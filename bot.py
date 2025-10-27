import os
import logging
import asyncio
from datetime import datetime
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

QUEST_TYPES = {
    "physical": "💪 Физическая задача",
    "intellectual": "📚 Интеллектуальная задача",
    "mental": "🧠 Ментальная задача",
    "custom": "🎯 Произвольная задача"
}


def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 Квесты", callback_data="quests_menu")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_quests_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Мои квесты", callback_data="my_quests")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_quest_type_keyboard():
    keyboard = [
        [InlineKeyboardButton("💪 Физическая задача", callback_data="type_physical")],
        [InlineKeyboardButton("📚 Интеллектуальная задача", callback_data="type_intellectual")],
        [InlineKeyboardButton("🧠 Ментальная задача", callback_data="type_mental")],
        [InlineKeyboardButton("🎯 Произвольная задача", callback_data="type_custom")],
        [InlineKeyboardButton("❌ Отменить", callback_data="quests_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_cancel_keyboard(callback="cancel_creation"):
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data=callback)]]
    return InlineKeyboardMarkup(keyboard)


def format_quest_text(quest):
    quest_id, user_id, title, quest_type, target_value, current_value, completed, deadline, comment, created_at = quest
    
    type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
    
    if quest_type in ["physical", "intellectual"]:
        progress_text = f"{current_value}/{target_value}"
    else:
        progress_text = f"{current_value}%"
    
    status = "✅ Завершен" if completed else "⏳ В процессе"
    
    text = f"{type_emoji} **{title}**\\n\\n"
    text += f"Тип: {QUEST_TYPES.get(quest_type, quest_type)}\\n"
    text += f"Прогресс: {progress_text}\\n"
    text += f"Статус: {status}\\n"
    
    if deadline:
        try:
            try:
                d = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                d = datetime.strptime(deadline, "%Y-%m-%d")
            
            if d.hour != 0 or d.minute != 0:
                text += f"📅 Дедлайн: {d.strftime('%d.%m.%y %H:%M')}\\n"
            else:
                text += f"📅 Дедлайн: {d.strftime('%d.%m.%y')}\\n"
        except:
            pass
    
    if comment:
        text += f"\\n💬 Комментарий: {comment}\\n"
    
    return text


