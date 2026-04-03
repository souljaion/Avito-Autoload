"""
Sync Avito category tree and field definitions into local DB.

Avito API endpoints:
  - Tree:   GET /autoload/v1/user-docs/tree
  - Fields: GET /autoload/v1/user-docs/node/{slug}/fields
"""

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utc_now
from app.models.avito_category import AvitoCategory
from app.services.avito_client import AvitoClient, AVITO_API_BASE

logger = structlog.get_logger(__name__)


async def sync_tree(client: AvitoClient, db: AsyncSession) -> int:
    """Fetch full category tree from Avito and replace local cache.

    Returns number of categories stored.
    Raises on auth/network errors. Rolls back on parse errors
    so existing data is preserved.
    """
    headers = await client._headers()
    resp = await client._client.get(
        f"{AVITO_API_BASE}/autoload/v1/user-docs/tree",
        headers=headers,
    )
    resp.raise_for_status()
    data = resp.json()

    # API may return {"categories": [...]} or just [...]
    if isinstance(data, list):
        root_nodes = data
    elif isinstance(data, dict):
        root_nodes = data.get("categories", [])
    else:
        raise ValueError(f"Unexpected response type: {type(data)}")

    if not root_nodes:
        raise ValueError("Empty category tree from Avito API")

    # Clear old data and insert new — all in one transaction
    await db.execute(delete(AvitoCategory))
    await db.flush()

    now = utc_now()

    async def _insert_nodes(nodes: list[dict], parent_id: int | None) -> int:
        inserted = 0
        for node in nodes:
            cat = AvitoCategory(
                avito_id=node.get("id"),
                slug=node.get("slug"),
                name=node["name"],
                parent_id=parent_id,
                show_fields=node.get("show_fields", False),
                synced_at=now,
            )
            db.add(cat)
            await db.flush()  # get cat.id
            inserted += 1

            children = node.get("nested") or []
            if children:
                inserted += await _insert_nodes(children, cat.id)
        return inserted

    count = await _insert_nodes(root_nodes, None)
    await db.commit()
    logger.info("Synced %d categories from Avito", count)
    return count


class FieldsUnavailable(Exception):
    """Avito API does not provide fields for this category (400/404)."""
    pass


async def sync_fields(client: AvitoClient, db: AsyncSession, slug: str) -> bool:
    """Fetch fields for a category node by slug and store in fields_data.

    Returns True if fields were saved.
    Raises FieldsUnavailable if Avito returns 400/404 for this node.
    """
    # Find category by slug first, then by name
    stmt = select(AvitoCategory).where(AvitoCategory.slug == slug)
    result = await db.execute(stmt)
    cat = result.scalar_one_or_none()

    if not cat:
        stmt = select(AvitoCategory).where(AvitoCategory.name == slug)
        result = await db.execute(stmt)
        cat = result.scalar_one_or_none()

    if not cat:
        logger.warning("Category not found for slug/name: %s", slug)
        return False

    headers = await client._headers()

    node_ref = cat.slug or str(cat.avito_id)
    resp = await client._client.get(
        f"{AVITO_API_BASE}/autoload/v1/user-docs/node/{node_ref}/fields",
        headers=headers,
    )

    if resp.status_code in (400, 404):
        # Avito doesn't serve fields for this node — mark as unavailable
        cat.fields_data = {"_unavailable": True, "_status": resp.status_code}
        cat.synced_at = utc_now()
        await db.commit()
        logger.info("Fields unavailable for: %s (%s) — HTTP %d", cat.name, node_ref, resp.status_code)
        raise FieldsUnavailable(
            f"Avito не предоставляет поля для «{cat.name}» (HTTP {resp.status_code})"
        )

    resp.raise_for_status()

    cat.fields_data = resp.json()
    cat.synced_at = utc_now()
    await db.commit()
    logger.info("Synced fields for category: %s (%s)", cat.name, node_ref)
    return True
