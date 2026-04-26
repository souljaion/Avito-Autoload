# CLAUDE.md — Avito Autoload

## 1. Обзор проекта

Avito Autoload — self-hosted веб-приложение для управления товарными объявлениями
на Avito (крупнейший российский маркетплейс). Бизнес-модель: ресейл одежды/обуви
через несколько аккаунтов Avito.

Система умеет:
- Создавать товары, управлять каталогом (категории, фото, описания, цены)
- Генерировать XML-фиды в формате Avito Autoload v3
- Загружать фиды в Avito через OAuth2 API
- Импортировать товары: с Avito (Items API), из Excel, из XML-фида
- Мониторить отчёты (applied/declined), собирать аналитику (просмотры, контакты, избранное)
- Планировать публикации по расписанию (inline и bulk)
- Работать с моделями и фотопаками для мультиаккаунтных схем
- Загружать фото из публичных папок Яндекс.Диска
- Управлять шаблонами описаний (standalone библиотека)
- Уникализировать фото для обхода Avito-дупликатора
- Отправлять Telegram-уведомления о блокировках

## 2. Стек и зависимости

| Компонент | ��ехнология | Версия |
|-----------|-----------|--------|
| Язык | Python | 3.12 |
| Фреймворк | FastAPI | 0.115.6 |
| ASGI-сервер | Uvicorn | 0.34.0 |
| ORM | SQLAlchemy (async) | 2.0.36 |
| Драйвер БД | asyncpg | 0.30.0 |
| БД | PostgreSQL | 14+ |
| Миграции | Alembic | 1.14.0 |
| Шаблонизатор | Jinja2 | 3.1.4 |
| HTTP-клиент | httpx | 0.28.1 |
| План��ровщик | APScheduler | 3.11.2 |
| XML | lxml | 5.3.0 |
| Изображения | Pillow + pillow-heif | 12.1.1 / 1.3.0 |
| Уникализация фото | numpy | 2.4.4 |
| Excel | openpyxl | 3.1.5 |
| Rate limiting | slowapi | 0.1.9 |
| Логирование | structlog | 24.4.0 |
| Мониторинг | sentry-sdk | 2.19.2 |
| Шифрование | cryptography (Fernet) | 44.0.2 |
| Валидация | Pydantic + pydantic-settings | 2.10.3 / 2.7.0 |
| Тесты | pytest + pytest-asyncio | 8.3.4 / 0.24.0 |

Фронтенд: **чистый HTML/CSS/JS** через Jinja2-шаблоны, без фреймворков и сборки.

## 3. Структура проекта

