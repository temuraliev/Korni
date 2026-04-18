"""Команда /broadcast для админов — быстрая рассылка из ЛС-бота без захода в веб-панель."""
import asyncio
import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from korni_bot.config import get_settings
from korni_bot.db.models import Broadcast, User

router = Router(name="broadcast")
logger = logging.getLogger(__name__)


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject, session: AsyncSession) -> None:
    settings = get_settings()
    assert message.from_user is not None
    if message.from_user.id not in settings.admin_ids:
        return
    if not command.args:
        await message.answer("Использование: <code>/broadcast текст рассылки</code>")
        return

    broadcast = Broadcast(text=command.args)
    session.add(broadcast)
    await session.commit()
    await message.answer("📣 Рассылка запущена…")

    sent, failed = await run_broadcast(
        message.bot,  # type: ignore[arg-type]
        text=command.args,
        photo_file_id=None,
        session_maker=None,
    )
    broadcast.sent_count = sent
    broadcast.failed_count = failed
    await session.commit()
    await message.answer(f"Готово. Доставлено: {sent}. Ошибок: {failed}.")


async def run_broadcast(
    bot: Bot,
    text: str,
    photo_file_id: str | None,
    session_maker: async_sessionmaker | None,
) -> tuple[int, int]:
    """Шлёт сообщение всем незаблокированным юзерам. Ограничение Telegram ≈ 30 msg/sec — спим 40ms."""
    from korni_bot.db.session import session_factory as default_factory

    factory = session_maker or default_factory
    sent = 0
    failed = 0
    async with factory() as session:
        user_ids = list(await session.scalars(select(User.tg_id).where(User.is_blocked.is_(False))))

    for tg_id in user_ids:
        try:
            if photo_file_id:
                await bot.send_photo(tg_id, photo_file_id, caption=text or None)
            else:
                await bot.send_message(tg_id, text)
            sent += 1
            await asyncio.sleep(0.04)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                if photo_file_id:
                    await bot.send_photo(tg_id, photo_file_id, caption=text or None)
                else:
                    await bot.send_message(tg_id, text)
                sent += 1
            except Exception as exc:
                logger.warning("broadcast retry fail for %s: %s", tg_id, exc)
                failed += 1
        except TelegramForbiddenError:
            failed += 1
            async with factory() as session:
                await session.execute(update(User).where(User.tg_id == tg_id).values(is_blocked=True))
                await session.commit()
        except Exception as e:
            logger.warning("broadcast fail for %s: %s", tg_id, e)
            failed += 1

    return sent, failed
