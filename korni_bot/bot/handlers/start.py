import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from korni_bot.bot import keyboards as kb
from korni_bot.bot import texts
from korni_bot.bot.callbacks import BackCB, StartBrowseCB
from korni_bot.db.models import AppSetting, Category, User

logger = logging.getLogger(__name__)

router = Router(name="start")


async def _upsert_user(session: AsyncSession, message: Message) -> User:
    tg_user = message.from_user
    assert tg_user is not None
    existing = await session.scalar(select(User).where(User.tg_id == tg_user.id))
    if existing is None:
        existing = User(
            tg_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        session.add(existing)
        await session.commit()
    else:
        changed = False
        if existing.username != tg_user.username:
            existing.username = tg_user.username
            changed = True
        if existing.first_name != tg_user.first_name:
            existing.first_name = tg_user.first_name
            changed = True
        if existing.is_blocked:
            existing.is_blocked = False
            changed = True
        if changed:
            await session.commit()
    return existing


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await _upsert_user(session, message)
    start_photo = await session.get(AppSetting, "start_photo_file_id")
    if start_photo and start_photo.value:
        try:
            await message.answer_photo(
                photo=start_photo.value, caption=texts.START, reply_markup=kb.start_kb()
            )
            return
        except TelegramBadRequest as e:
            # file_id мог «протухнуть» (сменили токен бота, фото удалено и т.п.).
            # Чистим запись, чтобы не падать на каждом /start, и шлём только текст.
            logger.warning("Invalid start_photo_file_id, clearing it: %s", e)
            await session.execute(
                delete(AppSetting).where(AppSetting.key == "start_photo_file_id")
            )
            await session.commit()
    await message.answer(texts.START, reply_markup=kb.start_kb())


@router.callback_query(StartBrowseCB.filter())
async def on_start_browse(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await _show_categories(cb, session)


@router.callback_query(BackCB.filter(F.to == "categories"))
async def on_back_to_categories(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await _show_categories(cb, session)


async def _show_categories(cb: CallbackQuery, session: AsyncSession) -> None:
    await cb.answer()
    categories = list(
        await session.scalars(
            select(Category).where(Category.is_active.is_(True)).order_by(Category.sort_order, Category.id)
        )
    )
    assert cb.message is not None
    # если сообщение выше было фото — редактировать caption нельзя на текст, шлём новое
    try:
        await cb.message.edit_text(texts.CATEGORY_PROMPT, reply_markup=kb.categories_kb(categories))
    except Exception:
        await cb.message.answer(texts.CATEGORY_PROMPT, reply_markup=kb.categories_kb(categories))
