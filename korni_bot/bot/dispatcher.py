from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from korni_bot.bot.handlers import admin_chat, broadcast, catalog, start
from korni_bot.bot.middlewares import DbSessionMiddleware
from korni_bot.config import get_settings
from korni_bot.db.session import session_factory


def build_bot() -> Bot:
    settings = get_settings()
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    db_mw = DbSessionMiddleware(session_factory)
    dp.message.middleware(db_mw)
    dp.callback_query.middleware(db_mw)

    # admin_chat handlers должны идти ПЕРЕД catalog, чтобы reply в группе не падал в общий message-хендлер
    dp.include_router(admin_chat.router)
    dp.include_router(broadcast.router)
    dp.include_router(start.router)
    dp.include_router(catalog.router)

    return dp