```
avito-autoload/
├── app/
│   ├── main.py                 # Точка входа FastAPI, lifespan, middleware, роутеры
│   ├── config.py               # Pydantic Settings (все env-переменные)
│   ├── db.py                   # SQLAlchemy engine + session + safe_update_status()
│   ├── cache.py                # In-memory TTL cache (asyncio.Lock)
│   ├── catalog.py              # Таксономия Avito (category → goods_type → subcategory → goods_subtype)
│   ├── crypto.py               # Fernet encrypt/decrypt для client_secret
│   ├── logging_config.py       # structlog + RotatingFileHandler
│   ├── rate_limit.py           # slowapi Limiter setup
│   ├── scheduler.py            # APScheduler: 14 фоно��ых задач + retry logic
│   │
│   ├── middleware/
│   │   └── auth.py             # HTTP Basic Auth middleware
│   │
│   ├── models/                 # SQLAlchemy ORM-модели (22 таблицы)
│   │   ├── account.py          # Аккаунт Avito с OAuth2 credentials
│   │   ├── product.py          # Товар (главная сущность, 30+ полей)
│   │   ├── product_image.py    # Фото товара (local/avito_cdn/yandex_disk)
│   │   ├── model.py            # Модель (шаблон для мультиаккаунтного товара)
│   │   ├── variant.py          # Вариант модели (размер/цвет/цена/pack)
│   │   ├── photo_pack.py       # Фотопак (набор фото для модели)
│   │   ├── photo_pack_image.py # Фото в паке
│   │   ├── listing.py          # Привязка product → account для публикации
│   │   ├── listing_image.py    # Фото листинга
│   │   ├── description_template.py    # Шаблон описания (standalone)
│   │   ├── account_description_template.py  # DEPRECATED
│   │   ├── feed_export.py      # Запись о сгенерированном XML-фиде
│   │   ├── item_stats.py       # Статистика просмотров/контактов/избранного
│   │   ├── autoload_report.py  # Отчёт Avito Autoload
│   │   ├── autoload_report_item.py  # Строка отчёта
│   │   ├── avito_category.py   # Категория из дерева Avito
│   │   ├── product_yandex_folder.py      # Привязка Я.Диска к товару
│   │   ├── product_publish_history.py    # История публикаций (для уникализации)
│   │   ├── photo_pack_yandex_folder.py   # Привязка Я.Диска к паку
│   │   ├── photo_pack_publish_history.py # История публи��аций пака
│   │   └── pack_usage_history.py         # История использования пака
│   │
│   ├── routes/                 # HTTP-эндпоинты (17 роутеров, ~117 endpoints)
│   │   ├── dashboard.py        # Командный центр + API
│   │   ├── products.py         # CRUD товаров, bulk operations, scheduling
│   │   ├── models.py           # CRUD моделей, матрица, bulk-publish (самый большой: 58K)
│   │   ├── accounts.py         # CRUD аккаунтов, Excel import
│   │   ├── feeds.py            # Генерация/загрузка XML-фидов
│   │   ├── autoload.py         # Sync/upload через Avito Autoload API
│   │   ├── analytics.py        # Статистика, эффективность, fee-отчёты
│   │   ├── schedule.py         # Расписание публикаций
│   │   ├── listings.py         # CRUD листингов
│   │   ├── images.py           # Загрузка/удаление фото товаров
│   │   ├── photo_packs.py      # CRUD фотопаков
│   │   ├── categories.py       # Синхронизация категорий
│   │   ├── reports.py          # Просмотр отчётов Avito
│   │   ├── description_templates.py  # CRUD шаблонов описаний
│   │   ├── yandex_folders.py   # Я.Диск ��ля товаров
│   │   ├── photo_pack_yandex_folders.py  # Я.Диск для паков
│   │   └── yandex_preview.py   # Прокси для превью с Я.Диска
│   │
│   ├── services/               # Бизнес-логика (16 сервисов)
│   │   ├── avito_client.py     # OAuth2 клиент Avito API (retry, token refresh)
│   │   ├── feed_generator.py   # Генерация XML-фидов (lxml)
│   │   ├── feed_importer.py    # Импорт avito_id из XML-фида
│   │   ├── avito_import.py     # Импорт товаров с Avito Items API
│   │   ├── autoload_sync.py    # 3-pass sync с отчётами Avito
│   │   ├── excel_importer.py   # Импорт из Excel-экспорта Avito
│   │   ├── publish_scheduled.py  # Публикация по расписанию
│   │   ├── image_processor.py  # Resize, compress, HEIC→JPEG
│   │   ├── image_sync.py       # Синхрон��зация фото из CRM
│   │   ├── photo_uniquifier.py # Уникализация фото (crop/brightness/noise)
│   │   ├── stats_sync.py       # Синхронизация статистики с Avito
│   │   ├── category_sync.py    # Синх��онизация дерева категорий
│   │   ├── sold_detection.py   # Обнаружение проданных/удалённых
│   │   ├── telegram_notify.py  # Telegram-уведомления
│   │   └── yandex_disk.py      # Загрузка фото с Яндекс.Диска
│   │
│   ├── schemas/                # Pydantic-схемы (минимальные)
│   ├── utils/
│   │   ├── title_heuristic.py  # Генерация заголовков из параметров
│   │   └── uploads.py          # Хелперы загрузки файлов
│   │
│   ├── templates/              # Jinja2 HTML-шаблоны
│   │   ├── base.html           # Базовый layout (sidebar + content)
│   │   ├── dashboard.html
│   │   ├── analytics.html      # 46K — самый большой шаблон
│   │   ├── schedule.html
│   │   ├── schedule_account.html
│   │   ├── accounts/           # list, form, detail
│   │   ├── models/
│   │   │   ├── list.html       # Dashboard с карточками моделей
│   │   │   └── detail.html     # 69K — матрица, bulk actions, inline edit
│   │   ├── products/
│   │   │   ├── list.html       # Таблица товаров с фи��ьтрами
│   │   │   ├── detail.html     # Карточка товара
│   │   │   ├── form.html       # Форма редактирования (полная)
│   │   │   ├── form_inline.html  # Slim-форма для iframe в модалке
│   │   │   └── bulk_edit.html
│   │   ├── feeds/, reports/, listings/, categories/, settings/
│   │
│   └── static/                 # Favicon, иконки (minimal — нет JS/CSS фреймворков)
│
├── alembic/
│   ├── env.py                  # Async migration runner
│   └── versions/               # 27+ миграций
��
├── tests/                      # 61 тест-файл, 939 тестов
│   ├── conftest.py             # Hard guard от запуска на prod DB
│   ├── test_models_routes.py   # 89K — самый большой тест
│   ├── test_products_routes.py # 79K
│   └── ...
│
├── deploy/
│   ├── avito-autoload.service  # systemd unit
│   ├── nginx-autoload.conf     # nginx reverse proxy + SSL
│   └── deploy.sh               # Деплой-скрипт
│
├── scripts/                    # Утилиты (backup, import, migration)
├── .github/workflows/
│   ├── test.yml                # CI: PostgreSQL 14, pytest
│   └── deploy.yml              # CD: SSH deploy
│
├── feeds/                      # Сгенерированные XML-фиды (gitignored)
├── media/                      # Загруженные фото (gitignored)
├── logs/                       # Логи (gitignored)
└── uploads/                    # Excel-импорты (gitignored)
```

