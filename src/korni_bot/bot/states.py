from aiogram.fsm.state import State, StatesGroup


class BookingFlow(StatesGroup):
    waiting_contact = State()


class CallbackFlow(StatesGroup):
    waiting_contact = State()


class QuestionFlow(StatesGroup):
    waiting_text = State()
