import os
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from reminder import ReminderSystem
from database import Database

# Загружаем переменные из .env файла
load_dotenv()

# Инициализируем базу данных
db = Database()

# Включаем логирование, чтобы видеть ошибки
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Читаем токен из переменной окружения
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("Токен не найден! Проверь файл .env")

# Функция-обработчик команды /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("📋 Мои квесты", callback_data="my_quests")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = f"""
Привет, {user.first_name}! 🚀

Я — твой проводник на пути к Сверхчеловеку. 
Вместе мы превратим рутину в увлекательную игру!

Выбери действие:
    """
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

# Функция-обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    Доступные команды:
    /start - Начать работу
    /help - Получить справку
    """
    await update.message.reply_text(help_text)

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # 1) Частичный прогресс
    if context.user_data.get("awaiting_partial_progress"):
        import re
        m = re.search(r"\d+", text)
        if not m:
            await update.message.reply_text("Пожалуйста, введи число. Пример: 10")
            return
        delta = int(m.group(0))
        quest_id = context.user_data.get("partial_progress_quest_id")
        if not quest_id:
            await update.message.reply_text("Контекст утерян. Попробуй снова из карточки квеста.")
            context.user_data["awaiting_partial_progress"] = False
            return

        user_id = update.effective_user.id
        quest = db.update_quest_progress(user_id, quest_id, delta)
        if not quest:
            await update.message.reply_text("Квест не найден")
            context.user_data["awaiting_partial_progress"] = False
            context.user_data.pop("partial_progress_quest_id", None)
            return

        if quest[5] >= quest[4]:
            db.complete_quest(user_id, quest_id)

        context.user_data["awaiting_partial_progress"] = False
        context.user_data.pop("partial_progress_quest_id", None)

        await update.message.reply_text("Прогресс обновлён! ✅")

        # Показать список квестов
        quests = db.get_user_quests(user_id)
        if not quests:
            list_text = "📋 У тебя пока нет активных квестов!\n\nНажми 'Создать квест' чтобы начать."
            keyboard = [
                [InlineKeyboardButton("➕ Создать квест", callback_data="create_quest")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")],
            ]
        else:
            list_text = "📋 Твои активные квесты:\n\n"
            keyboard = []
            for q in quests:
                qid = q[0]
                deadline_info = ""
                if len(q) > 7 and q[7]:
                    from datetime import datetime
                    try:
                        # Пробуем оба формата - с временем и без
                        try:
                            d = datetime.strptime(q[7], "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            d = datetime.strptime(q[7], "%Y-%m-%d")
                        deadline_info = f" 📅 {d.strftime('%d.%m.%Y %H:%M')}" if d.hour != 0 or d.minute != 0 else f" 📅 {d.strftime('%d.%m.%Y')}"
                    except Exception:
                        pass
                list_text += f"• {q[2]} ({q[5]}/{q[4]}){deadline_info}\n"
                keyboard.append([InlineKeyboardButton(f"Открыть: {q[2]}", callback_data=f"quest_{qid}")])
            keyboard.append([InlineKeyboardButton("➕ Создать квест", callback_data="create_quest")])
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])

        await update.message.reply_text(list_text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 2) Ввод названия квеста
    elif context.user_data.get("awaiting_quest_title"):
        if not text:
            await update.message.reply_text("Название не должно быть пустым. Введите название квеста:")
            return
        context.user_data["quest_title"] = text
        context.user_data["awaiting_quest_title"] = False
        context.user_data["awaiting_target_value"] = True
        await update.message.reply_text(
            "Отлично! Теперь укажи целевое значение (например: 50 для отжиманий, 30 для страниц):"
        )
        return

    # 3) Ввод целевого значения
    elif context.user_data.get("awaiting_target_value"):
        import re
        m = re.search(r"\d+", text)
        if not m:
            await update.message.reply_text("Пожалуйста, укажи число. Пример: 50")
            return
        target_value = int(m.group(0))

        quest_type = context.user_data.get("quest_type")
        quest_title = context.user_data.get("quest_title")
        if not quest_type or not quest_title:
            context.user_data["awaiting_target_value"] = False
            await update.message.reply_text("Контекст утерян. Начните заново: /start")
            return

        # Сохраняем целевое значение для следующего шага (дедлайн)
        context.user_data["target_value"] = target_value
        context.user_data["awaiting_target_value"] = False
        context.user_data["awaiting_deadline"] = True
        await update.message.reply_text(
            "Хочешь установить дедлайн для квеста?\n"
            "Форматы:\n"
            "• ДД.ММ.ГГГГ (например, 25.12.2024)\n"
            "• ДД.ММ.ГГГГ ЧЧ:ММ (например, 25.12.2024 18:30)\n"
            "• Или отправь 'нет' чтобы пропустить"
        )
        return

    # 4) Ввод дедлайна (опционально)
    elif context.user_data.get("awaiting_deadline"):
        user_input = (update.message.text or "").strip().lower()
        if user_input in {"нет", "no", "skip"}:
            deadline = None
            deadline_text = "без дедлайна"
        else:
            try:
                from datetime import datetime, timedelta
                user_input = user_input.replace('/', '.').replace('-', '.')
                if len(user_input.split('.')) == 3 and len(user_input.split('.')[2]) == 4:
                    deadline_date = datetime.strptime(user_input, "%d.%m.%Y")
                elif ' ' in user_input and ':' in user_input:
                    date_part, time_part = user_input.split(' ', 1)
                    deadline_date = datetime.strptime(f"{date_part} {time_part}", "%d.%m.%Y %H:%M")
                else:
                    raise ValueError("Неверный формат")

                if deadline_date < datetime.now():
                    await update.message.reply_text(
                        "❌ Нельзя установить прошедшую дату!\n"
                        "Введи будущую дату в формате ДД.ММ.ГГГГ или ДД.ММ.ГГГГ ЧЧ:ММ\n"
                        "Или отправь 'нет' чтобы пропустить"
                    )
                    return

                deadline = deadline_date.strftime("%Y-%m-%d %H:%M:%S")
                deadline_text = deadline_date.strftime("%d.%m.%Y %H:%M")
            except ValueError:
                await update.message.reply_text(
                    "❌ Неверный формат даты!\n"
                    "Используй:\n"
                    "• ДД.ММ.ГГГГ (например, 25.12.2024)\n"
                    "• ДД.ММ.ГГГГ ЧЧ:ММ (например, 25.12.2024 18:30)\n"
                    "• Или отправь 'нет' чтобы пропустить"
                )
                return

        quest_type = context.user_data.get("quest_type")
        quest_title = context.user_data.get("quest_title")
        target_value = context.user_data.get("target_value")
        if not quest_type or not quest_title or target_value is None:
            context.user_data.clear()
            await update.message.reply_text("Контекст утерян. Начните заново: /start")
            return

        user_id = update.effective_user.id
        db.create_quest(user_id=user_id, title=quest_title, quest_type=quest_type, target_value=target_value, deadline=deadline)

        # Очистка состояний
        context.user_data.clear()

        await update.message.reply_text(f"🎯 Квест '{quest_title}' создан! {deadline_text}")

        # Показать список квестов
        quests = db.get_user_quests(user_id)
        if not quests:
            list_text = "📋 У тебя пока нет активных квестов!\n\nНажми 'Создать квест' чтобы начать."
            keyboard = [
                [InlineKeyboardButton("➕ Создать квест", callback_data="create_quest")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")],
            ]
        else:
            list_text = "📋 Твои активные квесты:\n\n"
            keyboard = []
            for q in quests:
                qid = q[0]
                deadline_info = ""
                if len(q) > 7 and q[7]:
                    from datetime import datetime
                    try:
                        # Пробуем оба формата - с временем и без
                        try:
                            d = datetime.strptime(q[7], "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            d = datetime.strptime(q[7], "%Y-%m-%d")
                        deadline_info = f" 📅 {d.strftime('%d.%m.%Y %H:%M')}" if d.hour != 0 or d.minute != 0 else f" 📅 {d.strftime('%d.%m.%Y')}"
                    except Exception:
                        pass
                list_text += f"• {q[2]} ({q[5]}/{q[4]}){deadline_info}\n"
                keyboard.append([InlineKeyboardButton(f"Открыть: {q[2]}", callback_data=f"quest_{qid}")])
            keyboard.append([InlineKeyboardButton("➕ Создать квест", callback_data="create_quest")])
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])

        await update.message.reply_text(list_text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 5) Нет активных состояний
    else:
        response = f"Ты написал: '{text}'. Используй кнопки меню для навигации."
        await update.message.reply_text(response)

