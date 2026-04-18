"""Мост сообщения: юзер ↔ админ-группа.

- Любое неструктурированное текстовое сообщение юзера форвардится в группу + пишется «шапка»
  с инфой о юзере → id этой «шапки» сохраняется в message_map.
- Если админ в группе делает reply на форвард (или на «шапку»), ответ уходит юзеру.
"""
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from korni_bot.bot import texts
from korni_bot.config import get_settings
from korni_bot.db.models import DialogDirection, DialogMessage, MessageMap, User

router = Router(name="admin_chat")
logger = logging.getLogger(__name__)


# ─── От юзера в группу ────────────────────────────────────────────────────


async def deliver_to_admins(message: Message, session: AsyncSession) -> bool:
    """Форвардит сообщение юзера в админ-группу и сохраняет маппинг.
    Возвращает True при успехе, False если не удалось достучаться до группы."""
    settings = get_settings()
    bot = message.bot
    assert bot is not None and message.from_user is not None

    header_text = _header_for(message)
    try:
        forwarded = await bot.forward_message(
            chat_id=settings.admin_group_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await bot.send_message(
            settings.admin_group_id,
            header_text,
            reply_to_message_id=forwarded.message_id,
        )
    except TelegramAPIError as e:
        logger.error(
            "Failed to forward to admin group %s: %s. "
            "Check ADMIN_GROUP_ID (должен начинаться с -100) и что бот добавлен в группу.",
            settings.admin_group_id,
            e,
        )
        return False

    mapping = MessageMap(
        user_tg_id=message.from_user.id,
        admin_group_message_id=forwarded.message_id,
        user_message_id=message.message_id,
    )
    session.add(mapping)
    await session.commit()
    return True


def _header_for(message: Message) -> str:
    u = message.from_user
    assert u is not None
    name = " ".join(filter(None, [u.first_name, u.last_name])) or "Без имени"
    handle = f"@{u.username}" if u.username else "—"
    return (
        f"✉️ <b>Сообщение от пользователя</b>\n"
        f"{name} | {handle} | id <code>{u.id}</code>\n\n"
        f"<i>Чтобы ответить — сделайте reply на это сообщение.</i>"
    )


# ─── От админа в группе → юзеру ───────────────────────────────────────────


@router.message(F.chat.func(lambda c: c.id == get_settings().admin_group_id), F.reply_to_message)
async def on_admin_reply(message: Message, session: AsyncSession) -> None:
    bot = message.bot
    assert bot is not None and message.reply_to_message is not None

    # reply может быть и на форвард, и на «шапку» — ищем оба варианта
    target_msg_id = message.reply_to_message.message_id
    mapping = await session.scalar(select(MessageMap).where(MessageMap.admin_group_message_id == target_msg_id))
    if mapping is None:
        # возможно, reply был на «шапку» — найдём по соседнему id
        mapping = await session.scalar(
            select(MessageMap).where(MessageMap.admin_group_message_id == target_msg_id - 1)
        )
    if mapping is None:
        return  # не наш reply

    user = await session.scalar(select(User).where(User.tg_id == mapping.user_tg_id))
    if user is None or user.is_blocked:
        await message.reply("⚠️ Пользователь недоступен.")
        return

    log_content_type = "text"
    log_text: str | None = None
    log_file_id: str | None = None
    try:
        if message.text:
            await bot.send_message(mapping.user_tg_id, texts.ADMIN_REPLY_PREFIX + message.text)
            log_text = message.text
        elif message.photo:
            caption = (texts.ADMIN_REPLY_PREFIX + (message.caption or "")).rstrip()
            await bot.send_photo(mapping.user_tg_id, message.photo[-1].file_id, caption=caption or None)
            log_content_type = "photo"
            log_text = message.caption
            log_file_id = message.photo[-1].file_id
        elif message.document:
            caption = (texts.ADMIN_REPLY_PREFIX + (message.caption or "")).rstrip()
            await bot.send_document(mapping.user_tg_id, message.document.file_id, caption=caption or None)
            log_content_type = "document"
            log_text = message.caption
            log_file_id = message.document.file_id
        elif message.voice:
            await bot.send_voice(mapping.user_tg_id, message.voice.file_id)
            log_content_type = "voice"
            log_file_id = message.voice.file_id
        elif message.video:
            caption = (texts.ADMIN_REPLY_PREFIX + (message.caption or "")).rstrip()
            await bot.send_video(mapping.user_tg_id, message.video.file_id, caption=caption or None)
            log_content_type = "video"
            log_text = message.caption
            log_file_id = message.video.file_id
        else:
            await message.reply("⚠️ Этот тип сообщения пока не поддерживается для ответа.")
            return
        session.add(
            DialogMessage(
                user_tg_id=mapping.user_tg_id,
                direction=DialogDirection.out,
                content_type=log_content_type,
                text=log_text,
                file_id=log_file_id,
            )
        )
        await session.commit()
        await message.reply("✅ Отправлено")
    except Exception as e:
        await message.reply(f"❌ Не удалось доставить: {e}")


# ─── Свободный текст юзера в ЛС → в админ-группу ──────────────────────────


@router.message(F.chat.type == "private", ~F.text.startswith("/"))
async def on_private_text(message: Message, session: AsyncSession) -> None:
    # Контакты, фото и т.п. обрабатываются в специализированных FSM-хендлерах;
    # сюда попадёт остаток (текст без команды и без FSM-состояния).
    if message.text or message.photo or message.voice or message.video or message.document:
        await deliver_to_admins(message, session)
        await message.answer(texts.QUESTION_RECEIVED)


# ─── /admin — быстрая проверка прав ───────────────────────────────────────


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    settings = get_settings()
    assert message.from_user is not None
    if message.from_user.id not in settings.admin_ids:
        return
    await message.answer(
        "Админ-команды:\n"
        "/broadcast &lt;текст&gt; — рассылка всем пользователям\n"
        f"Админ-панель: {settings.webhook_base_url.rstrip('/')}/admin/"
    )
