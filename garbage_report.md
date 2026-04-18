# Test Garbage in Production Database — Diagnostic Report

**Database:** `postgresql+asyncpg://avito_user:avito_pass@localhost:5433/avito_autoload`
**Generated:** 2026-04-18
**Status:** READ-ONLY diagnostic — no records deleted

---

## Summary

| Table | Garbage rows | Total rows | % garbage |
|-------|-------------|------------|-----------|
| products | **504** | 1,397 | 36.1% |
| models | 0 | — | — |
| photo_packs | 0 | — | — |
| accounts | 0 (4 real: Parker/Рыбка/Zulla/Crosstherapy) | 4 | 0% |
| model_variants | 0 | — | — |
| listings (FK from products) | **111** | 984 | 11.3% |

**Root cause:** Tests were running against production database (no guard existed).
The `db` fixture in conftest.py uses rollback, but integration tests via the `client`
fixture hit the live server at localhost:8001, which commits to prod.

---

## products (504 rows)

### By title pattern

| Title | Count | First seen | Last seen | Status |
|-------|-------|------------|-----------|--------|
| Auto Listing Test | 128 | 2026-04-03 | 2026-04-18 | draft (mostly), some removed |
| Patch Price Test | 128 | 2026-04-06 | 2026-04-18 | draft |
| Test Product Pytest | 128 | 2026-04-06 | 2026-04-18 | draft |
| Patch Status Test | 119 | 2026-04-06 | 2026-04-18 | active |
| TEST Auto Listing | 1 | 2026-04-03 | 2026-04-03 | draft |

### Characteristics
- **account_id:** NULL for most (Test Product Pytest, Patch *), account_id=1 (Parker) for Auto Listing Test
- **model_id:** all NULL
- **product_images:** 0 for all 504 rows
- **product_yandex_folders:** 0
- **product_publish_history:** 0
- **item_stats:** 0

### Date pattern
Rows span 2026-04-03 to 2026-04-18 (today). Each pytest run created 3-4 rows
that were NOT rolled back (integration tests via httpx client → live server).

---

## listings (111 rows)

111 listings reference the garbage products above (via `product_id` FK).
- **listing_images:** 0 (no child images)
- All created as side effects of product creation in integration tests.

---

## "YD Test — delete me" (product 1449)

Product ID 1449 does **NOT exist** in the database. The v7.3 E2E smoke test
correctly cleaned it up (or it was deleted as claimed). Confirmed clean.

---

## models, photo_packs, accounts, model_variants

All clean — zero test garbage found in these tables.

---

## Suggested DELETE Plan

**Order matters due to FK constraints. All FKs use CASCADE on products, but
listings have a separate FK. Execute in this order:**

```sql
-- Step 1: Delete orphan listings referencing garbage products
-- (listings.product_id → products.id, no CASCADE — must delete explicitly)
DELETE FROM listings
WHERE product_id IN (
    SELECT id FROM products
    WHERE title IN ('Auto Listing Test', 'Test Product Pytest',
                    'Patch Price Test', 'Patch Status Test',
                    'TEST Auto Listing')
);
-- Expected: ~111 rows

-- Step 2: Delete garbage products
-- (product_images, product_yandex_folders, product_publish_history,
--  item_stats all have 0 rows referencing these, so no cascade needed)
DELETE FROM products
WHERE title IN ('Auto Listing Test', 'Test Product Pytest',
                'Patch Price Test', 'Patch Status Test',
                'TEST Auto Listing');
-- Expected: 504 rows

-- Step 3: Verify
SELECT COUNT(*) FROM products
WHERE title ILIKE '%test%' OR title ILIKE '%pytest%'
   OR title ILIKE '%delete me%' OR title ILIKE '%patch price%'
   OR title ILIKE '%auto listing%';
-- Expected: 0
```

### CASCADE implications
- `product_images` → CASCADE on `product_id` — 0 rows affected (already empty)
- `product_yandex_folders` → CASCADE on `product_id` — 0 rows affected
- `product_publish_history` → CASCADE on `product_id` — 0 rows affected
- `item_stats` → has FK but 0 rows affected
- `listings` → FK to products, **NOT CASCADE** — must delete first (Step 1)
- `listing_images` → CASCADE on `listing_id` — 0 rows affected

### Risk assessment
- **Low risk**: All garbage rows have no real data (no images, no stats, no history)
- **No avito_id**: None of these rows have avito_ids, so they won't appear in feeds
- **No model links**: None linked to models, so no impact on model pages
- **"Patch Status Test" rows have status=active**: These could theoretically appear
  in feed generation, but since they have no account_id and no images, they'd be
  filtered out by `is_ready_for_feed`.

---

## Prevention

Task 1 of this session added a hard guard in `tests/conftest.py` that refuses to
run pytest against the production database. This should prevent future accumulation.
The test database `avito_autoload_test` has been created and tested.