# Функции-обработчики для callback_data
async def handle_my_quests(query, context):
    user_id = query.from_user.id
    quests = db.get_user_quests(user_id)
    
    if not quests:
        text = "📋 У тебя пока нет активных квестов!\n\nНажми 'Создать квест' чтобы начать."
        keyboard = [
            [InlineKeyboardButton("➕ Создать квест", callback_data="create_quest")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
        ]
    else:
        text = "📋 Твои активные квесты:\n\n"
        keyboard = []
        for quest in quests:
            qid = quest[0]
            deadline_info = ""
            if len(quest) > 7 and quest[7]:
                from datetime import datetime
                try:
                    # Пробуем оба формата
                    try:
                        d = datetime.strptime(quest[7], "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        d = datetime.strptime(quest[7], "%Y-%m-%d")
                    deadline_info = f" 📅 {d.strftime('%d.%m.%Y %H:%M')}" if d.hour != 0 or d.minute != 0 else f" 📅 {d.strftime('%d.%m.%Y')}"
                except Exception:
                    pass
            text += f"• {quest[2]} ({quest[5]}/{quest[4]}){deadline_info}\n"
            keyboard.append([InlineKeyboardButton(f"Открыть: {quest[2]}", callback_data=f"quest_{qid}")])
        keyboard.append([InlineKeyboardButton("➕ Создать квест", callback_data="create_quest")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)

async def handle_stats(query, context):
    await query.edit_message_text("📊 Раздел 'Статистика' в разработке...")

async def handle_help(query, context):
    await query.edit_message_text("❓ Раздел 'Помощь' в разработке...")

async def handle_create_quest(query, context):
    context.user_data["creating_quest"] = True
    context.user_data.pop("awaiting_quest_name", None)
    context.user_data.pop("awaiting_quest_title", None)
    context.user_data.pop("awaiting_target_value", None)
    context.user_data.pop("new_quest_type", None)
    context.user_data.pop("new_quest_title", None)
    context.user_data.pop("quest_title", None)
    
    text = (
        "Выбери тип квеста:\n\n"
        "- 💪 Физические упражнения\n"
        "- 📚 Чтение\n"
        "- 🧠 Медитация\n"
        "- 🎯 Произвольная задача"
    )
    keyboard = [
        [InlineKeyboardButton("💪 Физические упражнения", callback_data="quest_type_physical")],
        [InlineKeyboardButton("📚 Чтение", callback_data="quest_type_reading")],
        [InlineKeyboardButton("🧠 Медитация", callback_data="quest_type_meditation")],
        [InlineKeyboardButton("🎯 Произвольная задача", callback_data="quest_type_custom")],
        [InlineKeyboardButton("🔙 Назад", callback_data="my_quests")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)

async def handle_quest_progress(query, context):
    user_id = query.from_user.id
    try:
        quest_id = int(query.data.rsplit("_", 1)[1])
    except Exception:
        await query.edit_message_text("Некорректный идентификатор квеста")
        return

    context.user_data["awaiting_partial_progress"] = True
    context.user_data["partial_progress_quest_id"] = quest_id
    await query.edit_message_text("Введи величину прогресса числом (например, 10):")

async def handle_quest_complete(query, context):
    user_id = query.from_user.id
    try:
        quest_id = int(query.data.rsplit("_", 1)[1])
    except Exception:
        await query.edit_message_text("Некорректный идентификатор квеста")
        return

    quest = db.complete_quest(user_id, quest_id)
    if not quest:
        await query.edit_message_text("Квест не найден")
        return

    await query.edit_message_text("Квест завершён! ✅", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Назад", callback_data="my_quests")]
    ]))

async def handle_quest_detail(query, context):
    user_id = query.from_user.id
    try:
        quest_id = int(query.data.split("_", 1)[1])
    except Exception:
        await query.edit_message_text("Некорректный идентификатор квеста")
        return

    quest = db.get_quest(user_id, quest_id)
    if not quest:
        await query.edit_message_text("Квест не найден")
        return

    title = quest[2]
    quest_type = quest[3]
    target_value = quest[4]
    current_value = quest[5]
    completed = bool(quest[6])

    status = "✅ Завершен" if completed else "⏳ В процессе"
    text = (
        f"🏷️ {title}\n"
        f"Тип: {quest_type}\n"
        f"Прогресс: {current_value}/{target_value}\n"
        f"Статус: {status}"
    )

    if len(quest) > 7 and quest[7]:
        from datetime import datetime
        try:
            try:
                d = datetime.strptime(quest[7], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                d = datetime.strptime(quest[7], "%Y-%m-%d")
            text += f"\nДедлайн: {d.strftime('%d.%m.%Y %H:%M')}" if d.hour != 0 or d.minute != 0 else f"\nДедлайн: {d.strftime('%d.%m.%Y')}"
        except Exception:
            pass

    keyboard = []
    if not completed:
        keyboard.append([InlineKeyboardButton("➕ Частичный прогресс", callback_data=f"quest_progress_{quest_id}")])
        keyboard.append([InlineKeyboardButton("✅ Завершить", callback_data=f"quest_complete_{quest_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="my_quests")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_quest_type(query, context):
    type_map = {
        "quest_type_physical": "physical",
        "quest_type_reading": "reading",
        "quest_type_meditation": "meditation",
        "quest_type_custom": "custom",
    }
    context.user_data["quest_type"] = type_map.get(query.data, "custom")
    context.user_data["awaiting_quest_title"] = True
    await query.edit_message_text(
        "Отлично! Введи название квеста сообщением.\nНапример: 'Утренняя пробежка', 'Читать 20 минут'"
    )

async def handle_back_to_main(query, context):
    keyboard = [
        [InlineKeyboardButton("📋 Мои квесты", callback_data="my_quests")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выбери действие:", reply_markup=reply_markup)

# Главная callback функция
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Словарь обработчиков для разных callback_data
    handlers = {
        "my_quests": handle_my_quests,
        "stats": handle_stats,
        "help": handle_help,
        "create_quest": handle_create_quest,
        "back_to_main": handle_back_to_main
    }
    
    # Обработка специальных случаев с префиксами
    if query.data.startswith("quest_progress_"):
        await handle_quest_progress(query, context)
    elif query.data.startswith("quest_complete_"):
        await handle_quest_complete(query, context)
    elif query.data.startswith("quest_") and query.data.split("_", 1)[1].isdigit():
        await handle_quest_detail(query, context)
    elif query.data in {"quest_type_physical", "quest_type_reading", "quest_type_meditation", "quest_type_custom"}:
        await handle_quest_type(query, context)
    # Обычные обработчики из словаря
    elif query.data in handlers:
        await handlers[query.data](query, context)
    else:
        await query.edit_message_text("Неизвестная команда")

# Главная функция, где все собирается
def main():
    # Создаем приложение и передаем ему токен
    application = Application.builder().token(TOKEN).build()

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # Единый обработчик текстовых сообщений по состояниям
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))

    # Обработчик для INLINE-КНОПОК
    application.add_handler(CallbackQueryHandler(button_callback))

    # Запуск системы напоминаний в фоне
    async def run_reminders():
        reminder = ReminderSystem()
        while True:
            try:
                sent = await reminder.check_deadlines()
                if sent > 0:
                    logging.info(f"Отправлено {sent} напоминаний")
                await asyncio.sleep(60)
            except Exception as e:
                logging.error(f"Ошибка в системе напоминаний: {e}")
                await asyncio.sleep(300)

    # Запускаем в фоне
    loop = asyncio.get_event_loop()
    loop.create_task(run_reminders())

    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()