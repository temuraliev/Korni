import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Contact, InputMediaPhoto, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from korni_bot.bot import keyboards as kb
from korni_bot.bot import texts
from korni_bot.bot.callbacks import BackCB, CategoryCB, EventActionCB, EventCB
from korni_bot.bot.handlers.admin_chat import deliver_to_admins
from korni_bot.bot.states import BookingFlow, CallbackFlow, DiscountFlow, QuestionFlow
from korni_bot.config import get_settings
from korni_bot.db.models import (
    Booking,
    BookingStatus,
    Callback,
    Category,
    Event,
    EventPhoto,
    EventPhotoKind,
    User,
)

router = Router(name="catalog")


# ─── Список мероприятий в категории ───────────────────────────────────────


@router.callback_query(CategoryCB.filter())
async def on_category(cb: CallbackQuery, callback_data: CategoryCB, session: AsyncSession) -> None:
    # Сначала гасим спиннер на кнопке — чтобы UI чувствовался быстрым.
    await cb.answer()
    assert cb.message is not None
    category = await session.get(Category, callback_data.id)
    if category is None:
        await cb.message.answer("Категория не найдена.")
        return
    events = list(
        await session.scalars(
            select(Event)
            .where(Event.category_id == category.id, Event.is_active.is_(True))
            .order_by(Event.event_date.nulls_last(), Event.id)
        )
    )
    if not events:
        await cb.message.answer(texts.NO_EVENTS_IN_CATEGORY, reply_markup=kb.events_kb([]))
        return
    title = f"<b>{category.title}</b>\n\nВыберите мероприятие:"
    try:
        await cb.message.edit_text(title, reply_markup=kb.events_kb(events))
    except Exception:
        await cb.message.answer(title, reply_markup=kb.events_kb(events))


@router.callback_query(BackCB.filter(F.to.startswith("category-")))
async def on_back_to_category(cb: CallbackQuery, callback_data: BackCB, session: AsyncSession) -> None:
    cat_id = int(callback_data.to.split("-", 1)[1])
    await on_category(cb, CategoryCB(id=cat_id), session)


# ─── Карточка мероприятия ─────────────────────────────────────────────────


@router.callback_query(EventCB.filter())
async def on_event(cb: CallbackQuery, callback_data: EventCB, session: AsyncSession) -> None:
    logger.info("on_event called: event_id=%s", callback_data.id)
    await cb.answer()
    assert cb.message is not None
    try:
        event = await session.get(Event, callback_data.id)
        if event is None or not event.is_active:
            await cb.message.answer("Мероприятие недоступно.")
            return
        photo_ids: list[str] = []
        if event.photo_file_id:
            photo_ids.append(event.photo_file_id)
        extra = await session.scalars(
            select(EventPhoto.file_id)
            .where(EventPhoto.event_id == event.id, EventPhoto.kind == EventPhotoKind.event)
            .order_by(EventPhoto.sort_order, EventPhoto.id)
        )
        photo_ids.extend(extra)
        photo_ids = photo_ids[:10]

        category = await session.get(Category, event.category_id)
        simple = "игр" in (category.title or "").lower() if category else False
        action_kb = kb.event_actions_kb(event.id, event.category_id, simple=simple)
        logger.info(
            "on_event event=%s photos=%d simple=%s", event.id, len(photo_ids), simple
        )

        # Telegram лимит на caption у фото и media_group — 1024 символа. Если описание
        # длинное — отправим фото без подписи, а полный текст с кнопками отдельным сообщением.
        TG_CAPTION_LIMIT = 1024
        full_caption = _format_event_caption(event)

        # file_id привязан к токену бота. Если сменили токен — все старые file_id
        # перестанут работать ('wrong file identifier'). Пробуем послать фото, если
        # получаем TelegramBadRequest — падаем на текстовый fallback (и сразу видим в логах).
        sent_with_photo = False
        try:
            if len(photo_ids) >= 2:
                short_caption = _format_event_caption(event, include_prompt=False)
                if len(short_caption) <= TG_CAPTION_LIMIT:
                    media = [
                        InputMediaPhoto(media=fid, caption=short_caption if i == 0 else None, parse_mode="HTML")
                        for i, fid in enumerate(photo_ids)
                    ]
                    await cb.message.answer_media_group(media)
                    await cb.message.answer(texts.EVENT_ACTIONS_PROMPT, reply_markup=action_kb)
                else:
                    media = [InputMediaPhoto(media=fid) for fid in photo_ids]
                    await cb.message.answer_media_group(media)
                    await cb.message.answer(full_caption, reply_markup=action_kb)
                sent_with_photo = True
            elif len(photo_ids) == 1:
                if len(full_caption) <= TG_CAPTION_LIMIT:
                    await cb.message.answer_photo(
                        photo=photo_ids[0], caption=full_caption, reply_markup=action_kb
                    )
                else:
                    await cb.message.answer_photo(photo=photo_ids[0])
                    await cb.message.answer(full_caption, reply_markup=action_kb)
                sent_with_photo = True
        except TelegramBadRequest as e:
            logger.warning(
                "Failed to send event photos (event_id=%s, reason=%s) — falling back to text",
                event.id, e,
            )

        if not sent_with_photo:
            await cb.message.answer(full_caption, reply_markup=action_kb)
    except Exception:
        logger.exception("on_event failed for event_id=%s", callback_data.id)
        try:
            await cb.message.answer("⚠️ Не удалось открыть карточку мероприятия.")
        except Exception:
            pass


