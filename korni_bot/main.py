import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

from korni_bot.admin_web.app import register_admin
from korni_bot.bot.dispatcher import build_bot, build_dispatcher
from korni_bot.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("korni_bot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    bot = build_bot()
    dp = build_dispatcher()

    app.state.bot = bot
    app.state.dispatcher = dp

    try:
        await bot.set_webhook(
            url=settings.webhook_url,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )
        logger.info("Webhook set to %s", settings.webhook_url)
    except Exception as e:
        logger.error(
            "Failed to set webhook (%s). App will start anyway — fix WEBHOOK_BASE_URL and redeploy.",
            e,
        )

    try:
        yield
    finally:
        # НЕ удаляем webhook при shutdown: Railway при редеплое сначала глушит старый контейнер,
        # а новый поднимается не мгновенно. Если удалить webhook — в окне между контейнерами
        # апдейты от юзеров копятся, а потом Telegram их может и отбросить. Лучше оставить.
        await bot.session.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Korni bot", lifespan=lifespan)

    register_admin(app)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/admin/")

    @app.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
    async def health():
        return "ok"

    @app.post(settings.webhook_path, include_in_schema=False)
    async def telegram_webhook(request: Request):
        bot = request.app.state.bot
        dp = request.app.state.dispatcher
        payload = await request.json()
        update = Update.model_validate(payload, context={"bot": bot})
        # Отвечаем Telegram 200 мгновенно, обработку кидаем в фон.
        # Иначе Telegram не шлёт следующий апдейт юзера пока не получит ответ
        # на текущий → при частых нажатиях кнопок чувствуется лаг.
        asyncio.create_task(_process_update(dp, bot, update))
        return Response(status_code=200)

    return app


async def _process_update(dp: Dispatcher, bot: Bot, update: Update) -> None:
    try:
        await dp.feed_update(bot, update)
    except Exception:
        logger.exception("Update processing failed (update_id=%s)", update.update_id)


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "korni_bot.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
