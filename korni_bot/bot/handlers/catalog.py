from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Contact, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from korni_bot.bot import keyboards as kb
from korni_bot.bot import texts
from korni_bot.bot.callbacks import BackCB, CategoryCB, EventActionCB, EventCB
from korni_bot.bot.handlers.admin_chat import deliver_to_admins
from korni_bot.bot.states import BookingFlow, CallbackFlow, QuestionFlow
from korni_bot.db.models import Booking, BookingStatus, Callback, Category, Event, User

router = Router(name="catalog")


# ─── Список мероприятий в категории ───────────────────────────────────────


@router.callback_query(CategoryCB.filter())
async def on_category(cb: CallbackQuery, callback_data: CategoryCB, session: AsyncSession) -> None:
    category = await session.get(Category, callback_data.id)
    if category is None:
        await cb.answer("Категория не найдена", show_alert=True)
        return
    events = list(
        await session.scalars(
            select(Event)
            .where(Event.category_id == category.id, Event.is_active.is_(True))
            .order_by(Event.event_date.nulls_last(), Event.id)
        )
    )
    if not events:
        assert cb.message is not None
        await cb.message.answer(texts.NO_EVENTS_IN_CATEGORY, reply_markup=kb.events_kb([]))
        await cb.answer()
        return
    title = f"<b>{category.title}</b>\n\nВыберите мероприятие:"
    assert cb.message is not None
    try:
        await cb.message.edit_text(title, reply_markup=kb.events_kb(events))
    except Exception:
        await cb.message.answer(title, reply_markup=kb.events_kb(events))
    await cb.answer()


@router.callback_query(BackCB.filter(F.to.startswith("category:")))
async def on_back_to_category(cb: CallbackQuery, callback_data: BackCB, session: AsyncSession) -> None:
    cat_id = int(callback_data.to.split(":", 1)[1])
    await on_category(cb, CategoryCB(id=cat_id), session)


# ─── Карточка мероприятия ─────────────────────────────────────────────────


@router.callback_query(EventCB.filter())
async def on_event(cb: CallbackQuery, callback_data: EventCB, session: AsyncSession) -> None:
    event = await session.get(Event, callback_data.id)
    if event is None or not event.is_active:
        await cb.answer("Мероприятие недоступно", show_alert=True)
        return
    booked = await session.scalar(
        select(func.count(Booking.id)).where(
            Booking.event_id == event.id, Booking.status != BookingStatus.cancelled
        )
    )
    seats_left = max(0, event.total_seats - (booked or 0))
    caption = _format_event_caption(event, seats_left)
    assert cb.message is not None
    if event.photo_file_id:
        await cb.message.answer_photo(
            photo=event.photo_file_id, caption=caption, reply_markup=kb.event_actions_kb(event.id)
        )
    else:
        await cb.message.answer(caption, reply_markup=kb.event_actions_kb(event.id))
    await cb.answer()


def _format_event_caption(event: Event, seats_left: int) -> str:
    parts: list[str] = [f"<b>{event.title}</b>"]
    if event.event_date:
        parts.append(f"📅 {event.event_date.strftime('%d.%m.%Y %H:%M')}")
    if event.description:
        parts.append(event.description)
    parts.append(f"\n<i>Свободных мест: {seats_left} из {event.total_seats}</i>")
    parts.append("")
    parts.append(texts.EVENT_ACTIONS_PROMPT)
    return "\n\n".join(parts)


# ─── Действия с мероприятием ──────────────────────────────────────────────


@router.callback_query(EventActionCB.filter(F.action == "teacher"))
async def on_teacher(cb: CallbackQuery, callback_data: EventActionCB, session: AsyncSession) -> None:
    event = await session.get(Event, callback_data.event_id)
    text = (event.teacher_info if event and event.teacher_info else texts.TEACHER_FALLBACK)
    assert cb.message is not None
    await cb.message.answer(text, reply_markup=kb.back_to_category_kb(event.category_id if event else 0))
    await cb.answer()


@router.callback_query(EventActionCB.filter(F.action == "book"))
async def on_book(cb: CallbackQuery, callback_data: EventActionCB, session: AsyncSession, state: FSMContext) -> None:
    event = await session.get(Event, callback_data.event_id)
    if event is None or not event.is_active:
        await cb.answer("Мероприятие недоступно", show_alert=True)
        return
    booked = await session.scalar(
        select(func.count(Booking.id)).where(
            Booking.event_id == event.id, Booking.status != BookingStatus.cancelled
        )
    )
    if (booked or 0) >= event.total_seats:
        assert cb.message is not None
        await cb.message.answer(texts.BOOKING_NO_SEATS)
        await cb.answer()
        return
    await state.set_state(BookingFlow.waiting_contact)
    await state.update_data(event_id=event.id)
    assert cb.message is not None
    await cb.message.answer(texts.ASK_CONTACT_BOOKING, reply_markup=kb.share_contact_kb())
    await cb.answer()


@router.callback_query(EventActionCB.filter(F.action == "callback"))
async def on_callback_request(
    cb: CallbackQuery, callback_data: EventActionCB, state: FSMContext
) -> None:
    await state.set_state(CallbackFlow.waiting_contact)
    await state.update_data(event_id=callback_data.event_id or None)
    assert cb.message is not None
    await cb.message.answer(texts.ASK_CONTACT_CALLBACK, reply_markup=kb.share_contact_kb())
    await cb.answer()


@router.callback_query(EventActionCB.filter(F.action == "question"))
async def on_question(cb: CallbackQuery, callback_data: EventActionCB, state: FSMContext) -> None:
    await state.set_state(QuestionFlow.waiting_text)
    await state.update_data(event_id=callback_data.event_id or None)
    assert cb.message is not None
    await cb.message.answer(texts.ASK_QUESTION_PROMPT, reply_markup=kb.remove_kb())
    await cb.answer()


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

    booked = await session.scalar(
        select(func.count(Booking.id)).where(
            Booking.event_id == event.id, Booking.status != BookingStatus.cancelled
        )
    )
    if (booked or 0) >= event.total_seats:
        await message.answer(texts.BOOKING_NO_SEATS, reply_markup=kb.remove_kb())
        return

    booking = Booking(user_id=user.id, event_id=event.id, phone=contact.phone_number or "")
    session.add(booking)
    await session.commit()

    await message.answer(texts.BOOKING_SUCCESS.format(event_title=event.title), reply_markup=kb.remove_kb())
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
