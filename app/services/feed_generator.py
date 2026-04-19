import os
from datetime import datetime, timezone

import aiofiles
import structlog
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings

logger = structlog.get_logger(__name__)
from app.models.account import Account
from app.models.account_description_template import AccountDescriptionTemplate
from app.models.description_template import DescriptionTemplate
from app.models.product import Product
from app.models.feed_export import FeedExport


def _add_element(parent: etree._Element, tag: str, text: str | None, cdata: bool = False):
    if text is None:
        return
    text_str = str(text).strip()
    if text_str == "":
        return
    el = etree.SubElement(parent, tag)
    if cdata:
        el.text = etree.CDATA(text_str)
    else:
        el.text = text_str


def _add_images(ad: etree._Element, images, base_url: str, fallback_url: str | None = None):
    """Render <Images> block.

    Primary source: product.images relation (sorted by is_main desc, sort_order).
    Only images with download_status='ready' are included.
    Fallback: a single fallback_url (product.image_url) — used for imported
    items that have an Avito CDN URL but no rows in product_images yet.
    """
    if images:
        ready_images = [
            img for img in images
            if getattr(img, "download_status", "ready") == "ready"
        ]
        if ready_images:
            imgs_el = etree.SubElement(ad, "Images")
            sorted_images = sorted(ready_images, key=lambda x: (not x.is_main, x.sort_order))[:10]
            for img in sorted_images:
                url = img.url
                if url.startswith("/"):
                    url = base_url.rstrip("/") + url
                img_el = etree.SubElement(imgs_el, "Image")
                img_el.set("url", url)
            return

    # Fallback: use product.image_url (typically an Avito CDN URL on imported items)
    if fallback_url and isinstance(fallback_url, str) and fallback_url.startswith("http"):
        imgs_el = etree.SubElement(ad, "Images")
        img_el = etree.SubElement(imgs_el, "Image")
        img_el.set("url", fallback_url)


_SHOE_GOODS_TYPES = {"Мужская обувь", "Женская обувь"}

_APPAREL_TYPE_MAP = {
    "Мужская одежда": "Одежда",
    "Женская одежда": "Одежда",
    "Аксессуары": "Аксессуары",
}

# For shoes, ApparelType must be the specific shoe type from Avito's dictionary
# (e.g. "Кроссовки", "Ботинки и полуботинки"), not the generic "Обувь".
# We use goods_subtype which already contains the correct value.


def is_ready_for_feed(product: Product, has_account_template: bool = False) -> bool:
    """Товар считается готовым к выгрузке, если заполнены все обязательные поля.

    Status is NOT checked — scheduled/active/draft products can all be ready.
    If has_account_template=True and use_custom_description=False,
    description is considered filled (comes from account template at feed time).

    Imported products require avito_id + at least one image source + brand +
    goods_type. Avito validates the full <Ad> block in the feed regardless of
    <AvitoId>, so missing required fields cause Avito to reject the whole feed.
    """
    # Imported products: minimal viable Ad — Avito won't accept feed entries
    # without GoodsType / Brand / Images even if AvitoId is present.
    if product.status == "imported":
        if not product.avito_id:
            return False
        has_image = bool(product.images) or bool(product.image_url)
        if not has_image:
            return False
        if not product.brand or not product.goods_type:
            return False
        return True

    if not product.title:
        return False
    has_description = bool(product.description)
    if not has_description and not product.use_custom_description and has_account_template:
        has_description = True
    if not has_description:
        return False
    if product.price is None:
        return False
    if not product.category or not product.goods_type:
        return False
    if not product.subcategory or not product.goods_subtype:
        return False
    if not product.images:
        return False
    return True


