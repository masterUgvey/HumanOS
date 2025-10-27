"""
Главный файл для запуска Telegram-бота на aiogram 3.x
Точка входа приложения
"""

import asyncio
import sys
from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import config
from database_async import db
from handlers import router


async def on_startup():
    """Действия при запуске бота"""
    logger.info("🚀 Запуск бота...")
    
    # Инициализация базы данных
    await db.init_db()
    logger.info("✅ База данных готова")


async def on_shutdown():
    """Действия при остановке бота"""
    logger.info("🛑 Остановка бота...")


async def main():
    """Основная функция запуска бота"""
    
    # Настройка логирования
    logger.remove()  # Удаляем стандартный обработчик
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level=config.LOG_LEVEL
    )
    logger.add(
        "bot.log",
        rotation="10 MB",
        retention="7 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}"
    )
    
    # Валидация конфигурации
    if not config.validate():
        logger.error("❌ Ошибка конфигурации! Проверьте файл .env")
        return
    
    # Создание бота и диспетчера
    bot = Bot(token=config.BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Регистрация роутера с обработчиками
    dp.include_router(router)
    
    # Регистрация startup/shutdown функций
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    try:
        logger.info("✅ Бот запущен и готов к работе!")
        logger.info(f"📊 База данных: {config.DATABASE_PATH}")
        logger.info(f"🤖 AI: {'Включен' if config.WINDSURF_API_KEY else 'Выключен'}")
        
        # Запуск polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
    
    finally:
        await bot.session.close()
        logger.info("👋 Бот остановлен")


if __name__ == "__main__":
    """
    Запуск бота
    
    Для запуска выполните:
        python main.py
    
    Для остановки нажмите Ctrl+C
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {e}")
