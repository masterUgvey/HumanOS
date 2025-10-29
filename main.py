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
from datetime import datetime, timedelta, timezone

# Очередь для RT-логов
LOG_QUEUE: asyncio.Queue | None = None

# Состояние напоминаний в памяти: {quest_id: {"h1": bool, "overdue": bool}}
REMINDER_STATE = {}


async def reminder_loop(bot: Bot):
    """Фоновая задача: рассылает напоминания за час до дедлайна и по просрочке"""
    global REMINDER_STATE
    while True:
        try:
            quests = await db.get_quests_with_deadlines()
            now_utc = datetime.now(timezone.utc)
            for q in quests:
                # Порядок: quest_id(0), user_id(1), title(2), quest_type(3), target(4), current(5),
                # completed(6), deadline(7), comment(8), created_at(9), has_date(10), has_time(11)
                quest_id, user_id, title = q[0], q[1], q[2]
                completed = bool(q[6])
                deadline_str = q[7]
                has_date = bool(q[10]) if len(q) > 10 else True
                if completed or not deadline_str or not has_date:
                    continue
                try:
                    dt_deadline_utc = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                delta = dt_deadline_utc - now_utc
                state = REMINDER_STATE.setdefault(quest_id, {"h1": False, "overdue": False})
                # Напоминание за час
                if 0 <= delta.total_seconds() <= 3600 and not state["h1"]:
                    tz_off, _ = await db.get_user_timezone(user_id)
                    dt_local = dt_deadline_utc + timedelta(minutes=int(tz_off or 0))
                    time_str = dt_local.strftime("%H:%M")
                    date_str = dt_local.strftime("%d.%m.%y")
                    try:
                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🔎 Открыть квест", callback_data=f"quest_{quest_id}")],
                            [InlineKeyboardButton(text="📋 Квесты", callback_data="my_quests_inline")],
                        ])
                        await bot.send_message(user_id, f"🟡 Напоминание: до дедлайна квеста «{title}» остался 1 час.\nДедлайн: {date_str} {time_str}", reply_markup=kb)
                        state["h1"] = True
                    except Exception:
                        pass
                # Просрочка
                if delta.total_seconds() < 0 and not state["overdue"]:
                    tz_off, _ = await db.get_user_timezone(user_id)
                    dt_local = dt_deadline_utc + timedelta(minutes=int(tz_off or 0))
                    time_str = dt_local.strftime("%H:%M")
                    date_str = dt_local.strftime("%d.%m.%y")
                    try:
                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🔎 Открыть квест", callback_data=f"quest_{quest_id}")],
                            [InlineKeyboardButton(text="📋 Квесты", callback_data="my_quests_inline")],
                        ])
                        await bot.send_message(user_id, f"🔴 Просрочен дедлайн по квесту «{title}».\nДедлайн был: {date_str} {time_str}", reply_markup=kb)
                        state["overdue"] = True
                    except Exception:
                        pass
            # Пауза между циклами
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Reminder loop error: {e}")
            await asyncio.sleep(60)


async def on_startup(bot: Bot):
    """Действия при запуске бота"""
    logger.info("🚀 Запуск бота...")
    # Инициализация базы данных
    await db.init_db()
    logger.info("✅ База данных готова")
    # Запуск фоновой задачи напоминаний
    bot.reminder_task = asyncio.create_task(reminder_loop(bot))
    # Настройка RT-логов
    global LOG_QUEUE
    LOG_QUEUE = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _sink(message):
        try:
            loop.call_soon_threadsafe(LOG_QUEUE.put_nowait, str(message))
        except Exception:
            pass

    # Дополнительный sink для логов (оставляем stderr и файл как есть)
    bot.log_sink_id = logger.add(_sink, level="INFO")

    async def _log_dispatcher():
        while True:
            try:
                line = await LOG_QUEUE.get()
                subs = await db.get_log_subscribers()
                if not subs:
                    continue
                # Отправляем только информативные строки, без слишком длинных
                text = line[-800:]
                for uid in subs:
                    try:
                        await bot.send_message(uid, f"📟 {text}")
                    except Exception:
                        pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"log dispatcher error: {e}")
                await asyncio.sleep(0.5)

    bot.log_task = asyncio.create_task(_log_dispatcher())


async def on_shutdown(bot: Bot):
    """Действия при остановке бота"""
    logger.info("🛑 Остановка бота...")
    # Убираем дополнительный sink, чтобы прекратить отправку RT-логов
    sink_id = getattr(bot, "log_sink_id", None)
    if sink_id is not None:
        try:
            logger.remove(sink_id)
        except Exception:
            pass
    # Останов фоновой задачи
    task = getattr(bot, "reminder_task", None)
    if task:
        task.cancel()
        try:
            await task
        except Exception:
            pass
    # Останов лог-диспетчера
    ltask = getattr(bot, "log_task", None)
    if ltask:
        ltask.cancel()
        try:
            await ltask
        except Exception:
            pass
    # Обнуляем очередь логов
    global LOG_QUEUE
    LOG_QUEUE = None


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
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except asyncio.CancelledError:
        logger.info("🛑 Остановка: polling отменен")
    except KeyboardInterrupt:
        logger.info("🛑 Остановка: прерывание пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
    
    finally:
        try:
            await dp.storage.close()
            await dp.storage.wait_closed()
        except Exception:
            pass
        await bot.session.close()
        logger.info("👋 Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
