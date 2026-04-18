import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from korni_bot.db.models import DialogDirection, DialogMessage

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Открывает AsyncSession на каждый update и кладёт в data['session']."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            return await handler(event, data)


class DialogLoggerMiddleware(BaseMiddleware):
    """Логирует все входящие сообщения юзера в приватном чате для админской
    вкладки «Диалоги». Отдельная сессия — чтобы падение бизнес-логики не
    откатывало логи, и наоборот."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.chat.type == "private" and event.from_user:
            try:
                async with self.session_factory() as session:
                    content_type, text, file_id = _extract(event)
                    session.add(
                        DialogMessage(
                            user_tg_id=event.from_user.id,
                            direction=DialogDirection.in_,
                            content_type=content_type,
                            text=text,
                            file_id=file_id,
                        )
                    )
                    await session.commit()
            except Exception:
                logger.exception("Failed to log incoming dialog message")
        return await handler(event, data)


def _extract(m: Message) -> tuple[str, str | None, str | None]:
    if m.text:
        return "text", m.text, None
    if m.photo:
        return "photo", m.caption, m.photo[-1].file_id
    if m.voice:
        return "voice", None, m.voice.file_id
    if m.video:
        return "video", m.caption, m.video.file_id
    if m.document:
        return "document", m.caption, m.document.file_id
    if m.contact:
        c = m.contact
        name = " ".join(filter(None, [c.first_name, c.last_name])) or ""
        return "contact", f"{name} {c.phone_number}".strip(), None
    return "other", None, None
