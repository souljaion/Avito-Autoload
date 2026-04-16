"""Tests for autoload_sync: sync applied ads from Avito reports into products."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.db import get_db
from app.routes.autoload import router
from app.services.autoload_sync import sync_ads_from_avito


# ── Helpers ──

def _make_account(id=1, name="TestAcc", client_id="cid", client_secret="sec"):
    acc = MagicMock()
    acc.id = id
    acc.name = name
    acc.client_id = client_id
    acc.client_secret = client_secret
    acc.autoload_enabled = True
    return acc


def _make_report_item(ad_id, avito_id, status="applied"):
    return {"ad_id": ad_id, "avito_id": avito_id, "status": status, "url": f"https://avito.ru/{avito_id}"}


def _make_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


# ── Unit tests for sync_ads_from_avito ──

class TestSyncAdsFromAvito:
    @pytest.mark.asyncio
    async def test_creates_new_product_when_not_in_db(self):
        """Applied item with new avito_id creates a product."""
        account = _make_account()

        # Mock DB
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        # existing_by_avito_id: empty
        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        # existing_by_sku: empty
        r2_scalars = MagicMock()
        r2_scalars.all.return_value = []
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        # all_avito_ids: empty
        r3 = MagicMock()
        r3.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # Mock client
        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={
            "reports": [{"id": 100}]
        })
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 12345),
        ])
        mock_client.close = AsyncMock()

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["created"] == 1
        assert result["synced"] == 0
        assert result["skipped"] == 0
        assert result["error"] is None
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_existing_product_avito_id(self):
        """Product matched by sku/ad_id gets avito_id filled in."""
        account = _make_account()

        existing_product = MagicMock()
        existing_product.avito_id = None
        existing_product.sku = "ad_1"
        existing_product.account_id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        # existing_by_avito_id: empty
        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        # existing_by_sku: one product
        r2_scalars = MagicMock()
        r2_scalars.all.return_value = [existing_product]
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        # all_avito_ids: empty
        r3 = MagicMock()
        r3.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 99999),
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["synced"] == 1
        assert result["created"] == 0
        assert existing_product.avito_id == 99999

    @pytest.mark.asyncio
    async def test_skips_non_applied_status(self):
        """Items with status != 'applied' are skipped."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        r2_scalars = MagicMock()
        r2_scalars.all.return_value = []
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        r3 = MagicMock()
        r3.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 111, status="declined"),
            _make_report_item("ad_2", 222, status="processing"),
            _make_report_item("ad_3", 333, status="applied"),
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["skipped"] == 2
        assert result["created"] == 1

    @pytest.mark.asyncio
    async def test_pagination_merges_multiple_pages(self):
        """Items from multiple pages should all be processed."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        r2_scalars = MagicMock()
        r2_scalars.all.return_value = []
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        r3 = MagicMock()
        r3.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # Return 3 items — all from get_report_items_all (pagination is internal)
        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 111),
            _make_report_item("ad_2", 222),
            _make_report_item("ad_3", 333),
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["created"] == 3
        assert mock_db.add.call_count == 3

    @pytest.mark.asyncio
    async def test_api_error_does_not_crash(self):
        """API error should be caught and returned in result."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.rollback = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(side_effect=Exception("Connection timeout"))
        mock_client.close = AsyncMock()

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["error"] is not None
        assert "Connection timeout" in result["error"]
        assert result["created"] == 0

    @pytest.mark.asyncio
    async def test_no_reports_returns_error(self):
        """Empty reports list should return error, not crash."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": []})

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["error"] == "No reports found"
        assert result["created"] == 0

    @pytest.mark.asyncio
    async def test_skips_duplicate_avito_id_across_accounts(self):
        """If avito_id already exists on another account, skip it."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        r1_scalars = MagicMock()
        r1_scalars.all.return_value = []
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        r2_scalars = MagicMock()
        r2_scalars.all.return_value = []
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        # avito_id 12345 already exists on another account
        r3 = MagicMock()
        r3.all.return_value = [(12345,)]

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 12345),
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["skipped"] == 1
        assert result["created"] == 0

    @pytest.mark.asyncio
    async def test_pass2_fills_avito_id_by_exact_title(self):
        """Pass 2: Items API fills avito_id when product title matches exactly."""
        account = _make_account()

        # Product with no avito_id
        existing_product = MagicMock()
        existing_product.avito_id = None
        existing_product.title = "Nike Air Max 90"
        existing_product.account_id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        # Pass 1 queries: existing_by_avito_id, existing_by_sku, all_avito_ids
        r1_scalars = MagicMock(); r1_scalars.all.return_value = []
        r1 = MagicMock(); r1.scalars.return_value = r1_scalars
        r2_scalars = MagicMock(); r2_scalars.all.return_value = []
        r2 = MagicMock(); r2.scalars.return_value = r2_scalars
        r3 = MagicMock(); r3.all.return_value = []

        # Pass 2 query: products with NULL avito_id
        r4_scalars = MagicMock(); r4_scalars.all.return_value = [existing_product]
        r4 = MagicMock(); r4.scalars.return_value = r4_scalars

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3, r4])
        mock_db.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[])  # Pass 1: no report items
        mock_client.get_all_items = AsyncMock(return_value=[
            {"id": 77777, "title": "Nike Air Max 90", "price": 5000, "status": "active"},
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["avito_ids_filled"] == 1
        assert existing_product.avito_id == 77777
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_pass2_skips_when_title_does_not_match(self):
        """Pass 2: Items API does NOT fill avito_id if title doesn't match exactly."""
        account = _make_account()

        existing_product = MagicMock()
        existing_product.avito_id = None
        existing_product.title = "Nike Air Max 90"
        existing_product.account_id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        r1_scalars = MagicMock(); r1_scalars.all.return_value = []
        r1 = MagicMock(); r1.scalars.return_value = r1_scalars
        r2_scalars = MagicMock(); r2_scalars.all.return_value = []
        r2 = MagicMock(); r2.scalars.return_value = r2_scalars
        r3 = MagicMock(); r3.all.return_value = []

        r4_scalars = MagicMock(); r4_scalars.all.return_value = [existing_product]
        r4 = MagicMock(); r4.scalars.return_value = r4_scalars

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3, r4])
        mock_db.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[])
        mock_client.get_all_items = AsyncMock(return_value=[
            {"id": 77777, "title": "Adidas Yeezy 350", "price": 8000, "status": "active"},
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["avito_ids_filled"] == 0
        assert existing_product.avito_id is None

    @pytest.mark.asyncio
    async def test_existing_by_avito_id_counted_as_synced(self):
        """Product already matched by avito_id is counted as synced, not created."""
        account = _make_account()

        existing = MagicMock()
        existing.avito_id = 12345
        existing.account_id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)

        r1_scalars = MagicMock()
        r1_scalars.all.return_value = [existing]
        r1 = MagicMock()
        r1.scalars.return_value = r1_scalars

        r2_scalars = MagicMock()
        r2_scalars.all.return_value = []
        r2 = MagicMock()
        r2.scalars.return_value = r2_scalars

        r3 = MagicMock()
        r3.all.return_value = [(12345,)]

        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3])
        mock_db.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[
            _make_report_item("ad_1", 12345),
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["synced"] == 1
        assert result["created"] == 0

    # ── Pass 3 tests ──

    # Helper: build the 6 execute results expected by the refactored sync
    # (Pass1×3 + Pass2×1 + Pass3×2). Mocks empty unless overridden.
    @staticmethod
    def _execute_seq(
        all_avito_ids=None,
        pass2_null_products=None,
        pass3_acc_avito_ids=None,
        pass3_null_products=None,
    ):
        def _scalars_with(items):
            s = MagicMock()
            s.all.return_value = items or []
            r = MagicMock()
            r.scalars.return_value = s
            return r

        def _rows_with(rows):
            r = MagicMock()
            r.all.return_value = rows or []
            return r

        return [
            _scalars_with([]),                          # Pass1: existing_by_avito_id
            _scalars_with([]),                          # Pass1: existing_by_sku
            _rows_with([(x,) for x in (all_avito_ids or [])]),  # Pass1: all_avito_ids
            _scalars_with(pass2_null_products or []),   # Pass2: null avito_id
            _rows_with([(x,) for x in (pass3_acc_avito_ids or [])]),  # Pass3: per-account avito_ids
            _scalars_with(pass3_null_products or []),   # Pass3: null avito_id reload
        ]

    @pytest.mark.asyncio
    async def test_pass3_creates_imported_for_unknown_avito_id(self):
        """Pass 3: items not matched by avito_id OR title → product created."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.execute = AsyncMock(side_effect=self._execute_seq())
        mock_db.commit = AsyncMock()
        added: list = []
        mock_db.add = MagicMock(side_effect=added.append)

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[])
        mock_client.get_all_items = AsyncMock(return_value=[
            {"id": 555001, "title": "Brand New Sneakers", "price": 7500, "status": "active"},
            {"id": 555002, "title": "Another Pair", "price": 4200, "status": "active"},
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["pass3_created"] == 2
        assert result["pass3_matched"] == 0
        assert result["error"] is None
        assert len(added) == 2
        assert {p.avito_id for p in added} == {555001, 555002}
        for p in added:
            assert p.account_id == 1
            assert p.status == "imported"
            assert p.published_at is not None

    @pytest.mark.asyncio
    async def test_pass3_skips_avito_id_already_in_db(self):
        """Pass 3: avito_id already present → no duplicate created or matched."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.execute = AsyncMock(side_effect=self._execute_seq(
            all_avito_ids=[999_111],
            pass3_acc_avito_ids=[999_111],
        ))
        mock_db.commit = AsyncMock()
        added: list = []
        mock_db.add = MagicMock(side_effect=added.append)

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[])
        mock_client.get_all_items = AsyncMock(return_value=[
            {"id": 999111, "title": "Already Tracked", "price": 3000, "status": "active"},
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["pass3_created"] == 0
        assert result["pass3_matched"] == 0
        assert added == []

    @pytest.mark.asyncio
    async def test_pass3_counters_match_actual_inserts(self):
        """Pass 3: pass3_created counts only true new items; global dup is skipped."""
        account = _make_account()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.execute = AsyncMock(side_effect=self._execute_seq(
            all_avito_ids=[700001],   # held by another account
        ))
        mock_db.commit = AsyncMock()
        added: list = []
        mock_db.add = MagicMock(side_effect=added.append)

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[])
        mock_client.get_all_items = AsyncMock(return_value=[
            {"id": 700001, "title": "Globally Dup", "price": 1000, "status": "active"},
            {"id": 700002, "title": "Fresh One",    "price": 2000, "status": "active"},
            {"id": 700003, "title": "Fresh Two",    "price": 3000, "status": "active"},
            {"id": None,   "title": "No ID",        "price": 4000, "status": "active"},
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["pass3_created"] == 2
        assert result["pass3_matched"] == 0
        assert {p.avito_id for p in added} == {700002, 700003}

    # ── New: Pass 3 title matching ──

    @pytest.mark.asyncio
    async def test_pass3_matches_existing_imported_by_exact_title(self):
        """Pass 3: existing imported with NULL avito_id → avito_id filled, no insert."""
        account = _make_account()

        existing = MagicMock()
        existing.id = 99
        existing.avito_id = None
        existing.title = "Nike Pegasus 40"
        existing.account_id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        # Pass2 also sees this product but title in API differs from Pass2 input,
        # so Pass2 leaves it untouched. Pass3 reload returns the same product.
        mock_db.execute = AsyncMock(side_effect=self._execute_seq(
            pass3_null_products=[existing],
        ))
        mock_db.commit = AsyncMock()
        added: list = []
        mock_db.add = MagicMock(side_effect=added.append)

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[])
        mock_client.get_all_items = AsyncMock(return_value=[
            {"id": 333111, "title": "Nike Pegasus 40", "price": 6500, "status": "active"},
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["pass3_matched"] == 1
        assert result["pass3_created"] == 0
        assert existing.avito_id == 333111
        assert added == []

    @pytest.mark.asyncio
    async def test_pass3_matches_with_fuzzy_title(self):
        """Pass 3: title differs only in case + extra whitespace → still matches."""
        account = _make_account()

        existing = MagicMock()
        existing.id = 100
        existing.avito_id = None
        existing.title = "Adidas Yeezy 350 Boost"
        existing.account_id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.execute = AsyncMock(side_effect=self._execute_seq(
            pass3_null_products=[existing],
        ))
        mock_db.commit = AsyncMock()
        added: list = []
        mock_db.add = MagicMock(side_effect=added.append)

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[])
        mock_client.get_all_items = AsyncMock(return_value=[
            # Different case + double spaces → normalized exact match
            {"id": 444222, "title": "  ADIDAS  yeezy 350   boost  ", "price": 9000, "status": "active"},
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["pass3_matched"] == 1
        assert result["pass3_created"] == 0
        assert existing.avito_id == 444222
        assert added == []

    @pytest.mark.asyncio
    async def test_pass3_matches_by_50_char_prefix(self):
        """Pass 3: titles share the first 50 normalized characters → prefix match."""
        account = _make_account()

        existing = MagicMock()
        existing.id = 101
        existing.avito_id = None
        # 50+ chars; trailing differs
        # First 50 normalized chars: "brooks glycerin 21 premium running shoes mens runn"
        existing.title = "Brooks Glycerin 21 Premium Running Shoes Mens Running Black 42"
        existing.account_id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.execute = AsyncMock(side_effect=self._execute_seq(
            pass3_null_products=[existing],
        ))
        mock_db.commit = AsyncMock()
        added: list = []
        mock_db.add = MagicMock(side_effect=added.append)

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[])
        mock_client.get_all_items = AsyncMock(return_value=[
            # Same first 50 normalized chars; trailing differs → prefix match
            {"id": 555333, "title": "Brooks Glycerin 21 Premium Running Shoes Mens Running White 41",
             "price": 12000, "status": "active"},
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["pass3_matched"] == 1
        assert result["pass3_created"] == 0
        assert existing.avito_id == 555333
        assert added == []

    @pytest.mark.asyncio
    async def test_pass3_mixed_match_and_create(self):
        """Pass 3: one item matches existing imported, the other has no match → created."""
        account = _make_account()

        matchable = MagicMock()
        matchable.id = 200
        matchable.avito_id = None
        matchable.title = "New Balance 990v6"
        matchable.account_id = 1

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=account)
        mock_db.execute = AsyncMock(side_effect=self._execute_seq(
            pass3_null_products=[matchable],
        ))
        mock_db.commit = AsyncMock()
        added: list = []
        mock_db.add = MagicMock(side_effect=added.append)

        mock_client = AsyncMock()
        mock_client.get_reports = AsyncMock(return_value={"reports": [{"id": 100}]})
        mock_client.get_report_items_all = AsyncMock(return_value=[])
        mock_client.get_all_items = AsyncMock(return_value=[
            {"id": 800001, "title": "new balance 990v6", "price": 17000, "status": "active"},  # match
            {"id": 800002, "title": "Some Brand New Item", "price": 4200, "status": "active"},  # create
        ])

        result = await sync_ads_from_avito(1, mock_db, client=mock_client)

        assert result["pass3_matched"] == 1
        assert result["pass3_created"] == 1
        assert matchable.avito_id == 800001
        assert len(added) == 1
        assert added[0].avito_id == 800002


# ── Route tests ──

class TestSyncAdsEndpoint:
    @pytest.mark.asyncio
    async def test_account_not_found(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/accounts/999/autoload/sync-ads")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_credentials(self):
        acc = _make_account(client_id=None, client_secret=None)
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        app = _make_app(mock_db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/accounts/1/autoload/sync-ads")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_success(self):
        acc = _make_account()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        app = _make_app(mock_db)

        with patch("app.routes.autoload.sync_ads_from_avito", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = {"created": 5, "synced": 3, "skipped": 2, "error": None}

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/accounts/1/autoload/sync-ads")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["created"] == 5
        assert data["synced"] == 3
        assert data["skipped"] == 2

    @pytest.mark.asyncio
    async def test_sync_error_returns_502(self):
        acc = _make_account()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=acc)
        app = _make_app(mock_db)

        with patch("app.routes.autoload.sync_ads_from_avito", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = {"created": 0, "synced": 0, "skipped": 0, "error": "API timeout"}

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/accounts/1/autoload/sync-ads")

        assert resp.status_code == 502
        assert resp.json()["error"] == "API timeout"
