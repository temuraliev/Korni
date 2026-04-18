"""Локальный запуск бота в long-polling режиме.

Использование:
    uv run python -m korni_bot.polling

Нужен .env с теми же переменными, что и для продакшена (BOT_TOKEN, DATABASE_URL, ADMIN_GROUP_ID и т.д.),
КРОМЕ WEBHOOK_BASE_URL — его можно любой указать, он не используется в polling.

Перед запуском webhook в Telegram будет удалён (иначе polling не работает параллельно).
При остановке (Ctrl+C) webhook НЕ восстанавливается — перед деплоем на Railway редеплой сам
его поставит через lifespan в main.py.
"""
import asyncio
import logging

from korni_bot.bot.dispatcher import build_bot, build_dispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("korni_bot.polling")


async def main() -> None:
    bot = build_bot()
    dp = build_dispatcher()

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook removed, starting polling…")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
