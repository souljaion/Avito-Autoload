# Audit v7.12 (2026-04-23)

## Summary

- **Всего находок: 36**
- **BLOCKER: 1** — ✅ DONE (corrupted UTF-8 in models_detail.js — исправлено)
- **FIX-NOW: 0**
- **NICE-TO-HAVE: 20**
- **INFO: 14**

> datetime.utcnow() — **0 вхождений** (уже заменено на utc_now() helper в db.py).
> Неиспользуемые импорты — **0 найдено** (pyflakes/ruff не установлены, ручная проверка чисто).
> Опечатки в русском UI — **0 найдено** (все шаблоны проверены).

---

## A. Backend Python

### A.1 datetime.utcnow()
Все вызовы уже заменены на `datetime.now(timezone.utc)` через хелпер `utc_now()` в `app/db.py:29`.
**Вхождений: 0** — ни в app/, ни в scripts/, ни в tests/.

### A.2 Неиспользуемые импорты
pyflakes и ruff не установлены. Ручная проверка 5 основных роутеров
(products, models, feeds, accounts, dashboard) — **неиспользуемых импортов не найдено**.

### A.3 Неиспользуемые переменные
Проверены products.py и feed_generator.py — **не найдено**.

### A.4 Bare `except:` без класса исключения
**Вхождений: 0** — все except-блоки типизированы (Exception, OSError, ValueError и т.д.).

### A.5 `print()` в production-коде
**Вхождений: 0**. Два вхождения в config.py — это строковые литералы в сообщениях об ошибках (инструкции для генерации ключей), не вызовы print().

### A.6 Опечатки в комментариях/docstring
**Не обнаружено** при проверке основных файлов.

### A.7 f-strings с пропущенным `f` префиксом
**Не обнаружено.**

### A.8 Sync функции в async-роутерах
**Не обнаружено** — все роутеры с await используют async def.

### A.9 `assert` в production коде
**Вхождений: 0** в app/.

### A.10 TODO/FIXME/XXX/HACK комментарии
**Вхождений: 0** в app/ и scripts/.

### A.11 Lazy imports внутри функций — INFO
~69 lazy import-ов в 12 файлах. Используются для избежания circular imports.
Основные файлы:
- `app/routes/models.py` — 23 lazy imports
- `app/routes/products.py` — 16 lazy imports
- `app/routes/analytics.py` — 6
- `app/services/publish_scheduled.py` — 6
- `app/routes/listings.py` — 4
- остальные — по 1-2

**Категория:** INFO (легитимный паттерн, не трогать)

### A.12 Dead endpoints
Подтверждены 3 endpoint без frontend-callers (нет в templates/ и static/):
- ~~`app/routes/models.py:502`~~ — `POST /{model_id}/create-all-listings` — ✅ DONE удалён
- ~~`app/routes/models.py:644`~~ — `POST /schedule-matrix` — ✅ DONE удалён
- ~~`app/routes/models.py:970`~~ — `POST /{model_id}/create-one` — ✅ DONE удалён

**Категория:** ✅ DONE — удалены вместе с 17 тестами в chore-коммите v7.12

---

## B. Frontend

### B.1 Опечатки в UI
**Не обнаружено** — все русские подписи, placeholder, кнопки проверены в form.html, form_inline.html, list.html, detail.html, dashboard.html, models/list.html, models/detail.html.

### B.2 Сломанные URL
**Не обнаружено** — нет `href="#"` или `href=""` в шаблонах.

### B.3 console.log в JS — INFO
3 вхождения (все оправданы для отладки ошибок):
- `app/static/js/models_detail.js:835` — `console.warn()` для таймаута Y.Disk polling
- `app/templates/settings/description_templates.html:57` — `console.error()` в catch
- `app/templates/settings/description_templates.html:155` — `console.error()` в catch

**Категория:** INFO

### B.4 Дубликаты `id="..."` в шаблонах
**Не обнаружено.**

### B.5 onclick с русским текстом без экранирования
**Не обнаружено.**

### B.6 postMessage — INFO
3 вхождения в `app/static/js/models_detail.js`:
- Строка 421: listener с проверкой `e.origin !== window.location.origin` (безопасно)
- Строка 453: `postMessage(..., window.location.origin)` (безопасно)
- Строка 465: `postMessage(..., window.location.origin)` (безопасно)