def _format_event_caption(event: Event, include_prompt: bool = True) -> str:
    parts: list[str] = [f"<b>{event.title}</b>"]
    if event.event_date:
        parts.append(f"📅 {event.event_date.strftime('%d.%m.%Y %H:%M')}")
    if event.description:
        parts.append(event.description)
    if include_prompt:
        parts.append("")
        parts.append(texts.EVENT_ACTIONS_PROMPT)
    return "\n\n".join(parts)


# ─── Действия с мероприятием ──────────────────────────────────────────────


@router.callback_query(EventActionCB.filter(F.action == "teacher"))
async def on_teacher(cb: CallbackQuery, callback_data: EventActionCB, session: AsyncSession) -> None:
    await cb.answer()
    assert cb.message is not None
    event = await session.get(Event, callback_data.event_id)
    text = (event.teacher_info if event and event.teacher_info else texts.TEACHER_FALLBACK)

    teacher_photo_ids: list[str] = []
    if event is not None:
        rows = await session.scalars(
            select(EventPhoto.file_id)
            .where(EventPhoto.event_id == event.id, EventPhoto.kind == EventPhotoKind.teacher)
            .order_by(EventPhoto.sort_order, EventPhoto.id)
        )
        teacher_photo_ids = list(rows)[:10]

    back_kb = kb.back_to_category_kb(event.category_id if event else 0)

    if len(teacher_photo_ids) >= 2:
        media = [
            InputMediaPhoto(media=fid, caption=text if i == 0 else None, parse_mode="HTML")
            for i, fid in enumerate(teacher_photo_ids)
        ]
        await cb.message.answer_media_group(media)
        await cb.message.answer("◀️ Назад к мероприятиям", reply_markup=back_kb)
    elif len(teacher_photo_ids) == 1:
        await cb.message.answer_photo(photo=teacher_photo_ids[0], caption=text, reply_markup=back_kb)
    else:
        await cb.message.answer(text, reply_markup=back_kb)


@router.callback_query(EventActionCB.filter(F.action == "book"))
async def on_book(cb: CallbackQuery, callback_data: EventActionCB, session: AsyncSession, state: FSMContext) -> None:
    await cb.answer()
    assert cb.message is not None
    event = await session.get(Event, callback_data.event_id)
    if event is None or not event.is_active:
        await cb.message.answer("Мероприятие недоступно.")
        return
    await state.set_state(BookingFlow.waiting_contact)
    await state.update_data(event_id=event.id)
    await cb.message.answer(texts.ASK_CONTACT_BOOKING, reply_markup=kb.share_contact_kb())


@router.callback_query(EventActionCB.filter(F.action.in_({"question", "other_game"})))
async def on_question(cb: CallbackQuery, callback_data: EventActionCB, state: FSMContext) -> None:
    await cb.answer()
    assert cb.message is not None
    # event_id == 0 — пришли из меню категорий («У меня есть другой вопрос!»), там подменю не нужно,
    # сразу просим текст. С карточки мероприятия (event_id>0) показываем выбор: написать / позвонить.
    if callback_data.event_id == 0:
        await state.set_state(QuestionFlow.waiting_text)
        await state.update_data(event_id=None)
        await cb.message.answer(texts.ASK_QUESTION_PROMPT, reply_markup=kb.remove_kb())
    else:
        await cb.message.answer(
            texts.QUESTION_MENU_PROMPT,
            reply_markup=kb.question_submenu_kb(callback_data.event_id),
        )