## 4. Ключевые сущности

| Сущность | Таблица | Описание |
|----------|---------|----------|
| **Account** | `accounts` | Аккаунт Avito с OAuth2 credentials, feed_token (UUID), schedule |
| **Product** | `products` | Товар — центральная сущность. Статусы: imported → draft → scheduled → active → removed. 30+ полей. Optimistic locking через `version` |
| **Model** | `models` | Шаблон товара для мультиаккаунтных схем. Один Model → много Product на разных Account |
| **ModelVariant** | `model_variants` | Вариант модели (размер/цвет/цена + привязка к pack) |
| **PhotoPack** | `photo_packs` | Набор фото, привязан к Model. Копируется в Product при создании |
| **ProductImage** | `product_images` | Фото товара. source_type: local / avito_cdn / yandex_disk |
| **Listing** | `listings` | Привязка Product → Account для публикации. status: draft / scheduled / published |
| **DescriptionTemplate** | `description_templates` | Шаблон описания (standalone). Приоритет: template_id > custom > account_template |
| **FeedExport** | `feed_exports` | Запись о сгенерированном XML-фиде с upload_response |
| **ItemStats** | `item_stats` | Дневная статистика: views, contacts, favorites (кумулятивные) |
| **AutoloadReport** | `autoload_reports` | Отчёт Avito о принятых/отклонённых объявлениях |

### Статусы товара (Product.status)

```
imported  → Импортирован с Avito (не показывается в /products)
draft     → Черновик, созданный через систему
scheduled → В очереди на ��убликацию (scheduled_at задан)
active    → Активен на Avito
published → Опубликован через автозагрузку
paused    → Приостано��лен
sold      → Продан (legacy, через sold_detection)
removed   → Мягко удалён. Попадает в фид как Status=Removed 48ч, потом cleanup
```

