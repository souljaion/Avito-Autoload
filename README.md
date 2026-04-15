# Avito Autoload MVP

Система автозагрузки объявлений на Avito. Позволяет вести базу товаров, генерировать XML-фиды и управлять автозагрузкой через Avito API.

## Возможности

- Управление аккаунтами Avito (до 5)
- Единая база товаров с привязкой к аккаунтам
- Загрузка изображений товаров
- Генерация XML-фидов для Avito Autoload
- Публичный URL фида для каждого аккаунта
- Интеграция с Avito Autoload API (профиль, upload, отчеты)
- Просмотр отчетов и ошибок загрузки

## Требования

- Python 3.11+
- PostgreSQL 14+

## Установка

```bash
git clone <repo-url>
cd avito-autoload

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Настройка

```bash
cp .env.example .env
```

Отредактируйте `.env`:

| Переменная     | Описание                          | Пример                                              |
|----------------|-----------------------------------|------------------------------------------------------|
| `DATABASE_URL` | Строка подключения к PostgreSQL   | `postgresql+asyncpg://user:pass@localhost:5432/avito` |
| `BASE_URL`     | Публичный URL приложения          | `https://your-domain.com`                            |
| `MEDIA_DIR`    | Директория для изображений        | `./media`                                            |
| `FEEDS_DIR`    | Директория для XML-фидов          | `./feeds`                                            |
| `SECRET_KEY`   | Секретный ключ                    | `random-string`                                      |

## База данных

Создайте базу данных:

```bash
createdb avito_autoload
```

Примените миграции:

```bash
alembic upgrade head
```

Создать новую миграцию (после изменения моделей):

```bash
alembic revision --autogenerate -m "описание"
```

## Запуск

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Приложение: http://localhost:8000

## Страницы

| URL          | Описание              |
|--------------|-----------------------|
| `/accounts`  | Управление аккаунтами |
| `/products`  | Управление товарами   |
| `/feeds`     | Генерация XML-фидов   |
| `/reports`   | Отчеты автозагрузки   |
| `/health`    | Health check          |

## XML-фид

Фид доступен по URL:

```
GET /feeds/{account_id}.xml
```

Для настройки в Avito укажите этот URL в профиле автозагрузки.

## Деплой

1. Настройте PostgreSQL
2. Задайте переменные окружения (`.env` или переменные среды)
3. Укажите `BASE_URL` — публичный адрес сервера
4. Примените миграции: `alembic upgrade head`
5. Запустите: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
6. Настройте reverse proxy (nginx) для проксирования на порт 8000
7. Убедитесь, что URL фида доступен извне

## Тесты

```bash
pytest tests/ -v
```

Тесты включают:
- `test_feed_generator.py` — unit-тесты генерации XML и валидации
- `test_avito_client.py` — mock-тесты OAuth2, retry, upload
- `test_health.py` — healthcheck endpoint
- `test_products_api.py` — CRUD товаров через API

## CI/CD (GitHub Actions)

Автодеплой настроен в `.github/workflows/deploy.yml`:
1. **test** — запуск тестов на каждый push в `main`
2. **deploy** — SSH на сервер, pull, миграции, рестарт

### Настройка GitHub Secrets

В репозитории Settings > Secrets and variables > Actions добавьте:

| Secret | Описание | Пример |
|--------|----------|--------|
| `SERVER_HOST` | IP или домен сервера | `autoload.souljaion.ru` |
| `SERVER_USER` | SSH пользователь | `claude2` |
| `SSH_KEY` | Приватный SSH ключ | Содержимое `~/.ssh/id_ed25519` |

### Ручной деплой

```bash
bash deploy/deploy.sh
```

## Структура проекта

```
app/
  main.py            — точка входа FastAPI
  config.py          — конфигурация (pydantic-settings)
  db.py              — подключение к БД
  models/            — SQLAlchemy модели
  routes/            — маршруты (accounts, products, feeds, reports, autoload)
  services/          — бизнес-логика (feed_generator, avito_client)
  templates/         — Jinja2 HTML-шаблоны
  static/            — статические файлы
  middleware/        — HTTP Basic Auth
  logging_config.py  — structlog + RotatingFileHandler
alembic/             — миграции
tests/               — pytest тесты
deploy/              — nginx, systemd, deploy.sh
.github/workflows/   — CI/CD
```