def get_quest_detail_keyboard(quest_id, completed):
    keyboard = []
    if not completed:
        keyboard.append([InlineKeyboardButton("📈 Обновить прогресс", callback_data=f"progress_{quest_id}")])
        keyboard.append([InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{quest_id}")])
    keyboard.append([InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{quest_id}")])
    keyboard.append([InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_{quest_id}")])
    keyboard.append([InlineKeyboardButton("🔙 К списку квестов", callback_data="my_quests")])
    return InlineKeyboardMarkup(keyboard)


def get_edit_quest_keyboard(quest_id):
    keyboard = [
        [InlineKeyboardButton("📝 Название", callback_data=f"edit_title_{quest_id}")],
        [InlineKeyboardButton("🎯 Целевое значение", callback_data=f"edit_target_{quest_id}")],
        [InlineKeyboardButton("📅 Дедлайн", callback_data=f"edit_deadline_{quest_id}")],
        [InlineKeyboardButton("💬 Комментарий", callback_data=f"edit_comment_{quest_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"quest_{quest_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


# Функция-обработчик команды /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.first_name)
    context.user_data.clear()
    
    welcome_text = f"""
Привет, {user.first_name}! 🚀

Я — твой проводник на пути к Сверхчеловеку. 
Вместе мы превратим рутину в увлекательную игру!

Выбери действие:
    """
    
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu_keyboard())

# Функция-обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    Доступные команды:
    /start - Начать работу
    /help - Получить справку
    """
    await update.message.reply_text(help_text)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    text = update.message.text.strip()
    user_id = update.effective_user.id
    state = context.user_data.get("state")
    
    if not text:
        await update.message.reply_text("❌ Сообщение не может быть пустым.")
        return
    
    try:
        # Создание квеста - ввод названия
        if state == "awaiting_title":
            is_valid, error_msg = db.validate_input(text, "Название")
            if not is_valid:
                await update.message.reply_text(f"❌ {error_msg}\n\nПопробуй ещё раз")
                return
            
            context.user_data["quest_title"] = text
            quest_type = context.user_data.get("quest_type")
            
            if quest_type in ["mental", "custom"]:
                context.user_data["target_value"] = 100
                context.user_data["state"] = "awaiting_deadline"
                
                text_msg = f"Название: {text}\n\nУстановить дедлайн?\n**Форматы:**\n• ДД.ММ.ГГ ЧЧ:ММ\n• ДД.ММ.ГГ\n• 'нет' - пропустить"
                await update.message.reply_text(text_msg, parse_mode='Markdown')
            else:
                context.user_data["state"] = "awaiting_target"
                text_msg = f"Название: {text}\n\nВведи целевое значение:\n**Примеры:** 50, 100"
                await update.message.reply_text(text_msg, parse_mode='Markdown')
        
        # Создание квеста - ввод целевого значения
        elif state == "awaiting_target":
            if not text.isdigit():
                await update.message.reply_text("❌ Введи число. **Пример:** 50", parse_mode='Markdown')
                return
            
            target_value = int(text)
            if target_value <= 0:
                await update.message.reply_text("❌ Значение должно быть больше 0")
                return
            
            context.user_data["target_value"] = target_value
            context.user_data["state"] = "awaiting_deadline"
            
            text_msg = f"Целевое значение: {target_value}\n\nУстановить дедлайн?\n**Форматы:**\n• ДД.ММ.ГГ ЧЧ:ММ\n• ДД.ММ.ГГ\n• 'нет' - пропустить"
            await update.message.reply_text(text_msg, parse_mode='Markdown')
        
        # Создание квеста - ввод дедлайна
        elif state == "awaiting_deadline":
            deadline = None
            
            if text.lower() not in ["нет", "no", "skip"]:
                try:
                    text_normalized = text.replace('/', '.').replace('-', '.')
                    
                    if ' ' in text_normalized and ':' in text_normalized:
                        deadline_date = datetime.strptime(text_normalized, "%d.%m.%y %H:%M")
                    else:
                        deadline_date = datetime.strptime(text_normalized, "%d.%m.%y")
                    
                    if deadline_date < datetime.now():
                        await update.message.reply_text("❌ Нельзя установить прошедшую дату!")
                        return
                    
                    deadline = deadline_date.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    await update.message.reply_text("❌ Неверный формат даты!\n\n**Используй:** ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ", parse_mode='Markdown')
                    return
            
            context.user_data["deadline"] = deadline
            context.user_data["state"] = "awaiting_comment"
            
            text_msg = "Добавить комментарий?\n\n**Пример:** Важно выполнить утром\n\nИли напиши 'нет'"
            await update.message.reply_text(text_msg, parse_mode='Markdown')
        
        # Создание квеста - ввод комментария
        elif state == "awaiting_comment":
            comment = None
            
            if text.lower() not in ["нет", "no", "skip"]:
                is_valid, error_msg = db.validate_input(text, "Комментарий")
                if not is_valid:
                    await update.message.reply_text(f"❌ {error_msg}")
                    return
                comment = text
            
            quest_title = context.user_data.get("quest_title")
            quest_type = context.user_data.get("quest_type")
            target_value = context.user_data.get("target_value")
            deadline = context.user_data.get("deadline")
            
            quest_id, error = db.create_quest(
                user_id=user_id,
                title=quest_title,
                quest_type=quest_type,
                target_value=target_value,
                deadline=deadline,
                comment=comment
            )
            
            if error:
                await update.message.reply_text(f"❌ Ошибка: {error}", reply_markup=get_main_menu_keyboard())
                context.user_data.clear()
                return
            
            context.user_data.clear()
            
            success_text = f"🎉 Квест **{quest_title}** создан!\n\nНайди его в 'Мои квесты'"
            await update.message.reply_text(success_text, reply_markup=get_quests_menu_keyboard(), parse_mode='Markdown')
        
        # Обновление прогресса
        elif state == "awaiting_progress":
            if not text.isdigit():
                await update.message.reply_text("❌ Введи число")
                return
            
            new_value = int(text)
            quest_id = context.user_data.get("progress_quest_id")
            quest_type = context.user_data.get("quest_type")
            
            if quest_type in ["mental", "custom"]:
                if new_value < 0 or new_value > 100:
                    await update.message.reply_text("❌ Процент должен быть от 0 до 100")
                    return
            
            quest = db.update_quest_progress(user_id, quest_id, new_value)
            
            if quest:
                context.user_data.clear()
                await update.message.reply_text("✅ Прогресс обновлён!", reply_markup=get_quests_menu_keyboard())
            else:
                await update.message.reply_text("❌ Ошибка при обновлении")
        
        # Редактирование полей квеста
        elif state and state.startswith("editing_"):
            field = state.replace("editing_", "")
            quest_id = context.user_data.get("editing_quest_id")
            
            if field == "title":
                is_valid, error_msg = db.validate_input(text, "Название")
                if not is_valid:
                    await update.message.reply_text(f"❌ {error_msg}")
                    return
                
                result, error = db.update_quest(user_id, quest_id, title=text)
                if error:
                    await update.message.reply_text(f"❌ {error}")
                    return
                
                context.user_data.clear()
                await update.message.reply_text("✅ Название обновлено!", reply_markup=get_quests_menu_keyboard())
            
            elif field == "target":
                if not text.isdigit():
                    await update.message.reply_text("❌ Введи число")
                    return
                
                target_value = int(text)
                if target_value <= 0:
                    await update.message.reply_text("❌ Значение должно быть больше 0")
                    return
                
                result, error = db.update_quest(user_id, quest_id, target_value=target_value)
                if error:
                    await update.message.reply_text(f"❌ {error}")
                    return
                
                context.user_data.clear()
                await update.message.reply_text("✅ Целевое значение обновлено!", reply_markup=get_quests_menu_keyboard())
            
            elif field == "deadline":
                deadline = None
                
                if text.lower() not in ["нет", "no", "skip"]:
                    try:
                        text_normalized = text.replace('/', '.').replace('-', '.')
                        
                        if ' ' in text_normalized and ':' in text_normalized:
                            deadline_date = datetime.strptime(text_normalized, "%d.%m.%y %H:%M")
                        else:
                            deadline_date = datetime.strptime(text_normalized, "%d.%m.%y")
                        
                        if deadline_date < datetime.now():
                            await update.message.reply_text("❌ Нельзя установить прошедшую дату!")
                            return
                        
                        deadline = deadline_date.strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        await update.message.reply_text("❌ Неверный формат даты!")
                        return
                
                result, error = db.update_quest(user_id, quest_id, deadline=deadline)
                if error:
                    await update.message.reply_text(f"❌ {error}")
                    return
                
                context.user_data.clear()
                await update.message.reply_text("✅ Дедлайн обновлён!", reply_markup=get_quests_menu_keyboard())
            
            elif field == "comment":
                comment = None if text.lower() in ["нет", "no", "skip"] else text
                
                if comment:
                    is_valid, error_msg = db.validate_input(comment, "Комментарий")
                    if not is_valid:
                        await update.message.reply_text(f"❌ {error_msg}")
                        return
                
                result, error = db.update_quest(user_id, quest_id, comment=comment)
                if error:
                    await update.message.reply_text(f"❌ {error}")
                    return
                
                context.user_data.clear()
                await update.message.reply_text("✅ Комментарий обновлён!", reply_markup=get_quests_menu_keyboard())
        
        else:
            await update.message.reply_text("Используй кнопки меню для навигации", reply_markup=get_main_menu_keyboard())
    
    except Exception as e:
        logging.error(f"Ошибка в handle_text_message: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Возврат в главное меню.", reply_markup=get_main_menu_keyboard())
        context.user_data.clear()


# Обработчики callback-кнопок

async def handle_main_menu(query, context):
    context.user_data.clear()
    text = "Главное меню\n\nВыбери действие:"
    await query.edit_message_text(text, reply_markup=get_main_menu_keyboard())


async def handle_quests_menu(query, context):
    context.user_data.clear()
    text = "📋 **Квесты**\n\nВыбери действие:"
    await query.edit_message_text(text, reply_markup=get_quests_menu_keyboard(), parse_mode='Markdown')


async def handle_create_quest(query, context):
    context.user_data.clear()
    context.user_data["creating_quest"] = True
    
    text = "Выбери тип квеста:\n\n"
    text += "💪 **Физическая задача** - с количественным значением\n"
    text += "📚 **Интеллектуальная задача** - с количественным значением\n"
    text += "🧠 **Ментальная задача** - с процентом выполнения (0-100%)\n"
    text += "🎯 **Произвольная задача** - с процентом выполнения (0-100%)"
    
    await query.edit_message_text(text, reply_markup=get_quest_type_keyboard(), parse_mode='Markdown')


async def handle_quest_type_selection(query, context):
    quest_type = query.data.replace("type_", "")
    context.user_data["quest_type"] = quest_type
    context.user_data["state"] = "awaiting_title"
    
    type_name = QUEST_TYPES.get(quest_type, "Квест")
    
    text = f"Тип квеста: {type_name}\n\n"
    text += "Введи название квеста:\n\n"
    text += "**Примеры:**\n• Утренняя пробежка\n• Прочитать книгу"
    
    await query.edit_message_text(text, reply_markup=get_cancel_keyboard(), parse_mode='Markdown')


async def handle_my_quests(query, context):
    user_id = query.from_user.id
    quests = db.get_user_quests(user_id)
    
    if not quests:
        text = "📋 У тебя пока нет активных квестов!\n\nСоздай свой первый квест! 💪"
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="quests_menu")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    text = "📋 **Твои активные квесты:**\n\n"
    keyboard = []
    
    for quest in quests:
        quest_id = quest[0]
        title = quest[2]
        quest_type = quest[3]
        target_value = quest[4]
        current_value = quest[5]
        
        type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
        
        if quest_type in ["physical", "intellectual"]:
            progress = f"{current_value}/{target_value}"
        else:
            progress = f"{current_value}%"
        
        text += f"{type_emoji} {title} - {progress}\n"
        keyboard.append([InlineKeyboardButton(f"{type_emoji} {title}", callback_data=f"quest_{quest_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="quests_menu")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def handle_quest_detail(query, context):
    try:
        quest_id = int(query.data.split("_")[1])
    except:
        await query.answer("Ошибка: некорректный ID квеста")
        return
    
    user_id = query.from_user.id
    quest = db.get_quest(user_id, quest_id)
    
    if not quest:
        await query.edit_message_text("❌ Квест не найден", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 К списку квестов", callback_data="my_quests")]
        ]))
        return
    
    text = format_quest_text(quest)
    completed = quest[6]
    
    await query.edit_message_text(text, reply_markup=get_quest_detail_keyboard(quest_id, completed), parse_mode='Markdown')


async def handle_progress_update(query, context):
    try:
        quest_id = int(query.data.split("_")[1])
    except:
        await query.answer("Ошибка: некорректный ID квеста")
        return
    
    user_id = query.from_user.id
    quest = db.get_quest(user_id, quest_id)
    
    if not quest:
        await query.answer("Квест не найден")
        return
    
    quest_type = quest[3]
    target_value = quest[4]
    current_value = quest[5]
    
    context.user_data["state"] = "awaiting_progress"
    context.user_data["progress_quest_id"] = quest_id
    context.user_data["quest_type"] = quest_type
    
    if quest_type in ["physical", "intellectual"]:
        text = f"Текущий прогресс: {current_value}/{target_value}\n\nВведи новое значение:\n**Пример:** 25"
    else:
        text = f"Текущий прогресс: {current_value}%\n\nВведи процент (0-100):\n**Пример:** 75"
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data=f"quest_{quest_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def handle_complete_quest(query, context):
    try:
        quest_id = int(query.data.split("_")[1])
    except:
        await query.answer("Ошибка: некорректный ID квеста")
        return
    
    user_id = query.from_user.id
    quest = db.complete_quest(user_id, quest_id)
    
    if quest:
        await query.answer("🎉 Квест завершен!")
        await handle_quest_detail(query, context)
    else:
        await query.answer("Ошибка при завершении квеста")


async def handle_edit_quest(query, context):
    try:
        quest_id = int(query.data.split("_")[1])
    except:
        await query.answer("Ошибка: некорректный ID квеста")
        return
    
    user_id = query.from_user.id
    quest = db.get_quest(user_id, quest_id)
    
    if not quest:
        await query.answer("Квест не найден")
        return
    
    text = f"✏️ **Редактирование квеста**\n\n{quest[2]}\n\nЧто хочешь изменить?"
    await query.edit_message_text(text, reply_markup=get_edit_quest_keyboard(quest_id), parse_mode='Markdown')


async def handle_edit_field(query, context):
    parts = query.data.split("_")
    field = parts[1]
    quest_id = int(parts[2])
    
    user_id = query.from_user.id
    quest = db.get_quest(user_id, quest_id)
    
    if not quest:
        await query.answer("Квест не найден")
        return
    
    context.user_data["editing_quest_id"] = quest_id
    context.user_data["state"] = f"editing_{field}"
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data=f"edit_{quest_id}")]]
    
    if field == "title":
        text = "Введи новое название квеста:\n\n**Пример:** Вечерняя пробежка"
    elif field == "target":
        quest_type = quest[3]
        if quest_type in ["physical", "intellectual"]:
            text = "Введи новое целевое значение:\n\n**Пример:** 100"
        else:
            await query.answer("Для ментальных задач целевое значение всегда 100%")
            return
    elif field == "deadline":
        text = "Введи новый дедлайн:\n\n**Форматы:**\n• ДД.ММ.ГГ ЧЧ:ММ\n• ДД.ММ.ГГ\n• 'нет' - удалить"
    elif field == "comment":
        text = "Введи новый комментарий:\n\n**Пример:** Важно не забыть!"
    else:
        await query.answer("Неизвестное поле")
        return
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def handle_delete_quest(query, context):
    try:
        quest_id = int(query.data.split("_")[1])
    except:
        await query.answer("Ошибка: некорректный ID квеста")
        return
    
    user_id = query.from_user.id
    quest = db.get_quest(user_id, quest_id)
    
    if not quest:
        await query.answer("Квест не найден")
        return
    
    text = f"⚠️ Ты уверен, что хочешь удалить квест?\n\n**{quest[2]}**\n\nЭто действие нельзя отменить!"
    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{quest_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"quest_{quest_id}")]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def handle_confirm_delete(query, context):
    try:
        quest_id = int(query.data.split("_")[2])
    except:
        await query.answer("Ошибка: некорректный ID квеста")
        return
    
    user_id = query.from_user.id
    
    if db.delete_quest(user_id, quest_id):
        await query.answer("🗑️ Квест удалён")
        await handle_my_quests(query, context)
    else:
        await query.answer("Ошибка при удалении квеста")


async def handle_stats(query, context):
    text = "📊 **Статистика**\n\nРаздел в разработке 🚧"
    keyboard = [[InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def handle_help(query, context):
    text = "❓ **Помощь**\n\nРаздел в разработке 🚧"
    keyboard = [[InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def handle_cancel_creation(query, context):
    context.user_data.clear()
    await query.answer("Создание квеста отменено")
    await handle_quests_menu(query, context)



async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Главное меню
    if data == "main_menu":
        await handle_main_menu(query, context)
    elif data == "quests_menu":
        await handle_quests_menu(query, context)
    elif data == "create_quest":
        await handle_create_quest(query, context)
    elif data == "my_quests":
        await handle_my_quests(query, context)
    elif data == "stats":
        await handle_stats(query, context)
    elif data == "help":
        await handle_help(query, context)
    elif data == "cancel_creation":
        await handle_cancel_creation(query, context)
    
    # Типы квестов
    elif data.startswith("type_"):
        await handle_quest_type_selection(query, context)
    
    # Детали квеста
    elif data.startswith("quest_") and not data.startswith("quest_type"):
        await handle_quest_detail(query, context)
    
    # Обновление прогресса
    elif data.startswith("progress_"):
        await handle_progress_update(query, context)
    
    # Завершение квеста
    elif data.startswith("complete_"):
        await handle_complete_quest(query, context)
    
    # Редактирование
    elif data.startswith("edit_") and not data.startswith("edit_title") and not data.startswith("edit_target") and not data.startswith("edit_deadline") and not data.startswith("edit_comment"):
        await handle_edit_quest(query, context)
    elif data.startswith("edit_title_") or data.startswith("edit_target_") or data.startswith("edit_deadline_") or data.startswith("edit_comment_"):
        await handle_edit_field(query, context)
    
    # Удаление
    elif data.startswith("delete_"):
        await handle_delete_quest(query, context)
    elif data.startswith("confirm_delete_"):
        await handle_confirm_delete(query, context)
    
    else:
        await query.edit_message_text("Неизвестная команда")


def main():
    # Создаем приложение и передаем ему токен
    application = Application.builder().token(TOKEN).build()

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # Единый обработчик текстовых сообщений по состояниям
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Обработчик для INLINE-КНОПОК
    application.add_handler(CallbackQueryHandler(button_callback))

    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
