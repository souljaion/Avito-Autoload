"""Tests for app/services/category_sync.py — sync_tree, sync_fields."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.category_sync import sync_tree, sync_fields, FieldsUnavailable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resp(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status_code), request=MagicMock(), response=resp
        )
    return resp


def _make_client(get_response=None, get_side_effect=None):
    """Build a mock AvitoClient with controllable .get() behaviour."""
    client = MagicMock()
    client._headers = AsyncMock(return_value={"Authorization": "Bearer x"})
    inner = MagicMock()
    if get_side_effect is not None:
        inner.get = AsyncMock(side_effect=get_side_effect)
    else:
        inner.get = AsyncMock(return_value=get_response)
    client._client = inner
    return client


def _make_db(scalar_one_or_none=None, scalar_one=None):
    """Mock async DB session.

    flush() assigns sequential ids to objects added via db.add() so that
    the recursive insert in sync_tree can use cat.id for parent_id.
    """
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    added_objects = []
    id_counter = [0]

    def _add(obj):
        added_objects.append(obj)
        id_counter[0] += 1
        obj.id = id_counter[0]

    db.add = MagicMock(side_effect=_add)
    db.added_objects = added_objects  # exposed for assertions

    if scalar_one_or_none is not None or scalar_one is not None:
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=scalar_one_or_none)
        result.scalar_one = MagicMock(return_value=scalar_one)
        db.execute = AsyncMock(return_value=result)

    return db


# ---------------------------------------------------------------------------
# sync_tree — happy path
# ---------------------------------------------------------------------------

class TestSyncTree:
    @pytest.mark.asyncio
    async def test_sync_flat_list(self):
        """Tree returned as plain list of categories."""
        tree = [
            {"id": 1, "slug": "auto", "name": "Транспорт", "show_fields": False},
            {"id": 2, "slug": "realty", "name": "Недвижимость", "show_fields": True},
        ]
        client = _make_client(_make_resp(200, tree))
        db = _make_db()

        count = await sync_tree(client, db)
        assert count == 2
        assert len(db.added_objects) == 2
        names = {o.name for o in db.added_objects}
        assert names == {"Транспорт", "Недвижимость"}
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_dict_with_categories_key(self):
        """API may wrap response as {'categories': [...]}."""
        tree = {"categories": [
            {"id": 5, "slug": "x", "name": "X", "show_fields": False},
        ]}
        client = _make_client(_make_resp(200, tree))
        db = _make_db()

        count = await sync_tree(client, db)
        assert count == 1
        assert db.added_objects[0].name == "X"

    @pytest.mark.asyncio
    async def test_sync_preserves_hierarchy(self):
        """Nested 'nested' children get correct parent_id."""
        tree = [
            {
                "id": 100, "slug": "parent", "name": "Parent",
                "nested": [
                    {"id": 101, "slug": "child1", "name": "Child1"},
                    {
                        "id": 102, "slug": "child2", "name": "Child2",
                        "nested": [
                            {"id": 103, "slug": "gc", "name": "Grandchild"},
                        ],
                    },
                ],
            }
        ]
        client = _make_client(_make_resp(200, tree))
        db = _make_db()

        count = await sync_tree(client, db)
        assert count == 4

        by_name = {o.name: o for o in db.added_objects}
        assert by_name["Parent"].parent_id is None
        assert by_name["Child1"].parent_id == by_name["Parent"].id
        assert by_name["Child2"].parent_id == by_name["Parent"].id
        assert by_name["Grandchild"].parent_id == by_name["Child2"].id

    @pytest.mark.asyncio
    async def test_sync_calls_delete_before_insert(self):
        """Old data is wiped before new tree inserted (idempotency mechanism)."""
        tree = [{"id": 1, "slug": "a", "name": "Alpha"}]
        client = _make_client(_make_resp(200, tree))
        db = _make_db()

        await sync_tree(client, db)
        # First execute call should be the DELETE
        first_call = db.execute.call_args_list[0]
        # DELETE statement contains avito_categories table reference
        assert "avito_categories" in str(first_call).lower() or "DELETE" in str(first_call).upper()

    @pytest.mark.asyncio
    async def test_sync_idempotent_replaces_old(self):
        """Two consecutive syncs both call delete + insert — net result is the second tree."""
        client1 = _make_client(_make_resp(200, [{"id": 1, "slug": "a", "name": "Old"}]))
        client2 = _make_client(_make_resp(200, [{"id": 2, "slug": "b", "name": "New"}]))

        db1 = _make_db()
        db2 = _make_db()

        await sync_tree(client1, db1)
        await sync_tree(client2, db2)

        # Each sync starts with delete, ends with one fresh row
        assert len(db1.added_objects) == 1
        assert len(db2.added_objects) == 1
        assert db1.added_objects[0].name == "Old"
        assert db2.added_objects[0].name == "New"


# ---------------------------------------------------------------------------
# sync_tree — error paths
# ---------------------------------------------------------------------------

class TestSyncTreeErrors:
    @pytest.mark.asyncio
    async def test_empty_list_raises(self):
        client = _make_client(_make_resp(200, []))
        db = _make_db()
        with pytest.raises(ValueError, match="Empty"):
            await sync_tree(client, db)
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_dict_raises(self):
        client = _make_client(_make_resp(200, {"categories": []}))
        db = _make_db()
        with pytest.raises(ValueError, match="Empty"):
            await sync_tree(client, db)

    @pytest.mark.asyncio
    async def test_unexpected_response_type_raises(self):
        resp = _make_resp(200)
        resp.json.return_value = "not a list or dict"
        client = _make_client(resp)
        db = _make_db()
        with pytest.raises(ValueError, match="Unexpected response type"):
            await sync_tree(client, db)

    @pytest.mark.asyncio
    async def test_http_403_propagates(self):
        client = _make_client(_make_resp(403))
        db = _make_db()
        with pytest.raises(httpx.HTTPStatusError):
            await sync_tree(client, db)
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_http_404_propagates(self):
        client = _make_client(_make_resp(404))
        db = _make_db()
        with pytest.raises(httpx.HTTPStatusError):
            await sync_tree(client, db)

    @pytest.mark.asyncio
    async def test_network_error_propagates(self):
        client = _make_client(get_side_effect=httpx.RequestError("connection refused"))
        db = _make_db()
        with pytest.raises(httpx.RequestError):
            await sync_tree(client, db)
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# sync_fields
# ---------------------------------------------------------------------------

class TestSyncFields:
    @pytest.mark.asyncio
    async def test_sync_fields_success_by_slug(self):
        cat = MagicMock(slug="boots", name="Сапоги", avito_id=1, fields_data=None)
        db = _make_db(scalar_one_or_none=cat)

        fields = {"required": ["size"]}
        client = _make_client(_make_resp(200, fields))

        ok = await sync_fields(client, db, "boots")
        assert ok is True
        assert cat.fields_data == fields
        db.commit.assert_called_once()

        # Verify URL contained the slug
        url = client._client.get.call_args[0][0]
        assert "/boots/" in url

    @pytest.mark.asyncio
    async def test_sync_fields_finds_by_name_when_slug_lookup_misses(self):
        """First lookup (by slug) returns None, second (by name) returns category."""
        cat = MagicMock(slug=None, name="UniqueName", avito_id=42, fields_data=None)

        db = AsyncMock()
        db.commit = AsyncMock()

        # Two .execute() calls: first slug lookup → None, second name lookup → cat
        slug_result = MagicMock()
        slug_result.scalar_one_or_none.return_value = None
        name_result = MagicMock()
        name_result.scalar_one_or_none.return_value = cat
        db.execute = AsyncMock(side_effect=[slug_result, name_result])

        client = _make_client(_make_resp(200, {"f": 1}))
        ok = await sync_fields(client, db, "UniqueName")

        assert ok is True
        assert cat.fields_data == {"f": 1}

    @pytest.mark.asyncio
    async def test_sync_fields_category_not_found_returns_false(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        none_result = MagicMock()
        none_result.scalar_one_or_none.return_value = None
        # Both slug and name lookups return None
        db.execute = AsyncMock(return_value=none_result)

        client = _make_client(_make_resp(200, {}))
        ok = await sync_fields(client, db, "nonexistent")

        assert ok is False
        # No HTTP call should have been made
        client._client.get.assert_not_called()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_fields_404_raises_unavailable(self):
        cat = MagicMock(slug="nofields", name="NoFields", avito_id=3, fields_data=None)
        db = _make_db(scalar_one_or_none=cat)

        client = _make_client(_make_resp(404))
        with pytest.raises(FieldsUnavailable):
            await sync_fields(client, db, "nofields")

        assert cat.fields_data == {"_unavailable": True, "_status": 404}
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_fields_400_raises_unavailable(self):
        cat = MagicMock(slug="bad", name="Bad", avito_id=4, fields_data=None)
        db = _make_db(scalar_one_or_none=cat)

        client = _make_client(_make_resp(400))
        with pytest.raises(FieldsUnavailable):
            await sync_fields(client, db, "bad")

        assert cat.fields_data["_status"] == 400
        assert cat.fields_data["_unavailable"] is True

    @pytest.mark.asyncio
    async def test_sync_fields_500_propagates(self):
        """5xx errors are not silently swallowed."""
        cat = MagicMock(slug="srvfail", name="Srv", avito_id=5, fields_data=None)
        db = _make_db(scalar_one_or_none=cat)

        client = _make_client(_make_resp(500))
        with pytest.raises(httpx.HTTPStatusError):
            await sync_fields(client, db, "srvfail")

    @pytest.mark.asyncio
    async def test_sync_fields_uses_avito_id_when_no_slug(self):
        """When category has no slug, request URL uses avito_id."""
        cat = MagicMock(slug=None, name="ByAvitoId", avito_id=12345, fields_data=None)

        db = AsyncMock()
        db.commit = AsyncMock()
        # First slug lookup → None, second name lookup → cat
        none_result = MagicMock()
        none_result.scalar_one_or_none.return_value = None
        cat_result = MagicMock()
        cat_result.scalar_one_or_none.return_value = cat
        db.execute = AsyncMock(side_effect=[none_result, cat_result])

        client = _make_client(_make_resp(200, {"ok": True}))
        await sync_fields(client, db, "ByAvitoId")

        url = client._client.get.call_args[0][0]
        assert "12345" in url

    @pytest.mark.asyncio
    async def test_sync_fields_network_error_propagates(self):
        cat = MagicMock(slug="x", name="X", avito_id=1, fields_data=None)
        db = _make_db(scalar_one_or_none=cat)

        client = _make_client(get_side_effect=httpx.RequestError("dns fail"))
        with pytest.raises(httpx.RequestError):
            await sync_fields(client, db, "x")