@router.callback_query(EventActionCB.filter(F.action == "qwrite"))
async def on_qwrite(cb: CallbackQuery, callback_data: EventActionCB, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(QuestionFlow.waiting_text)
    await state.update_data(event_id=callback_data.event_id or None)
    assert cb.message is not None
    await cb.message.answer(texts.ASK_QUESTION_PROMPT, reply_markup=kb.remove_kb())


@router.callback_query(EventActionCB.filter(F.action == "qcall"))
async def on_qcall(cb: CallbackQuery, callback_data: EventActionCB, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(CallbackFlow.waiting_contact)
    await state.update_data(event_id=callback_data.event_id or None)
    assert cb.message is not None
    await cb.message.answer(texts.ASK_CONTACT_CALLBACK, reply_markup=kb.share_contact_kb())


@router.callback_query(EventActionCB.filter(F.action == "qself"))
async def on_qself(cb: CallbackQuery, callback_data: EventActionCB) -> None:
    await cb.answer()
    settings = get_settings()
    assert cb.message is not None
    await cb.message.answer(
        texts.SELF_CALL_TEXT.format(phone=settings.restaurant_phone),
        reply_markup=kb.question_submenu_kb(callback_data.event_id),
    )


# ─── Скидка через Instagram ──────────────────────────────────────────────


@router.callback_query(EventActionCB.filter(F.action == "discount"))
async def on_discount(cb: CallbackQuery, callback_data: EventActionCB) -> None:
    await cb.answer()
    settings = get_settings()
    assert cb.message is not None
    await cb.message.answer(
        texts.DISCOUNT_OFFER.format(percent=settings.discount_percent),
        reply_markup=kb.discount_kb(callback_data.event_id, settings.instagram_url),
    )


@router.callback_query(EventActionCB.filter(F.action == "discount_check"))
async def on_discount_check(
    cb: CallbackQuery, callback_data: EventActionCB, state: FSMContext
) -> None:
    assert cb.message is not None
    await cb.answer()
    # Встаём в состояние ожидания скриншота, запоминаем event_id.
    await state.set_state(DiscountFlow.waiting_screenshot)
    await state.update_data(event_id=callback_data.event_id or None)
    await cb.message.answer(texts.DISCOUNT_ASK_SCREENSHOT)


@router.message(DiscountFlow.waiting_screenshot, F.photo)
async def on_discount_screenshot(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    settings = get_settings()
    data = await state.get_data()
    event_id = data.get("event_id")
    await state.clear()

    event = await session.get(Event, event_id) if event_id else None
    user = await _get_or_create_user(session, message)

    # Шлём скриншот в админ-группу с шапкой.
    await _notify_admins_discount_screenshot(message, event, user, settings.discount_percent)

    await message.answer(
        texts.DISCOUNT_SUCCESS.format(percent=settings.discount_percent),
        reply_markup=kb.discount_success_kb(event_id or 0),
    )


@router.message(DiscountFlow.waiting_screenshot)
async def on_discount_wrong_type(message: Message) -> None:
    # Всё, что не фото, пока ждём скриншот — показываем напоминание, state не сбрасываем.
    await message.answer(texts.DISCOUNT_SCREENSHOT_WRONG_TYPE)


@router.callback_query(EventActionCB.filter(F.action == "back_to_event"))
async def on_back_to_event(
    cb: CallbackQuery, callback_data: EventActionCB, session: AsyncSession
) -> None:
    await on_event(cb, EventCB(id=callback_data.event_id), session)


# ─── Приём контакта ───────────────────────────────────────────────────────


@router.message(BookingFlow.waiting_contact, F.contact)
async def on_booking_contact(message: Message, session: AsyncSession, state: FSMContext) -> None:
    contact: Contact = message.contact  # type: ignore[assignment]
    data = await state.get_data()
    event_id = data.get("event_id")
    await state.clear()

    event = await session.get(Event, event_id) if event_id else None
    user = await _get_or_create_user(session, message, phone=contact.phone_number)
    if event is None:
        await message.answer("Мероприятие не найдено.", reply_markup=kb.remove_kb())
        return

    booking = Booking(user_id=user.id, event_id=event.id, phone=contact.phone_number or "")
    session.add(booking)
    await session.commit()

    # Первым сообщением закрываем reply-клавиатуру «поделиться контактом»,
    # вторым — inline-кнопка «Назад к мероприятиям», чтобы юзер не застрял.
    await message.answer(
        texts.BOOKING_SUCCESS.format(event_title=event.title),
        reply_markup=kb.remove_kb(),
    )
    await message.answer(
        "Можете вернуться к списку мероприятий 👇",
        reply_markup=kb.back_to_category_kb(event.category_id),
    )
    await _notify_admins_booking(message, event, user, contact.phone_number or "")


@router.message(CallbackFlow.waiting_contact, F.contact)
async def on_callback_contact(message: Message, session: AsyncSession, state: FSMContext) -> None:
    contact: Contact = message.contact  # type: ignore[assignment]
    data = await state.get_data()
    event_id = data.get("event_id")
    await state.clear()

    user = await _get_or_create_user(session, message, phone=contact.phone_number)
    cb_req = Callback(user_id=user.id, event_id=event_id, phone=contact.phone_number or "")
    session.add(cb_req)
    await session.commit()

    await message.answer(texts.CALLBACK_SUCCESS, reply_markup=kb.remove_kb())
    event = await session.get(Event, event_id) if event_id else None
    await _notify_admins_callback(message, event, user, contact.phone_number or "")


@router.message(QuestionFlow.waiting_text, F.text)
async def on_question_text(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await _get_or_create_user(session, message)
    await deliver_to_admins(message, session)
    await message.answer(texts.QUESTION_RECEIVED)


# ─── Вспомогательное ──────────────────────────────────────────────────────


async def _get_or_create_user(session: AsyncSession, message: Message, phone: str | None = None) -> User:
    tg_user = message.from_user
    assert tg_user is not None
    user = await session.scalar(select(User).where(User.tg_id == tg_user.id))
    if user is None:
        user = User(
            tg_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            phone=phone,
        )
        session.add(user)
        await session.commit()
    elif phone and user.phone != phone:
        user.phone = phone
        await session.commit()
    return user


async def _notify_admins_booking(message: Message, event: Event, user: User, phone: str) -> None:
    from korni_bot.config import get_settings

    bot = message.bot
    assert bot is not None
    settings = get_settings()
    text = (
        f"🎟 <b>Новая бронь</b>\n"
        f"Мероприятие: {event.title}\n"
        f"Пользователь: {_user_display(user)}\n"
        f"Телефон: <code>{phone}</code>"
    )
    await bot.send_message(settings.admin_group_id, text)


async def _notify_admins_discount_screenshot(
    message: Message, event: Event | None, user: User, percent: int
) -> None:
    bot = message.bot
    assert bot is not None and message.photo
    settings = get_settings()
    caption = (
        f"🎁 <b>Заявка на скидку {percent}%</b> — со скриншотом подписки\n"
        f"Мероприятие: {event.title if event else '—'}\n"
        f"Пользователь: {_user_display(user)}"
    )
    photo_id = message.photo[-1].file_id
    try:
        await bot.send_photo(settings.admin_group_id, photo_id, caption=caption)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Failed to send discount screenshot to admin group %s", settings.admin_group_id
        )


async def _notify_admins_callback(message: Message, event: Event | None, user: User, phone: str) -> None:
    from korni_bot.config import get_settings

    bot = message.bot
    assert bot is not None
    settings = get_settings()
    text = (
        f"📞 <b>Запрос обратного звонка</b>\n"
        f"Мероприятие: {event.title if event else '—'}\n"
        f"Пользователь: {_user_display(user)}\n"
        f"Телефон: <code>{phone}</code>"
    )
    await bot.send_message(settings.admin_group_id, text)


def _user_display(user: User) -> str:
    name = " ".join(filter(None, [user.first_name, user.last_name])) or "Без имени"
    if user.username:
        return f"{name} (@{user.username}) | id {user.tg_id}"
    return f"{name} | id {user.tg_id}"
