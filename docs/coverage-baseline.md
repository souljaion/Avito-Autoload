# Coverage Baseline — 2026-04-15

Overall: **35%** (4111 statements, 2685 missed)

97 passed, 1 skipped

## Per-module coverage

| Module | Stmts | Miss | Cover |
|--------|-------|------|-------|
| app/config.py | 28 | 2 | 93% |
| app/db.py | 21 | 8 | 62% |
| app/logging_config.py | 25 | 25 | **0%** |
| app/main.py | 96 | 96 | **0%** |
| app/middleware/auth.py | 32 | 32 | **0%** |
| app/models/ (all) | — | — | 100% (except pack_usage_history 0%) |
| app/routes/accounts.py | 86 | 56 | 35% |
| app/routes/analytics.py | 201 | 93 | 54% |
| app/routes/autoload.py | 56 | 56 | **0%** |
| app/routes/categories.py | 66 | 66 | **0%** |
| app/routes/dashboard.py | 167 | 64 | 62% |
| app/routes/feeds.py | 176 | 46 | 74% |
| app/routes/images.py | 94 | 94 | **0%** |
| app/routes/listings.py | 229 | 229 | **0%** |
| app/routes/models.py | 443 | 443 | **0%** |
| app/routes/photo_packs.py | 109 | 109 | **0%** |
| app/routes/products.py | 629 | 549 | 13% |
| app/routes/reports.py | 57 | 35 | 39% |
| app/routes/schedule.py | 106 | 106 | **0%** |
| app/scheduler.py | 238 | 136 | 43% |
| app/services/avito_client.py | 209 | 128 | 39% |
| app/services/avito_import.py | 106 | 22 | 79% |
| app/services/category_sync.py | 65 | 65 | **0%** |
| app/services/feed_generator.py | 153 | 58 | 62% |
| app/services/image_processor.py | 55 | 9 | 84% |
| app/services/image_sync.py | 36 | 27 | 25% |
| app/services/photo_uniquifier.py | 38 | 29 | 24% |
| app/services/publish_scheduled.py | 70 | 7 | 90% |
| app/services/sold_detection.py | 49 | 11 | 78% |
| app/services/stats_sync.py | 53 | 4 | 92% |
| app/services/telegram_notify.py | 24 | 11 | 54% |

## Lowest coverage modules (by impact — stmts * miss%)

1. **app/routes/models.py** — 0% (443 statements, 443 missed)
2. **app/routes/products.py** — 13% (629 statements, 549 missed)
3. **app/routes/listings.py** — 0% (229 statements, 229 missed)

---

## After coverage sprint — 2026-04-15

Overall: **80%** (4236 statements, 846 missed)

421 passed, 1 skipped

| Module | Stmts | Miss | Cover | Delta |
|--------|-------|------|-------|-------|
| app/config.py | 35 | 4 | 89% | -4% |
| app/crypto.py | 10 | 0 | 100% | — |
| app/db.py | 21 | 8 | 62% | — |
| app/logging_config.py | 25 | 25 | **0%** | — |
| app/main.py | 96 | 96 | **0%** | — |
| app/middleware/auth.py | 32 | 32 | **0%** | — |
| app/models/ (all) | — | — | 100% | — |
| app/routes/accounts.py | 94 | 12 | 87% | **+52%** |
| app/routes/analytics.py | 223 | 53 | 76% | **+22%** |
| app/routes/autoload.py | 56 | 56 | **0%** | — |
| app/routes/categories.py | 66 | 12 | 82% | **+82%** |
| app/routes/dashboard.py | 166 | 26 | 84% | **+22%** |
| app/routes/feeds.py | 180 | 40 | 78% | +4% |
| app/routes/images.py | 94 | 6 | 94% | **+94%** |
| app/routes/listings.py | 229 | 28 | 88% | **+88%** |
| app/routes/models.py | 443 | 26 | 94% | **+94%** |
| app/routes/photo_packs.py | 109 | 5 | 95% | **+95%** |
| app/routes/products.py | 629 | 106 | 83% | **+70%** |
| app/routes/reports.py | 57 | 35 | 39% | — |
| app/routes/schedule.py | 94 | 0 | 100% | **+100%** |
| app/scheduler.py | 238 | 63 | 74% | **+31%** |
| app/schemas/model.py | 5 | 0 | 100% | **+100%** |
| app/schemas/product.py | 33 | 2 | 94% | +9% |
| app/services/avito_client.py | 273 | 10 | 96% | **+57%** |
| app/services/avito_import.py | 127 | 37 | 71% | -8% |
| app/services/category_sync.py | 65 | 54 | 17% | +17% |
| app/services/feed_generator.py | 153 | 8 | 95% | **+33%** |
| app/services/image_processor.py | 55 | 9 | 84% | — |
| app/services/image_sync.py | 36 | 0 | 100% | **+75%** |
| app/services/photo_uniquifier.py | 38 | 29 | 24% | — |
| app/services/publish_scheduled.py | 70 | 7 | 90% | — |
| app/services/sold_detection.py | 49 | 11 | 78% | — |
| app/services/stats_sync.py | 53 | 4 | 92% | — |
| app/services/telegram_notify.py | 24 | 0 | 100% | **+46%** |

### Biggest improvements
- routes/models.py: 0% → 94% (+94%)
- routes/photo_packs.py: 0% → 95% (+95%)
- routes/images.py: 0% → 94% (+94%)
- routes/listings.py: 0% → 88% (+88%)
- routes/categories.py: 0% → 82% (+82%)
- services/image_sync.py: 25% → 100% (+75%)
- routes/products.py: 13% → 83% (+70%)
- services/avito_client.py: 39% → 96% (+57%)
- routes/accounts.py: 35% → 87% (+52%)
- services/telegram_notify.py: 54% → 100% (+46%)
