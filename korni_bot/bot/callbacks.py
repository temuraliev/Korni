"""CallbackData для inline-клавиатур. Короткие префиксы — лимит Telegram 64 байта."""
from aiogram.filters.callback_data import CallbackData


class StartBrowseCB(CallbackData, prefix="start"):
    pass


class CategoryCB(CallbackData, prefix="cat"):
    id: int


class EventCB(CallbackData, prefix="ev"):
    id: int


class EventActionCB(CallbackData, prefix="evact"):
    event_id: int
    action: str  # book | teacher | question | callback


class BackCB(CallbackData, prefix="back"):
    to: str  # root | categories | category-{id}  (":" запрещён — это разделитель aiogram CallbackData)
