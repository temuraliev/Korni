from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from korni_bot.bot.callbacks import (
    BackCB,
    CategoryCB,
    EventActionCB,
    EventCB,
    StartBrowseCB,
)
from korni_bot.db.models import Category, Event

QUESTION_BTN_TEXT = "У меня есть другой вопрос!"


def start_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Начать", callback_data=StartBrowseCB())
    return b.as_markup()


def categories_kb(categories: list[Category]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in categories:
        label = f"{c.emoji} {c.title}".strip() if c.emoji else c.title
        b.button(text=label, callback_data=CategoryCB(id=c.id))
    b.button(text=QUESTION_BTN_TEXT, callback_data=EventActionCB(event_id=0, action="question"))
    b.adjust(1)
    return b.as_markup()


def events_kb(events: list[Event]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for e in events:
        b.button(text=e.title, callback_data=EventCB(id=e.id))
    b.button(text="◀️ Назад", callback_data=BackCB(to="categories"))
    b.adjust(1)
    return b.as_markup()


def event_actions_kb(event_id: int, category_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Все понятно, хочу забронировать!", callback_data=EventActionCB(event_id=event_id, action="book"))
    b.button(text="Подробнее про преподавателя", callback_data=EventActionCB(event_id=event_id, action="teacher"))
    b.button(text="У меня есть вопрос", callback_data=EventActionCB(event_id=event_id, action="question"))
    b.button(text="🎁 Я хочу получить скидку", callback_data=EventActionCB(event_id=event_id, action="discount"))
    b.button(text="◀️ Назад", callback_data=BackCB(to=f"category-{category_id}"))
    b.adjust(1)
    return b.as_markup()


def question_submenu_kb(event_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✍️ Напишите мне", callback_data=EventActionCB(event_id=event_id, action="qwrite"))
    b.button(text="📞 Позвоните мне", callback_data=EventActionCB(event_id=event_id, action="qcall"))
    b.button(text="☎️ Я сам позвоню", callback_data=EventActionCB(event_id=event_id, action="qself"))
    b.button(text="◀️ Назад", callback_data=EventActionCB(event_id=event_id, action="back_to_event"))
    b.adjust(1)
    return b.as_markup()


def discount_kb(event_id: int, instagram_url: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📷 Открыть Instagram", url=instagram_url)
    b.button(text="✅ Я подписался!", callback_data=EventActionCB(event_id=event_id, action="discount_check"))
    b.button(text="◀️ Назад", callback_data=EventActionCB(event_id=event_id, action="back_to_event"))
    b.adjust(1)
    return b.as_markup()


def discount_success_kb(event_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎟 Забронировать", callback_data=EventActionCB(event_id=event_id, action="book"))
    b.button(text="◀️ Назад", callback_data=EventActionCB(event_id=event_id, action="back_to_event"))
    b.adjust(1)
    return b.as_markup()


def back_to_category_kb(category_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ К мероприятиям", callback_data=BackCB(to=f"category-{category_id}"))
    return b.as_markup()


def share_contact_kb(text: str = "📞 Поделиться контактом") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Нажмите кнопку ниже",
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def admin_reply_hint_kb(user_tg_id: int) -> InlineKeyboardMarkup:
    """Маленькая подсказка под форвардом — чтобы админ видел, чей это вопрос."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"👤 tg://user?id={user_tg_id}", url=f"tg://user?id={user_tg_id}")]
        ]
    )