def build_ad_element(product: Product, account: Account, base_url: str, description_override: str | None = None) -> etree._Element:
    ad = etree.Element("Ad")

    _add_element(ad, "Id", str(product.id))
    if product.avito_id:
        _add_element(ad, "AvitoId", str(product.avito_id))
    _add_element(ad, "Title", product.title)
    _add_element(ad, "Description", description_override if description_override is not None else product.description, cdata=True)
    _add_element(ad, "Category", product.category)

    if account.phone:
        _add_element(ad, "ContactPhone", account.phone)
    if account.address:
        _add_element(ad, "Address", account.address)

    extra = product.extra or {}

    _add_element(ad, "GoodsType", product.goods_type)
    if product.goods_type in _SHOE_GOODS_TYPES:
        # For shoes ApparelType = specific shoe type (goods_subtype)
        _add_element(ad, "ApparelType", product.goods_subtype)
    else:
        apparel_type = _APPAREL_TYPE_MAP.get(product.goods_type)
        if apparel_type:
            _add_element(ad, "ApparelType", apparel_type)
    _add_element(ad, "Apparel", product.subcategory)
    _add_element(ad, "GoodsSubType", product.goods_subtype)
    _add_element(ad, "Condition", product.condition or "Новое с биркой")
    _add_element(ad, "AdType", extra.get("ad_type", "Товар приобретён на продажу"))
    _add_element(ad, "Availability", extra.get("availability", "В наличии"))
    _add_element(ad, "Color", product.color)
    _add_element(ad, "Brand", product.brand)

    if product.price is not None:
        _add_element(ad, "Price", str(product.price))

    _add_element(ad, "Size", product.size)
    if product.goods_type not in _SHOE_GOODS_TYPES:
        _add_element(ad, "MaterialsOdezhda", product.material)

    _add_images(ad, product.images, base_url, fallback_url=product.image_url)

    # Delivery
    delivery_val = extra.get("delivery")
    if delivery_val:
        delivery_el = etree.SubElement(ad, "Delivery")
        _add_element(delivery_el, "Option", delivery_val)
    delivery_subsidy_val = extra.get("delivery_subsidy")
    if delivery_subsidy_val:
        _add_element(ad, "DeliverySubsidy", delivery_subsidy_val)

    multi_item_val = extra.get("multi_item")
    if multi_item_val:
        _add_element(ad, "MultiItem", multi_item_val)
    try_on_val = extra.get("try_on")
    if try_on_val:
        _add_element(ad, "TryOn", try_on_val)

    return ad


async def generate_feed(account_id: int, db: AsyncSession) -> tuple[str, int]:
    """Generate XML feed for account. Returns (file_path, products_count)."""
    account = await db.get(Account, account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found")

    from sqlalchemy import or_, and_
    stmt = (
        select(Product)
        .options(selectinload(Product.images), selectinload(Product.description_template))
        .where(
            Product.account_id == account_id,
            or_(
                Product.status.in_(["active", "scheduled"]),
                and_(Product.status == "imported", Product.avito_id.isnot(None)),
            ),
        )
        .order_by(Product.id)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()

    # Also load recently removed products (within 48h) for removal from Avito
    from datetime import timedelta
    removal_cutoff = datetime.utcnow() - timedelta(hours=48)
    removed_stmt = (
        select(Product)
        .where(
            Product.account_id == account_id,
            Product.status == "removed",
            Product.removed_at >= removal_cutoff,
            Product.avito_id.isnot(None),
        )
    )
    removed_result = await db.execute(removed_stmt)
    removed_products = removed_result.scalars().all()

    # Load account description template for non-custom descriptions
    tmpl_result = await db.execute(
        select(AccountDescriptionTemplate).where(
            AccountDescriptionTemplate.account_id == account_id
        )
    )
    tmpl = tmpl_result.scalar_one_or_none()
    account_description = tmpl.description_template if tmpl else None

    base_url = settings.BASE_URL
    root = etree.Element("Ads", formatVersion="3", target="Avito.ru")

    included = 0
    skipped_invalid = 0
    for product in products:
        if not is_ready_for_feed(product, has_account_template=bool(account_description)):
            skipped_invalid += 1
            continue
        # Priority: 1) standalone template, 2) custom description, 3) account template
        if product.description_template_id is not None:
            if product.description_template is None:
                raise RuntimeError(
                    f"Product {product.id}: description_template not loaded — "
                    f"missing selectinload? (description_template_id={product.description_template_id})"
                )
            effective_description = product.description_template.body
        elif not product.use_custom_description and account_description:
            effective_description = account_description
        else:
            effective_description = product.description
        ad = build_ad_element(product, account, base_url, description_override=effective_description)
        root.append(ad)
        included += 1

    if skipped_invalid:
        logger.info("feed_build.skipped_invalid", account=account.name, count=skipped_invalid)
    logger.info("feed_build", account=account.name, active=included,
                removed=len(removed_products), skipped_invalid=skipped_invalid)

    # Add removed products with <Status>Removed</Status>
    for product in removed_products:
        ad = etree.Element("Ad")
        _add_element(ad, "Id", str(product.id))
        if product.avito_id:
            _add_element(ad, "AvitoId", str(product.avito_id))
        _add_element(ad, "Status", "Removed")
        root.append(ad)

    xml_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)

    feeds_dir = settings.FEEDS_DIR
    os.makedirs(feeds_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{account_id}_{timestamp}.xml"
    filepath = os.path.join(feeds_dir, filename)

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(xml_bytes)

    # Also save as latest
    latest_path = os.path.join(feeds_dir, f"{account_id}.xml")
    async with aiofiles.open(latest_path, "wb") as f:
        await f.write(xml_bytes)

    # Record export
    export = FeedExport(
        account_id=account_id,
        file_path=filepath,
        products_count=included,
        status="generated",
    )
    db.add(export)
    await db.commit()

    return filepath, included
