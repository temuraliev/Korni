from collections.abc import AsyncIterator

from aiogram import Bot
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from korni_bot.db.session import session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


def get_bot(request: Request) -> Bot:
    bot: Bot | None = getattr(request.app.state, "bot", None)
    if bot is None:
        raise RuntimeError("Bot is not initialized in app.state")
    return bot


DbDep = Depends(get_db)
BotDep = Depends(get_bot)
