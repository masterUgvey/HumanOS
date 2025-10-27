"""
Обработчики команд и callback-кнопок для Telegram-бота
Содержит всю логику взаимодействия с пользователем
"""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from loguru import logger

from database_async import db
from ai_client import ai_client
from config import config

# Создаем роутер для обработчиков
router = Router()


# FSM States для управления состояниями диалога
class QuestCreation(StatesGroup):
    """Состояния создания квеста"""
    waiting_for_type = State()
    waiting_for_title = State()
    waiting_for_target = State()
    waiting_for_deadline = State()
    waiting_for_comment = State()


class QuestEdit(StatesGroup):
    """Состояния редактирования квеста"""
    waiting_for_title = State()
    waiting_for_target = State()
    waiting_for_deadline = State()
    waiting_for_comment = State()


class QuestProgress(StatesGroup):
    """Состояние обновления прогресса"""
    waiting_for_value = State()


class AIQuest(StatesGroup):
    """Состояние генерации квеста через AI"""
    waiting_for_goal = State()


# ============= КЛАВИАТУРЫ =============

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton(text="📋 Квесты", callback_data="quests_menu")],
        [InlineKeyboardButton(text="🤖 AI Квест", callback_data="ai_quest")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_quests_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню квестов"""
    keyboard = [
        [InlineKeyboardButton(text="➕ Добавить квест", callback_data="create_quest")],
        [InlineKeyboardButton(text="📝 Мои квесты", callback_data="my_quests")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_quest_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа квеста"""
    keyboard = [
        [InlineKeyboardButton(text="💪 Физическая задача", callback_data="type_physical")],
        [InlineKeyboardButton(text="📚 Интеллектуальная задача", callback_data="type_intellectual")],
        [InlineKeyboardButton(text="🧠 Ментальная задача", callback_data="type_mental")],
        [InlineKeyboardButton(text="🎯 Произвольная задача", callback_data="type_custom")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_quest_detail_keyboard(quest_id: int, completed: bool) -> InlineKeyboardMarkup:
    """Клавиатура деталей квеста"""
    keyboard = []
    if not completed:
        keyboard.append([InlineKeyboardButton(text="📈 Обновить прогресс", callback_data=f"progress_{quest_id}")])
        keyboard.append([InlineKeyboardButton(text="✅ Завершить", callback_data=f"complete_{quest_id}")])
    keyboard.append([InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{quest_id}")])
    keyboard.append([InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_{quest_id}")])
    keyboard.append([InlineKeyboardButton(text="🔙 К списку", callback_data="my_quests")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def format_quest_text(quest: tuple) -> str:
    """Форматирование текста квеста"""
    quest_id, user_id, title, quest_type, target_value, current_value, completed, deadline, comment, created_at = quest
    
    type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
    
    if quest_type in ["physical", "intellectual"]:
        progress_text = f"{current_value}/{target_value}"
    else:
        progress_text = f"{current_value}%"
    
    status = "✅ Завершен" if completed else "⏳ В процессе"
    
    text = f"{type_emoji} <b>{title}</b>\n\n"
    text += f"Тип: {config.QUEST_TYPES.get(quest_type, quest_type)}\n"
    text += f"Прогресс: {progress_text}\n"
    text += f"Статус: {status}\n"
    
    if deadline:
        try:
            d = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
            if d.hour != 0 or d.minute != 0:
                text += f"📅 Дедлайн: {d.strftime('%d.%m.%y %H:%M')}\n"
            else:
                text += f"📅 Дедлайн: {d.strftime('%d.%m.%y')}\n"
        except:
            pass
    
    if comment:
        text += f"\n💬 Комментарий: {comment}\n"
    
    return text


# ============= КОМАНДЫ =============

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()
    user = message.from_user
    await db.add_user(user.id, user.first_name or user.username or "User")
    
    welcome_text = f"""
Привет, {user.first_name}! 🚀

Я — твой проводник на пути к Сверхчеловеку. 
Вместе мы превратим рутину в увлекательную игру!

Выбери действие:
    """
    
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard())
    logger.info(f"👤 Пользователь {user.id} ({user.first_name}) запустил бота")


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = """
<b>📚 Доступные команды:</b>

/start - Начать работу с ботом
/help - Показать эту справку
/add_task - Быстро добавить задачу
/quest - Создать квест через AI
/progress - Посмотреть прогресс

<b>🎯 Типы квестов:</b>
💪 Физические - с количественным значением
📚 Интеллектуальные - с количественным значением
🧠 Ментальные - с процентом выполнения
🎯 Произвольные - с процентом выполнения

<b>🤖 AI Функции:</b>
Используй команду /quest или кнопку "AI Квест" для генерации квеста на основе твоей цели!
    """
    await message.answer(help_text, parse_mode="HTML")


@router.message(Command("add_task"))
async def cmd_add_task(message: Message, state: FSMContext):
    """Быстрое добавление задачи"""
    await state.set_state(QuestCreation.waiting_for_type)
    text = "Выбери тип квеста:"
    await message.answer(text, reply_markup=get_quest_type_keyboard())


@router.message(Command("quest"))
async def cmd_quest(message: Message, state: FSMContext):
    """Создание квеста через AI"""
    if not config.WINDSURF_API_KEY:
        await message.answer("⚠️ AI функция недоступна. Настройте WINDSURF_API_KEY в .env файле.")
        return
    
    await state.set_state(AIQuest.waiting_for_goal)
    text = """
🤖 <b>AI Генератор Квестов</b>

Опиши свою цель, и я создам для тебя персональный квест!

<b>Примеры:</b>
• Хочу похудеть на 5 кг
• Научиться программировать на Python
• Читать по книге в неделю
• Бегать каждое утро

Напиши свою цель:
    """
    await message.answer(text, parse_mode="HTML")


@router.message(Command("progress"))
async def cmd_progress(message: Message):
    """Показать прогресс по квестам"""
    user_id = message.from_user.id
    quests = await db.get_user_quests(user_id)
    
    if not quests:
        await message.answer("📋 У тебя пока нет активных квестов!")
        return
    
    text = "<b>📊 Твой прогресс:</b>\n\n"
    for quest in quests:
        quest_type = quest[3]
        title = quest[2]
        current = quest[5]
        target = quest[4]
        
        type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
        
        if quest_type in ["physical", "intellectual"]:
            progress_text = f"{current}/{target}"
            percent = (current / target * 100) if target > 0 else 0
        else:
            progress_text = f"{current}%"
            percent = current
        
        bar_length = 10
        filled = int(bar_length * percent / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        text += f"{type_emoji} {title}\n"
        text += f"[{bar}] {progress_text} ({percent:.0f}%)\n\n"
    
    await message.answer(text, parse_mode="HTML")


# ============= CALLBACK HANDLERS =============

@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery, state: FSMContext):
    """Главное меню"""
    await state.clear()
    text = "Главное меню\n\nВыбери действие:"
    await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "quests_menu")
async def callback_quests_menu(callback: CallbackQuery, state: FSMContext):
    """Меню квестов"""
    await state.clear()
    text = "📋 <b>Квесты</b>\n\nВыбери действие:"
    await callback.message.edit_text(text, reply_markup=get_quests_menu_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "create_quest")
async def callback_create_quest(callback: CallbackQuery, state: FSMContext):
    """Начало создания квеста"""
    # Гарантируем, что пользователь существует в БД перед созданием квеста
    await db.add_user(callback.from_user.id, callback.from_user.first_name or callback.from_user.username or "User")
    await state.set_state(QuestCreation.waiting_for_type)
    text = "Выбери тип квеста:"
    await callback.message.edit_text(text, reply_markup=get_quest_type_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("type_"))
async def callback_quest_type(callback: CallbackQuery, state: FSMContext):
    """Выбор типа квеста"""
    quest_type = callback.data.replace("type_", "")
    await state.update_data(quest_type=quest_type)
    await state.set_state(QuestCreation.waiting_for_title)
    
    type_name = config.QUEST_TYPES.get(quest_type, "Квест")
    text = f"Тип квеста: {type_name}\n\nВведи название квеста:"
    await callback.message.edit_text(text)
    await callback.answer()


@router.message(QuestCreation.waiting_for_title)
async def process_quest_title(message: Message, state: FSMContext):
    """Обработка названия квеста"""
    title = message.text.strip()
    
    is_valid, error_msg = db.validate_input(title, "Название")
    if not is_valid:
        await message.answer(f"❌ {error_msg}\n\nПопробуй ещё раз:")
        return
    
    data = await state.get_data()
    quest_type = data.get("quest_type")
    
    await state.update_data(title=title)
    
    if quest_type in ["mental", "custom"]:
        await state.update_data(target_value=100)
        await state.set_state(QuestCreation.waiting_for_deadline)
        text = f"Название: {title}\n\nУстановить дедлайн?\nФорматы: ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ\nИли напиши 'нет'"
    else:
        await state.set_state(QuestCreation.waiting_for_target)
        text = f"Название: {title}\n\nВведи целевое значение (число):"
    
    await message.answer(text)


@router.message(QuestCreation.waiting_for_target)
async def process_quest_target(message: Message, state: FSMContext):
    """Обработка целевого значения"""
    if not message.text.isdigit():
        await message.answer("❌ Введи число!")
        return
    
    target_value = int(message.text)
    if target_value <= 0:
        await message.answer("❌ Значение должно быть больше 0!")
        return
    
    await state.update_data(target_value=target_value)
    await state.set_state(QuestCreation.waiting_for_deadline)
    text = f"Целевое значение: {target_value}\n\nУстановить дедлайн?\nФорматы: ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ\nИли напиши 'нет'"
    await message.answer(text)


@router.message(QuestCreation.waiting_for_deadline)
async def process_quest_deadline(message: Message, state: FSMContext):
    """Обработка дедлайна"""
    text = message.text.strip()
    deadline = None
    
    if text.lower() not in ["нет", "no", "skip"]:
        try:
            text_normalized = text.replace('/', '.').replace('-', '.')
            if ' ' in text_normalized and ':' in text_normalized:
                deadline_date = datetime.strptime(text_normalized, "%d.%m.%y %H:%M")
            else:
                deadline_date = datetime.strptime(text_normalized, "%d.%m.%y")
            
            if deadline_date < datetime.now():
                await message.answer("❌ Нельзя установить прошедшую дату!")
                return
            
            deadline = deadline_date.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            await message.answer("❌ Неверный формат даты!\nИспользуй: ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ")
            return
    
    await state.update_data(deadline=deadline)
    await state.set_state(QuestCreation.waiting_for_comment)
    await message.answer("Добавить комментарий?\nИли напиши 'нет'")


@router.message(QuestCreation.waiting_for_comment)
async def process_quest_comment(message: Message, state: FSMContext):
    """Обработка комментария и создание квеста"""
    text = message.text.strip()
    comment = None
    
    if text.lower() not in ["нет", "no", "skip"]:
        is_valid, error_msg = db.validate_input(text, "Комментарий")
        if not is_valid:
            await message.answer(f"❌ {error_msg}")
            return
        comment = text
    
    # Гарантируем, что пользователь существует в БД перед созданием квеста
    await db.add_user(message.from_user.id, message.from_user.first_name or message.from_user.username or "User")

    data = await state.get_data()
    quest_id, error = await db.create_quest(
        user_id=message.from_user.id,
        title=data["title"],
        quest_type=data["quest_type"],
        target_value=data["target_value"],
        deadline=data.get("deadline"),
        comment=comment
    )
    
    if error:
        await state.clear()
        await message.answer(
            f"❌ Ошибка: {error}",
            reply_markup=get_quests_menu_keyboard()
        )
        return
    else:
        await message.answer(
            f"🎉 Квест <b>{data['title']}</b> создан!\n\nНайди его в 'Мои квесты'",
            reply_markup=get_quests_menu_keyboard(),
            parse_mode="HTML"
        )
    
    await state.clear()


@router.callback_query(F.data == "my_quests")
async def callback_my_quests(callback: CallbackQuery):
    """Список квестов пользователя"""
    user_id = callback.from_user.id
    quests = await db.get_user_quests(user_id)
    
    if not quests:
        text = "📋 У тебя пока нет активных квестов!\n\nСоздай свой первый квест! 💪"
        keyboard = [
            [InlineKeyboardButton(text="➕ Создать квест", callback_data="create_quest")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="quests_menu")]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        await callback.answer()
        return
    
    text = "📋 <b>Твои активные квесты:</b>\n\n"
    keyboard = []
    
    for quest in quests:
        quest_id = quest[0]
        title = quest[2]
        quest_type = quest[3]
        type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
        keyboard.append([InlineKeyboardButton(text=f"{type_emoji} {title}", callback_data=f"quest_{quest_id}")])
    
    keyboard.append([InlineKeyboardButton(text="➕ Создать квест", callback_data="create_quest")])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="quests_menu")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("quest_"))
async def callback_quest_detail(callback: CallbackQuery):
    """Детали квеста"""
    try:
        quest_id = int(callback.data.split("_")[1])
    except:
        await callback.answer("Ошибка: некорректный ID")
        return
    
    quest = await db.get_quest(callback.from_user.id, quest_id)
    if not quest:
        await callback.answer("❌ Квест не найден")
        return
    
    text = format_quest_text(quest)
    completed = quest[6]
    await callback.message.edit_text(text, reply_markup=get_quest_detail_keyboard(quest_id, completed), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("complete_"))
async def callback_complete_quest(callback: CallbackQuery):
    """Завершение квеста"""
    try:
        quest_id = int(callback.data.split("_")[1])
    except:
        await callback.answer("Ошибка")
        return
    
    quest = await db.complete_quest(callback.from_user.id, quest_id)
    if quest:
        await callback.answer("🎉 Квест завершен!")
        text = format_quest_text(quest)
        await callback.message.edit_text(text, reply_markup=get_quest_detail_keyboard(quest_id, True), parse_mode="HTML")
    else:
        await callback.answer("❌ Ошибка")


@router.callback_query(F.data == "ai_quest")
async def callback_ai_quest(callback: CallbackQuery, state: FSMContext):
    """AI генерация квеста"""
    if not config.WINDSURF_API_KEY:
        await callback.answer("⚠️ AI функция недоступна", show_alert=True)
        return
    
    await state.set_state(AIQuest.waiting_for_goal)
    text = """
🤖 <b>AI Генератор Квестов</b>

Опиши свою цель, и я создам персональный квест!

<b>Примеры:</b>
• Хочу похудеть на 5 кг
• Научиться программировать
• Читать больше книг

Напиши свою цель:
    """
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


@router.message(AIQuest.waiting_for_goal)
async def process_ai_goal(message: Message, state: FSMContext):
    """Обработка цели для AI"""
    goal = message.text.strip()
    
    await message.answer("🤖 Генерирую квест... Подожди немного...")
    
    quest_data = await ai_client.generate_quest(goal)
    
    if not quest_data:
        await message.answer("❌ Не удалось сгенерировать квест. Попробуй позже или создай квест вручную.")
        await state.clear()
        return
    
    # Создаем квест из данных AI
    quest_id, error = await db.create_quest(
        user_id=message.from_user.id,
        title=quest_data.get("title", "AI Квест"),
        quest_type=quest_data.get("quest_type", "custom"),
        target_value=quest_data.get("target_value", 100),
        comment=quest_data.get("description", "")
    )
    
    if error:
        await message.answer(f"❌ Ошибка: {error}")
    else:
        response = f"🎉 <b>Квест создан!</b>\n\n"
        response += f"📝 {quest_data.get('title')}\n\n"
        response += f"💡 {quest_data.get('description')}\n\n"
        
        if "tips" in quest_data and quest_data["tips"]:
            response += "<b>Советы:</b>\n"
            for tip in quest_data["tips"][:3]:
                response += f"• {tip}\n"
        
        await message.answer(response, reply_markup=get_quests_menu_keyboard(), parse_mode="HTML")
    
    await state.clear()


@router.callback_query(F.data == "stats")
async def callback_stats(callback: CallbackQuery):
    """Статистика"""
    text = "📊 <b>Статистика</b>\n\nРаздел в разработке 🚧"
    keyboard = [[InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "help")
async def callback_help(callback: CallbackQuery):
    """Помощь"""
    text = """
<b>📚 Помощь</b>

<b>Команды:</b>
/start - Главное меню
/help - Справка
/add_task - Добавить задачу
/quest - AI генератор
/progress - Прогресс

<b>Типы квестов:</b>
💪 Физические
📚 Интеллектуальные
🧠 Ментальные
🎯 Произвольные
    """
    keyboard = [[InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена действия"""
    await state.clear()
    await callback.answer("Отменено")
    await callback_main_menu(callback, state)
