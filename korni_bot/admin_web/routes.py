from datetime import datetime

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from korni_bot.admin_web.auth import (
    AdminDep,
    clear_session_cookie,
    require_admin,
    set_session_cookie,
)
from korni_bot.admin_web.deps import BotDep, DbDep
from korni_bot.bot.handlers.broadcast import run_broadcast
from korni_bot.config import get_settings
from korni_bot.db.models import (
    Booking,
    BookingStatus,
    Broadcast,
    Callback,
    CallbackStatus,
    Category,
    Event,
    User,
)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _render(request: Request, name: str, **ctx) -> HTMLResponse:
    return _templates(request).TemplateResponse(request, name, ctx)


# ─── Auth ─────────────────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _render(request, "login.html", error=None)


@router.post("/login")
async def login_submit(
    request: Request, login: str = Form(...), password: str = Form(...)
):
    settings = get_settings()
    if login == settings.admin_login and password == settings.admin_password:
        resp = RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)
        set_session_cookie(resp, login)
        return resp
    return _render(request, "login.html", error="Неверный логин или пароль")


@router.post("/logout")
async def logout():
    resp = RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(resp)
    return resp


# ─── Dashboard ────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, admin: str = AdminDep, session: AsyncSession = DbDep):
    stats = {
        "users": await session.scalar(select(func.count(User.id))) or 0,
        "events": await session.scalar(select(func.count(Event.id)).where(Event.is_active.is_(True))) or 0,
        "bookings_pending": await session.scalar(
            select(func.count(Booking.id)).where(Booking.status == BookingStatus.pending)
        ) or 0,
        "callbacks_pending": await session.scalar(
            select(func.count(Callback.id)).where(Callback.status == CallbackStatus.pending)
        ) or 0,
    }
    return _render(request, "dashboard.html", stats=stats)


# ─── Categories ───────────────────────────────────────────────────────────


@router.get("/categories", response_class=HTMLResponse)
async def categories_list(request: Request, admin: str = AdminDep, session: AsyncSession = DbDep):
    categories = list(
        await session.scalars(select(Category).order_by(Category.sort_order, Category.id))
    )
    return _render(request, "categories.html", categories=categories)