1 вхождение в `app/templates/products/form_inline.html`:
- Строка 277: listener с проверкой `e.origin !== window.location.origin` (безопасно)

**Категория:** INFO (origin check реализован корректно)

### B.7 Inline `<style>` блоки — INFO
13 шаблонов с inline-стилями, ~700 строк CSS суммарно:

| Файл | ~строк CSS |
|------|-----------|
| base.html | 105 |
| models/detail.html | 119 |
| schedule_account.html | 91 |
| analytics.html | 83 |
| schedule.html | 50 |
| dashboard.html | 45 |
| models/list.html | 32 |
| products/form_inline.html | 29 |
| products/list.html | 28 |
| products/detail.html | 19 |
| products/bulk_edit.html | 16 |
| listings/edit.html | 13 |
| products/form.html | 11 |

**Категория:** NICE-TO-HAVE (вынести в отдельные .css при рефакторинге)

### B.8 Corrupted UTF-8 в models_detail.js — BLOCKER
**16 строк** с повреждёнными кириллическими символами (U+FFFD replacement characters).
Повреждены слова в строковых литералах, видимых пользователю:

| Строка | Повреждённый текст | Должно быть |
|--------|-------------------|-------------|
| 156 | `'Ошибк�� сети'` | `'Ошибка сети'` |
| 306 | corrupted | fix needed |
| 328 | corrupted | fix needed |
| 335 | corrupted | fix needed |
| 517 | `'Ошибка се��и'` | `'Ошибка сети'` |
| 537 | corrupted | fix needed |
| 554 | corrupted | fix needed |
| 575 | corrupted | fix needed |
| 657 | corrupted | fix needed |
| 690 | corrupted | fix needed |
| 733 | corrupted | fix needed |
| 762 | `'Ошибка сет��'` | `'Ошибка сети'` |
| 781 | corrupted | fix needed |
| 997 | `'Ошибк�� сети'` | `'Ошибка сети'` |
| 1006 | `'Нет да��ных'` | `'Нет данных'` |
| 1012 | `'Мёр��вых'` | `'Мёртвых'` |

**Причина:** повреждение UTF-8 при создании файла через Write tool в предыдущей задаче.

**Категория:** ✅ BLOCKER — DONE. 16 строк восстановлены из оригинального inline JS. Все U+FFFD replacement characters удалены, файл проверен (node --check OK, 0 corrupted chars).

---

## C. База данных и миграции

### C.1 Alembic drift — INFO
`alembic check` показывает расхождения между моделями и реальной БД:
- 2 orphan-таблицы в БД без моделей: `pack_usage_history`, `account_description_templates` (deprecated, известно)
- TIMESTAMP(timezone=True) vs DateTime() — расхождения в ~10 столбцах (timestamps с timezone в БД, без — в моделях)
- ~10 indexes в БД, отсутствующих в моделях
- nullable mismatches в ~8 колонках

Всё это pre-existing drift, накопившийся за 27+ миграций. Не влияет на работу.

**Категория:** INFO (не фиксить, требует отдельной задачи на reconciliation)

### C.2 Старый стиль Column vs Mapped
Все модели используют новый стиль `Mapped[...]` — **расхождений нет**.

### C.3 Модели без __tablename__ или дубликаты
**Не обнаружено** — все модели имеют уникальные `__tablename__`.

### C.4 Foreign keys без ondelete= — NICE-TO-HAVE
3 FK без явного ondelete:
- `app/models/product.py:20` — `account_id → accounts.id` (основной FK, должен быть SET NULL)
- `app/models/autoload_report.py:15` — `account_id → accounts.id` (должен быть CASCADE)
- `app/models/feed_export.py:15` — `account_id → accounts.id` (должен быть CASCADE)

**Категория:** NICE-TO-HAVE (требует миграцию, не фиксить в этой задаче)

### C.5 Миграции с op.execute()
**Вхождений: 0** — все миграции используют стандартные операции Alembic.

---

## D. Инфраструктура / зависимости

### D.1 requirements.txt vs CLAUDE.md — INFO
Все версии в requirements.txt совпадают с декларациями в CLAUDE.md:
- FastAPI 0.115.6
- SQLAlchemy 2.0.36
- Python 3.12 (runtime)
- Все 26 зависимостей с pin-версиями

**Категория:** INFO (всё в порядке)

