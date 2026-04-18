# Корни · бот «Близкий круг»

Telegram-бот для ресторана **«Корни»**: гости выбирают категорию мероприятий, бронируют место
через share-contact, задают вопросы → сообщения попадают в группу админов, админ отвечает reply'ем.
Есть веб-админка для управления категориями / мероприятиями / рассылками.

## Функции

- `/start` → приветствие + фото + кнопка **Начать**
- Меню категорий: Детские / Взрослые / Мафия / Настольные / «Другой вопрос»
- Карточка мероприятия: фото, описание, счётчик свободных мест, 4 действия
  (забронировать / подробнее о преподавателе / вопрос в чат / обратный звонок)
- Бронирование через `share_contact` (Telegram sends phone natively)
- Чат юзер ↔ админ-группа: любое сообщение форвардится, админ отвечает reply'ем — бот доставит юзеру
- Рассылка: через `/broadcast` в ЛС боту или из веб-админки (с фото)
- Веб-админка на `/admin/` — CRUD мероприятий/категорий, список броней/звонков/юзеров, история рассылок

## Стек

- Python 3.12 · **aiogram 3** (webhook) · **FastAPI** + Jinja2
- PostgreSQL · SQLAlchemy 2 async · Alembic
- Один сервис на Railway: FastAPI принимает и webhook от Telegram, и веб-админку

## Локальный запуск

```bash
# 1. Установка зависимостей
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate       # Mac/Linux
pip install -e .

# 2. Настроить .env (скопировать из .env.example)
cp .env.example .env
# отредактировать BOT_TOKEN, ADMIN_GROUP_ID, ADMIN_IDS, WEBHOOK_BASE_URL, ADMIN_LOGIN/PASSWORD, DATABASE_URL

# 3. Миграции
alembic upgrade head

# 4. Запуск
python -m korni_bot
```

Для локальной разработки webhook-у нужен публичный HTTPS — используй **ngrok** или **cloudflared**:

```bash
ngrok http 8080
# скопировать https://xxxx.ngrok-free.app в WEBHOOK_BASE_URL
```

## Деплой на Railway

1. **Создать проект** на [railway.app](https://railway.app) → *Deploy from GitHub repo* (или `railway up` из CLI)
2. **Добавить PostgreSQL**: *+ New → Database → PostgreSQL*.
   Railway автоматически подставит переменную `DATABASE_URL` в сервис
   (постфикс `+asyncpg` добавляется на лету в `config.py`).
3. **Добавить переменные окружения** (вкладка Variables):

   | Переменная | Значение |
   |---|---|
   | `BOT_TOKEN` | токен от @BotFather |
   | `ADMIN_GROUP_ID` | ID супергруппы админов (начинается с `-100…`) |
   | `ADMIN_IDS` | `111111111,222222222` — TG ID админов через запятую |
   | `WEBHOOK_BASE_URL` | публичный URL сервиса, например `https://korni-bot-production.up.railway.app` |
   | `WEBHOOK_SECRET` | любая случайная строка (hex, 32+ символов) |
   | `ADMIN_LOGIN` | логин для веб-админки |
   | `ADMIN_PASSWORD` | пароль для веб-админки |
   | `SESSION_SECRET` | любая случайная строка (hex, 32+ символов) |

   `DATABASE_URL` и `PORT` Railway подставит сам.

4. **Настройки деплоя** (`railway.toml` уже в репо):
   - Builder: Nixpacks (определит Python автоматически)
   - Start command: `alembic upgrade head && python -m korni_bot`

5. **Получить публичный URL** — в Railway: Settings → Networking → *Generate Domain* —
   скопировать в `WEBHOOK_BASE_URL` и пере-деплоить.

6. **Подготовка Telegram:**
   - Бот создаётся у [@BotFather](https://t.me/BotFather): `/newbot`, копируем токен
   - В настройках бота BotFather → `/setprivacy` → **Disable** (чтобы бот видел все сообщения в группе)
   - Создать **супергруппу** для админов, добавить туда бота, дать ему права админа
   - Узнать ID группы: временно добавить `@RawDataBot` в группу (после получения ID убрать), или
     использовать `curl "https://api.telegram.org/bot<TOKEN>/getUpdates"` после любого сообщения в группе

## Как заполнить бот контентом (первый раз)

1. Открыть `https://<your-domain>/admin/` → войти.
2. **Категории** → добавить: Детские (🎨), Взрослые (🍷), Мафия (🕵️), Настольные игры (🎲).
3. **Мероприятия** → «Добавить» → заполнить название, описание, инфу о преподавателе,
   даты, число мест, фото → Сохранить.
4. Юзеры в боте сразу увидят изменения — контент подгружается из БД на каждый запрос.

## Как работает мост «юзер ↔ админ-группа»

- Юзер пишет произвольный текст или нажимает «Другой вопрос» → сообщение форвардится в группу,
  следом бот присылает «шапку» с `tg_id` юзера. В БД сохраняется маппинг `admin_group_message_id → user_tg_id`.
- Админ в группе делает **reply** на форвард (или на шапку) → хендлер находит маппинг,
  отправляет текст/фото/голосовое юзеру с префиксом «💬 Ответ администратора:».
- Для этого боту нужны права админа в группе + *Group Privacy = Disabled* в BotFather.

## Структура проекта

```
korni/
├── pyproject.toml
├── railway.toml / Procfile
├── alembic.ini
├── migrations/
│   └── versions/0001_initial.py
└── src/korni_bot/
    ├── __main__.py
    ├── main.py               # FastAPI + webhook entry point
    ├── config.py             # pydantic-settings
    ├── db/                   # модели, сессия
    ├── bot/
    │   ├── dispatcher.py     # сборка Dispatcher + middleware
    │   ├── keyboards.py, texts.py, states.py, callbacks.py
    │   └── handlers/
    │       ├── start.py      # /start + переход к категориям
    │       ├── catalog.py    # категории/события/бронирование/контакт
    │       ├── admin_chat.py # мост юзер ↔ админ-группа
    │       └── broadcast.py  # /broadcast
    └── admin_web/
        ├── app.py, auth.py, deps.py, routes.py
        └── templates/*.html
```

## Частые проблемы

**Бот не отвечает в группе на reply.** Проверь `/setprivacy` → Disable в BotFather
и выдай боту права администратора в группе.

**Webhook не ставится.** Убедись, что `WEBHOOK_BASE_URL` — это публичный **HTTPS** (Telegram требует TLS).

**Миграции падают на Railway.** В логах ищи `alembic upgrade head` — часто проблема в том, что
`DATABASE_URL` содержит `postgres://` вместо `postgresql+asyncpg://`. В `config.py` есть нормализация,
но если алемибк не видит переменную — проверь что она доступна в build-стадии.

**Юзер не получает ответ админа.** Убедись, что админ делает *reply* именно на форвард или «шапку»,
а не на случайное сообщение в группе. Возраст сообщения не важен — маппинг хранится в БД.