### Приоритет описания в фиде

1. `description_template_id` — ссылочная семантика (FK на description_templates)
2. `description` + `use_custom_description=True` — своё описание
3. `AccountDescriptionTemplate` — шаблон аккаунта (deprecated fallback)

## 5. Точки входа

### Запуск

```bash
# Production (systemd)
sudo systemctl start avito-autoload
sudo systemctl status avito-autoload

# Development
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload

# Миграции
alembic upgrade head
alembic revision --autogenerate -m "description"
```

### Тесты

```bash
# Обязательно указать тестовую БД и TESTING=1
DATABASE_URL="postgresql+asyncpg://avito_user:avito_pass@localhost:5433/avito_autoload_test" \
  TESTING=1 pytest

# Быстрый прогон
DATABASE_URL="..." TESTING=1 pytest -q --tb=short

# Один файл
DATABASE_URL="..." TESTING=1 pytest tests/test_feed_generator.py -v
```

conftest.py имеет **hard guard** — отказывается запускать тесты на production БД.
Проверяет URL и переменную `TESTING=1` на этапе import-time.

### Деплой

```bash
# Через скрипт
./deploy/deploy.sh

# Вручную
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
sudo systemctl restart avito-autoload
```

### Инфраструктура

- **VPS:** Ubuntu, Timeweb Amsterdam, за Cloudflare proxy
- **Домен:** autoload.souljaion.ru (HTTPS, Let's Encrypt)
- **Порты:** uvicorn :8001, nginx :80/443, PostgreSQL :5433
- **БД prod:** `postgresql+asyncpg://avito_user:avito_pass@localhost:5433/avito_autoload`
- **БД test:** `postgresql+asyncpg://avito_user:avito_pass@localhost:5433/avito_autoload_test`

## 6. Специфика работы с Avito

### OAuth2

- Client credentials flow: `client_id` + `client_secret` (зашифрован Fernet)
- Token refresh каждые 50 минут через scheduler
- Scope: `autoload` — ограничивает доступ к API (нет brand, params, images через Items API)
- `avito_client.py` хранит логику retry с exponential backoff

### Avito Autoload API

- **Profile:** `GET /autoload/v2/profile` (v2 — с feeds_data), `GET /autoload/v1/profile` (fallback)
- **Upload:** `POST /autoload/v1/upload` — триггерит загрузку фида. v2 upload удалён Avito (404)
- **Reports:** `GET /autoload/v1/reports` — список отч��тов о принятых/отклонённых
- **Items:** `GET /core/v1/items` — только базовые поля (title, price, status, url). Brand/images **недоступны** через autoload scope
- **Stats:** `GET /stats/v1/accounts/{user_id}/items` — views, contacts, favorites (batch по 200)
- **ID mapping:** `POST /autoload/v1/items/ad-ids-to-avito-ids` — может вернуть 404 (endpoint нестабилен)

### XML-фиды

- Формат: Avito Autoload XML v3 (`feed_generator.py`, lxml)
- URL: `GET /feeds/{feed_token}.xml` — публичный, без авторизации
- Генерация: раз в час для каждого аккаунта (за 5 мин до avito_sync_minute). Задержка до ~1ч от создания scheduled до видимости в фиде
- Содержимое: active + scheduled + imported (если ready) + removed (< 48ч)
- Removed товары: минимальный `<Ad>` с Id + AvitoId + `<Status>Removed</Status>`
- **Avito не имеет API для удаления** — только через фид Status=Removed

### Таксономия (каталог)

4-уровневая иерархия Avito, хранится в `avito_categories` + hardcoded fallback в `catalog.py`:
```
Category → GoodsType → Subcategory (ApparelType) → GoodsSubType
```
Пример: `Одежда, обувь, аксессуары → Мужская обув�� → Кроссовки и кеды → Кроссовки`

`requires_subtype(category, goods_type, subcategory)` — только 3 подкатегории
реально требуют goods_subtype. Используется в:
- `feed_generator.get_missing_fields()`
- `dashboard._product_problems()`
- `models.py` (badge готовности модели)

### Уникализация фото

`photo_uniquifier.py` — неразличимые для человека модификации:
1. Random crop 1-3px + resize обратно
2. Brightness +/- 2-3%
3. Faint noise overlay 2-5%

Результат: уникальный hash файла при визуальной идентичности.
Триггер: автоматически при повторной публикации на тот же аккаунт (есть PublishHistory).

### Импорт данных (3 способа)

1. **Items API** (`avito_import.py`): каждые 3ч, создаёт imported-товары
2. **Autoload Report** (`autoload_sync.py`): 3-pass reconciliation (report → Items API → fuzzy title match)
3. **Excel** (`excel_importer.py`): ручной upload .xlsx экспорта из кабинета Avito. Единственный способ получить brand, goods_type, photos

### Лимиты и ограничения

- Items API: только базовые поля через autoload scope
- Stats API: batch max 200 ID, rolling window 269 дней
- Rate limit на `/products/{id}/avito-status`: 30/min
- Rate limit на `/api/analytics/fees`: 10/min
- Upload: max 200MB (nginx client_max_body_size)
- Изображения: max 20MB input, resize до 1600px, max 10 фото на товар

## 7. Конвенции кода

### Архитектура

- **Async everywhere:** все DB-операции, HTTP-вызовы, обработка изображений — async
- **Роутеры** возвращают HTML (Jinja2 TemplateResponse) или JSON (JSONResponse)
- **Сервисы** — чистая бизнес-логика, не знают о HTTP
- **Модели** — SQLAlchemy 2.0 declarative, relationships через `relationship()` с `selectinload` в запросах
- **Фоновые задачи** — APScheduler с retry logic (2 попытки, 5мин между)

### Паттерны

- `get_db()` — async generator для Depends injection
- `safe_update_status()` — optimistic locking через version field
- `selectinload()` — eager loading для N+1 prevention (не всегда применён)
- Роутеры используют `request.json()` напрямую вместо Pydantic-схем в большинстве endpoints
- HTML-формы через `Form(...)` параметры
- `JSONResponse({...})` вместо return dict (явный контроль над status_code)
- Структурированное логирование: `structlog.get_logger("module_name")`

### Имено��ание

- Файлы: snake_case (`avito_client.py`, `feed_generator.py`)
- Таблицы: snake_case множественное число (`products`, `photo_packs`)
- Функции endpoints: `product_list`, `model_detail`, `bulk_publish`
- Приватные функции: `_default_ad_title`, `_extract_feed_url`
- Шаблоны: `{entity}/{action}.html` (`products/form.html`, `models/detail.html`)

### Тесты

- pytest + pytest-asyncio с `asyncio_mode = auto`
- Fixtures: `db` (transactional rollback), `isolated_db` (для commit-тестов), `auth_headers`, `client`
- Hard guard против prod DB в conftest.py
- Session-scoped seed fixture для account id=1
- Тесты: 939 passed, 1 skipped. Отдельная БД `avito_autoload_test`

### Логиров��ние

- structlog: JSON в production, ConsoleRenderer в dev
- RotatingFileHandler: 10MB, 5 backups, `logs/app.log`
- Контекстное: `log.info("event_name", account_id=..., product_id=...)`

## 8. Чего избегать

### Хрупкие места

- **`models.py` (58K) и `detail.html` (69K)** — самые большие файлы. Изменения требуют осторожности. Inline JS в шаблонах: 700+ строк JavaScript внутри `<script>` без модулей
- **`scheduler.py` (29K)** — все 14 фоновых задач в одном файле. Scheduler lock через fcntl — только первый worker запускает задачи
- **Zulla diagnostics** в lifespan (`main.py:58-70`) — diagnostic query при каждом старте. Можно удалить после стабилизации
- **`datetime.utcnow()`** — deprecated, используется в `schedule.py`, `scheduler.py`, `test_stats_sync.py`. Нужно заменить на `datetime.now(timezone.utc)` (Python 3.13 compat)
- **postMessage без origin check** — `detail.html:694` и `form_inline.html:273` не пров��ряют `event.origin`. Также `postMessage(..., '*')` вместо конкретного origin
- ~~**Dead endpoints**~~ — удалены в v7.12: `create_all_listings`, `schedule_matrix`, `create_one`
- **N+1 в `bulk_publish`** — sequential query на ADT и Listing для каждого продукта

### Антипаттерны, которые НЕ копировать

- `request.json()` без валидации — большинство POST endpoints парсят body вручную вместо Pydantic-схем
- Inline CSS/JS в шаблонах — стили и скрипты внутри HTML файлов, нет отдельных .css/.js
- `from ... import` внутри функций (lazy imports в `bulk_publish`, `create_model_product`) — используется для избежания circular imports, но затрудняет понимание зависимостей
- Dual-source описания — product может иметь и `description`, и `description_template_id` одновременно. Feed корректен (template wins), но DB содержит лишние данные

### Что нельзя ломать

- `.env` — секреты, ENCRYPTION_KEY. Потеря ключа = потеря доступа к аккаунтам
- `crypto.py` — Fernet encrypt/decrypt для client_secret
- `middleware/auth.py` — единственная точка аутентификации
- `alembic/versions/` — не менять существующие миграции, только создавать новые
- `feeds/{token}.xml` — публичный URL, Avito забирает его по расписанию
- `/health` — должен быть доступен без авторизации
- `scheduler.py` lock mechanism — fcntl lock предотвращает дублирование задач при 2 workers

## 9. Рабочий процесс

### Git

- Ветка: `main`
- Remote: `https://github.com/souljaion/Avito-Autoload.git` (push требует настройки PAT/SSH)
- Commit style: `feat(scope):`, `fix(scope):`, `docs(scope):`

### CI/CD

- **CI:** GitHub Actions → PostgreSQL 14 service, `alembic upgrade head`, `pytest`
- **CD:** GitHub Actions → SSH deploy (pull + pip install + migrate + restart)
- Тесты: 939 passed, Python 3.12

### Деплой

- systemd: `avito-autoload.service`, 2 uvicorn workers, MemoryMax=1G
- nginx: reverse proxy :8001 → :443, SSL via Certbot, client_max_body_size 200M
- Cloudflare proxy на DNS (обход проблем маршрутизации Timeweb Amsterdam → RU)

### Тестирование перед деплоем

```bash
# Полный прогон
DATABASE_URL="postgresql+asyncpg://avito_user:avito_pass@localhost:5433/avito_autoload_test" \
  TESTING=1 pytest -q --tb=short

# Рестарт сервиса
sudo systemctl restart avito-autoload
curl -s http://127.0.0.1:8001/health | python3 -m json.tool
```

## Уточняющие вопросы

1. **Масштаб данных:** сколько примерно товаров в prod БД сейчас и какой ожидаемый рост? Это влияет на подход к bulk-операциям и индексам.

2. **account_description_templates (deprecated):** планируется ли удаление? Несколько сервисов всё ещё проверяют эту таблицу как fallback.

3. **Inline JS в шаблонах:** есть ли планы на вынос JS в отдельные файлы? Сейчас `detail.html` содержит 700+ строк JS, что усложняет поддержку и делает невозможным cache-busting для логики.

4. **Avito API scope:** возможно ли расширение OAuth scope за пределы `autoload`? Это разблокировало бы прямой доступ к brand, params, images через Items API вместо обходног�� пути через Excel.