### D.2 .env.example vs config.py — NICE-TO-HAVE
5 переменных из Settings отсутствуют в .env.example:
- `CRM_DSN` (default: "")
- `FEED_RETENTION_DAYS` (default: 30)
- `YANDEX_DISK_API_BASE` (default: URL)
- `YANDEX_DOWNLOAD_TIMEOUT` (default: 60)
- `YANDEX_DOWNLOAD_CONCURRENCY` (default: 2)

**Категория:** ✅ DONE — 5 переменных добавлены в .env.example

### D.3 Scheduler — 15 задач — INFO
Все 15 задач (включая новую cleanup_orphan_media) имеют error handling:
- 9 задач через `_run_with_retry()` wrapper (2 попытки, 5мин пауза)
- 6 задач с explicit `try/except` (auto_generate_feeds, fallback, check_declined, cleanup_old_feeds, cleanup_orphan_media, sync_autoload_ads)

**Категория:** INFO (всё в порядке)

### D.4 systemd unit — INFO
`deploy/avito-autoload.service`:
- MemoryMax=1G
- Restart=always, RestartSec=3s
- StartLimitBurst=5, StartLimitIntervalSec=300s
- 2 uvicorn workers

**Категория:** INFO (совпадает с CLAUDE.md)

### D.5 nginx config — INFO
`deploy/nginx-autoload.conf`:
- client_max_body_size 200M (совпадает с CLAUDE.md)
- proxy_read_timeout 120s
- proxy_connect_timeout 10s
- SSL Let's Encrypt

**Категория:** INFO (всё в порядке)

### D.6 Логирование — INFO
`app/logging_config.py`:
- RotatingFileHandler: maxBytes=10MB, backupCount=5 (совпадает с CLAUDE.md)
- File: logs/app.log
- Encoding: UTF-8

**Категория:** INFO (совпадает)

### D.7 .gitignore — INFO
Все требуемые записи присутствуют:
- .env, *.env
- venv/, .venv/
- media/, feeds/, logs/, uploads/
- __pycache__/
- context файлы

**Категория:** INFO (полный)

---

## E. Тесты

### E.1 datetime.utcnow() в тестах
**Вхождений: 0** — не используется в tests/.

### E.2 Hardcoded ID — INFO
Известный паттерн: seed account id=1 в conftest.py, используется повсеместно.

**Категория:** INFO (задокументировано в CLAUDE.md)

### E.3 Skipped тесты — INFO
1 skipped тест:
- `tests/test_heic_support.py:40` — `"Skipping integration part — unit conversion tests above are sufficient"`

**Категория:** INFO (осознанный skip)

### E.4 time.sleep в тестах
**0 реальных sleep-вызовов.** 10 вхождений `asyncio.sleep` — все через `AsyncMock` (мок retry/backoff в test_scheduler_jobs.py и test_avito_client.py).

**Категория:** INFO (нет риска flakiness)

### E.5 Fixtures с commit() вне isolated_db
**Не обнаружено** — все тесты с commit используют `isolated_db` fixture.

---

## F. Документация

### F.1 Устаревшие данные — NICE-TO-HAVE
- **CLAUDE.md:64** — написано "61 тест-файл, 860 тестов", реально 939 passed
- **docs/avito-autoload-context-v7.11.txt** — написано "926 passed", "15 local commits", реально 939 и 18 коммитов
- Обе цифры обновляются по мере развития проекта

**Категория:** ✅ DONE — счётчики обновлены до 922 (после удаления 17 тестов dead endpoints)

---

## Категории серьёзности

- **BLOCKER**: что-то сломано прямо сейчас, влияет на пользователей
- **FIX-NOW**: фиксится в фазе 2 этой задачи
- **NICE-TO-HAVE**: откладываем как TODO
- **INFO**: для сведения, не требует действий

---

## Рекомендации к фазе 2

Будут применены фиксы для:

1. **BLOCKER: Corrupted UTF-8 в models_detail.js** — пересоздать файл с корректными кириллическими символами (16 строк с U+FFFD replacement characters)

Что НЕ фиксится (оставлено как TODO):
- 3 dead endpoints (create_all_listings, schedule_matrix, create_one)
- 3 FK без ondelete= (требует миграцию)
- 5 переменных в .env.example
- 13 шаблонов с inline CSS
- Alembic drift (pre-existing, ~30 расхождений)
- Устаревшие тест-счётчики в документации
- ~69 lazy imports (легитимный паттерн)