@router.post("/categories")
async def category_create(
    title: str = Form(...),
    emoji: str = Form(""),
    sort_order: int = Form(0),
    admin: str = AdminDep,
    session: AsyncSession = DbDep,
):
    session.add(Category(title=title.strip(), emoji=emoji.strip() or None, sort_order=sort_order))
    await session.commit()
    return RedirectResponse("/admin/categories", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/categories/{cat_id}/update")
async def category_update(
    cat_id: int,
    title: str = Form(...),
    emoji: str = Form(""),
    sort_order: int = Form(0),
    is_active: str = Form(""),
    admin: str = AdminDep,
    session: AsyncSession = DbDep,
):
    cat = await session.get(Category, cat_id)
    if cat is None:
        raise HTTPException(404)
    cat.title = title.strip()
    cat.emoji = emoji.strip() or None
    cat.sort_order = sort_order
    cat.is_active = is_active == "on"
    await session.commit()
    return RedirectResponse("/admin/categories", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/categories/{cat_id}/delete")
async def category_delete(cat_id: int, admin: str = AdminDep, session: AsyncSession = DbDep):
    await session.execute(delete(Category).where(Category.id == cat_id))
    await session.commit()
    return RedirectResponse("/admin/categories", status_code=status.HTTP_303_SEE_OTHER)


# ─── Events ───────────────────────────────────────────────────────────────


@router.get("/events", response_class=HTMLResponse)
async def events_list(request: Request, admin: str = AdminDep, session: AsyncSession = DbDep):
    events = list(
        await session.scalars(select(Event).order_by(Event.event_date.nulls_last(), Event.id.desc()))
    )
    cat_map = {
        c.id: c for c in await session.scalars(select(Category))
    }
    booked_rows = list(
        await session.execute(
            select(Booking.event_id, func.count(Booking.id))
            .where(Booking.status != BookingStatus.cancelled)
            .group_by(Booking.event_id)
        )
    )
    booked_map = {row[0]: row[1] for row in booked_rows}
    return _render(
        request, "events.html", events=events, categories=cat_map, booked_map=booked_map
    )


@router.get("/events/new", response_class=HTMLResponse)
async def event_new_form(request: Request, admin: str = AdminDep, session: AsyncSession = DbDep):
    categories = list(await session.scalars(select(Category).order_by(Category.sort_order)))
    return _render(request, "event_form.html", event=None, categories=categories)


@router.post("/events/new")
async def event_create(
    request: Request,
    title: str = Form(...),
    category_id: int = Form(...),
    description: str = Form(""),
    teacher_info: str = Form(""),
    total_seats: int = Form(0),
    event_date: str = Form(""),
    is_active: str = Form(""),
    photo: UploadFile | None = File(None),
    admin: str = AdminDep,
    session: AsyncSession = DbDep,
    bot: Bot = BotDep,
):
    photo_file_id = await _upload_photo(bot, photo, title) if photo else None
    event = Event(
        title=title.strip(),
        category_id=category_id,
        description=description,
        teacher_info=teacher_info or None,
        total_seats=total_seats,
        photo_file_id=photo_file_id,
        event_date=_parse_dt(event_date),
        is_active=is_active == "on",
    )
    session.add(event)
    await session.commit()
    return RedirectResponse("/admin/events", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/events/{event_id}", response_class=HTMLResponse)
async def event_edit_form(
    request: Request, event_id: int, admin: str = AdminDep, session: AsyncSession = DbDep
):
    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(404)
    categories = list(await session.scalars(select(Category).order_by(Category.sort_order)))
    return _render(request, "event_form.html", event=event, categories=categories)


@router.post("/events/{event_id}/update")
async def event_update(
    event_id: int,
    title: str = Form(...),
    category_id: int = Form(...),
    description: str = Form(""),
    teacher_info: str = Form(""),
    total_seats: int = Form(0),
    event_date: str = Form(""),
    is_active: str = Form(""),
    photo: UploadFile | None = File(None),
    keep_photo: str = Form("on"),
    admin: str = AdminDep,
    session: AsyncSession = DbDep,
    bot: Bot = BotDep,
):
    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(404)
    event.title = title.strip()
    event.category_id = category_id
    event.description = description
    event.teacher_info = teacher_info or None
    event.total_seats = total_seats
    event.event_date = _parse_dt(event_date)
    event.is_active = is_active == "on"
    if photo and photo.filename:
        event.photo_file_id = await _upload_photo(bot, photo, title)
    elif keep_photo != "on":
        event.photo_file_id = None
    await session.commit()
    return RedirectResponse("/admin/events", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/events/{event_id}/delete")
async def event_delete(event_id: int, admin: str = AdminDep, session: AsyncSession = DbDep):
    await session.execute(delete(Event).where(Event.id == event_id))
    await session.commit()
    return RedirectResponse("/admin/events", status_code=status.HTTP_303_SEE_OTHER)


# ─── Bookings / Callbacks ─────────────────────────────────────────────────


@router.get("/bookings", response_class=HTMLResponse)
async def bookings_list(request: Request, admin: str = AdminDep, session: AsyncSession = DbDep):
    rows = list(
        await session.execute(
            select(Booking, User, Event)
            .join(User, User.id == Booking.user_id)
            .join(Event, Event.id == Booking.event_id)
            .order_by(Booking.created_at.desc())
            .limit(500)
        )
    )
    return _render(request, "bookings.html", rows=rows)


@router.post("/bookings/{booking_id}/status")
async def booking_set_status(
    booking_id: int,
    new_status: str = Form(...),
    admin: str = AdminDep,
    session: AsyncSession = DbDep,
):
    b = await session.get(Booking, booking_id)
    if b is None:
        raise HTTPException(404)
    b.status = BookingStatus(new_status)
    await session.commit()
    return RedirectResponse("/admin/bookings", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/callbacks", response_class=HTMLResponse)
async def callbacks_list(request: Request, admin: str = AdminDep, session: AsyncSession = DbDep):
    rows = list(
        await session.execute(
            select(Callback, User, Event)
            .join(User, User.id == Callback.user_id)
            .outerjoin(Event, Event.id == Callback.event_id)
            .order_by(Callback.created_at.desc())
            .limit(500)
        )
    )
    return _render(request, "callbacks.html", rows=rows)


@router.post("/callbacks/{cb_id}/done")
async def callback_done(cb_id: int, admin: str = AdminDep, session: AsyncSession = DbDep):
    c = await session.get(Callback, cb_id)
    if c is None:
        raise HTTPException(404)
    c.status = CallbackStatus.done
    await session.commit()
    return RedirectResponse("/admin/callbacks", status_code=status.HTTP_303_SEE_OTHER)


# ─── Users ────────────────────────────────────────────────────────────────


@router.get("/users", response_class=HTMLResponse)
async def users_list(request: Request, admin: str = AdminDep, session: AsyncSession = DbDep):
    users = list(await session.scalars(select(User).order_by(User.created_at.desc()).limit(1000)))
    return _render(request, "users.html", users=users)


# ─── Broadcast ────────────────────────────────────────────────────────────


@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, admin: str = AdminDep, session: AsyncSession = DbDep):
    history = list(await session.scalars(select(Broadcast).order_by(Broadcast.created_at.desc()).limit(20)))
    return _render(request, "broadcast.html", history=history, result=None)


@router.post("/broadcast")
async def broadcast_send(
    request: Request,
    text: str = Form(...),
    photo: UploadFile | None = File(None),
    admin: str = AdminDep,
    session: AsyncSession = DbDep,
    bot: Bot = BotDep,
):
    photo_file_id = await _upload_photo(bot, photo, "broadcast") if photo and photo.filename else None
    broadcast = Broadcast(text=text, photo_file_id=photo_file_id)
    session.add(broadcast)
    await session.commit()

    sent, failed = await run_broadcast(bot, text=text, photo_file_id=photo_file_id, session_maker=None)
    broadcast.sent_count = sent
    broadcast.failed_count = failed
    await session.commit()

    history = list(await session.scalars(select(Broadcast).order_by(Broadcast.created_at.desc()).limit(20)))
    return _render(
        request,
        "broadcast.html",
        history=history,
        result={"sent": sent, "failed": failed},
    )


# ─── helpers ──────────────────────────────────────────────────────────────


_upload_logger = logging.getLogger(__name__)


async def _upload_photo(bot: Bot, photo: UploadFile | None, label: str) -> str | None:
    if photo is None or not photo.filename:
        return None
    data = await photo.read()
    if not data:
        return None
    settings = get_settings()
    try:
        msg = await bot.send_photo(
            settings.admin_group_id,
            BufferedInputFile(data, filename=photo.filename),
            caption=f"📤 Upload: {label}",
        )
    except TelegramAPIError as e:
        _upload_logger.error(
            "Failed to upload photo to admin group %s: %s. "
            "Мероприятие сохранится без фото. Проверь ADMIN_GROUP_ID и что бот в группе админом.",
            settings.admin_group_id,
            e,
        )
        return None
    return msg.photo[-1].file_id


def _parse_dt(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None
