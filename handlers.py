"""
Обработчики команд и callback-кнопок для Telegram-бота
Содержит всю логику взаимодействия с пользователем
"""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from datetime_utils import (
    today_deadline_str,
    normalize_user_deadline_input,
    comment_should_be_saved,
    format_deadline_for_display,
)
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
    waiting_for_reps = State()
    waiting_for_sets = State()
    waiting_for_pages = State()
    waiting_for_minutes = State()
    waiting_for_progress = State()
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

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню (ReplyKeyboard)"""
    keyboard = [
        [KeyboardButton(text="📋 Мои квесты"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="❓ Помощь"), KeyboardButton(text="➕ Создать квест")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=False)


def get_quests_menu_keyboard() -> ReplyKeyboardMarkup:
    """Меню квестов (ReplyKeyboard)"""
    keyboard = [
        [KeyboardButton(text="📋 Список квестов")],
        [KeyboardButton(text="➕ Создать квест")],
        [KeyboardButton(text="🔙 Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=False)


def get_quest_type_keyboard() -> ReplyKeyboardMarkup:
    """Меню создания квеста (ReplyKeyboard)"""
    keyboard = [
        [KeyboardButton(text="💪 Физические упражнения"), KeyboardButton(text="📚 Чтение")],
        [KeyboardButton(text="🧠 Медитация"), KeyboardButton(text="🎯 Произвольный квест")],
        [KeyboardButton(text="🔙 Отмена")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=False)


def get_quest_detail_keyboard(quest_id: int, completed: bool, quest_type: str) -> InlineKeyboardMarkup:
    keyboard = []
    if not completed:
        keyboard.append([InlineKeyboardButton(text="📈 Обновить прогресс", callback_data=f"progress_{quest_id}")])
        keyboard.append([InlineKeyboardButton(text="✅ Завершить", callback_data=f"complete_{quest_id}")])
    keyboard.append([InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{quest_id}")])
    if quest_type == "mental":
        keyboard.append([InlineKeyboardButton(text="▶️ Начать медитацию", callback_data=f"meditate_{quest_id}")])
    keyboard.append([InlineKeyboardButton(text="🔙 К списку", callback_data="my_quests_inline")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def format_quest_text(quest: tuple) -> str:
    """Форматирование текста квеста"""
    quest_id, user_id, title, quest_type, target_value, current_value, completed, deadline, comment, created_at = quest
    
    type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
    
    if quest_type in ["physical", "intellectual", "mental"]:
        progress_text = f"{current_value}/{target_value}"
    else:
        progress_text = f"{current_value}%"
    
    status = "✅ Завершен" if completed else "⏳ В процессе"
    
    text = f"{type_emoji} <b>{title}</b>\nID: {quest_id}\n\n"
    text += f"Тип: {config.QUEST_TYPES.get(quest_type, quest_type)}\n"
    text += f"Прогресс: {progress_text}\n"
    text += f"Статус: {status}\n"
    
    text += f"📅 Дедлайн: {format_deadline_for_display(deadline)}\n"
    
    if comment and comment_should_be_saved(str(comment), deadline):
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


@router.message(Command("sanitize"))
async def cmd_sanitize(message: Message):
    """Админ-команда: привести БД в порядок (чистка комментариев и нормализация дедлайнов)"""
    user_id = message.from_user.id
    logger.info(f"[SANITIZE] requested by {user_id}")
    await message.answer("🧹 Запускаю чистку БД... это может занять несколько секунд")
    try:
        await db.sanitize_existing_data()
        await message.answer("✅ Чистка завершена. Проверь квесты.")
    except Exception as e:
        logger.error(f"[SANITIZE] failed: {e}")
        await message.answer("❌ Ошибка при чистке БД")


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

@router.message(F.text == "🔙 Назад")
async def go_back_to_main(message: Message, state: FSMContext):
    """Контекстный переход назад"""
    cur = await state.get_state()
    if cur in {
        QuestCreation.waiting_for_type.state,
        QuestCreation.waiting_for_title.state,
        QuestCreation.waiting_for_target.state,
        QuestCreation.waiting_for_reps.state,
        QuestCreation.waiting_for_sets.state,
        QuestCreation.waiting_for_pages.state,
        QuestCreation.waiting_for_minutes.state,
        QuestCreation.waiting_for_progress.state,
        QuestCreation.waiting_for_deadline.state,
        QuestCreation.waiting_for_comment.state,
        QuestEdit.waiting_for_title.state,
        QuestEdit.waiting_for_target.state,
        QuestEdit.waiting_for_deadline.state,
        QuestEdit.waiting_for_comment.state,
        QuestProgress.waiting_for_value.state,
    }:
        await state.clear()
        await message.answer("📋 Квесты\n\nВыбери действие:", reply_markup=get_quests_menu_keyboard())
    else:
        await state.clear()
        await message.answer("Главное меню\n\nВыбери действие:", reply_markup=get_main_menu_keyboard())


@router.message(F.text == "📋 Мои квесты")
async def menu_my_quests(message: Message, state: FSMContext):
    """Сразу показываем inline-список квестов без промежуточного меню"""
    await state.clear()
    user_id = message.from_user.id
    quests = await db.get_user_quests(user_id)
    if not quests:
        await message.answer("📋 У тебя пока нет активных квестов!")
        return
    keyboard = []
    now = datetime.now()
    for quest in quests:
        quest_id = quest[0]
        title = quest[2]
        quest_type = quest[3]
        deadline = quest[7]
        # Рассчитываем статус по дедлайну
        status_emoji = "⚪"
        if deadline:
            try:
                d = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
                # Если время 00:00, считаем как 23:00 этого дня
                if d.hour == 0 and d.minute == 0:
                    d = d.replace(hour=23, minute=0)
                if now > d:
                    status_emoji = "🔴"
                else:
                    seconds_left = (d - now).total_seconds()
                    if seconds_left <= 3600:
                        status_emoji = "🟡"
            except Exception:
                pass
        type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
        keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {title}", callback_data=f"quest_{quest_id}")])
    await message.answer("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.message(F.text == "➕ Создать квест")
async def menu_create_quest(message: Message, state: FSMContext):
    """Начало создания квеста (выбор типа)"""
    await state.set_state(QuestCreation.waiting_for_type)
    await message.answer("Выбери тип квеста:", reply_markup=get_quest_type_keyboard())


@router.message(F.text.in_( [
    "💪 Физические упражнения",
    "📚 Чтение",
    "🧠 Медитация",
    "🎯 Произвольный квест",
]))
async def select_quest_type(message: Message, state: FSMContext):
    mapping = {
        "💪 Физические упражнения": "physical",
        "📚 Чтение": "intellectual",
        "🧠 Медитация": "mental",
        "🎯 Произвольный квест": "custom",
    }
    quest_type = mapping.get(message.text)
    await state.update_data(quest_type=quest_type)
    await state.set_state(QuestCreation.waiting_for_title)
    type_name = config.QUEST_TYPES.get(quest_type, "Квест")
    await message.answer(f"Тип квеста: {type_name}\n\nВведи название квеста:", reply_markup=ReplyKeyboardRemove())


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
    
    if quest_type == "physical":
        await state.set_state(QuestCreation.waiting_for_reps)
        text = f"Название: {title}\n\nВведи количество повторений в одном подходе (число):"
    elif quest_type == "intellectual":
        await state.set_state(QuestCreation.waiting_for_pages)
        text = f"Название: {title}\n\nВведи количество страниц (число):"
    elif quest_type == "mental":
        await state.set_state(QuestCreation.waiting_for_minutes)
        text = f"Название: {title}\n\nСколько минут медитации? (число):"
    elif quest_type == "custom":
        await state.set_state(QuestCreation.waiting_for_progress)
        text = f"Название: {title}\n\nУ квеста есть прогресс?"
        keyboard = [[
            InlineKeyboardButton(text="Да", callback_data="custom_progress_yes"),
            InlineKeyboardButton(text="Нет", callback_data="custom_progress_no")
        ]]
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        return
    
    await message.answer(text, reply_markup=ReplyKeyboardRemove())

@router.message(QuestCreation.waiting_for_reps)
async def process_reps(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введи число")
        return
    reps = int(message.text)
    if reps <= 0:
        await message.answer("❌ Значение должно быть больше 0")
        return
    await state.update_data(reps=reps)
    await state.set_state(QuestCreation.waiting_for_sets)
    await message.answer("Введи количество подходов (число):")

@router.message(QuestCreation.waiting_for_sets)
async def process_sets(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введи число")
        return
    sets = int(message.text)
    if sets <= 0:
        await message.answer("❌ Значение должно быть больше 0")
        return
    data = await state.get_data()
    reps = data.get("reps", 0)
    target_value = reps * sets
    await state.update_data(target_value=target_value)
    await state.set_state(QuestCreation.waiting_for_deadline)
    keyboard = [[
        InlineKeyboardButton(text="Пропустить", callback_data="skip_deadline"),
        InlineKeyboardButton(text="Сегодня", callback_data="set_deadline_today")
    ]]
    await message.answer(
        "Укажи дедлайн в формате: ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.message(QuestCreation.waiting_for_pages)
async def process_pages(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введи число")
        return
    pages = int(message.text)
    if pages <= 0:
        await message.answer("❌ Значение должно быть больше 0")
        return
    await state.update_data(target_value=pages)
    await state.set_state(QuestCreation.waiting_for_deadline)
    keyboard = [[
        InlineKeyboardButton(text="Пропустить", callback_data="skip_deadline"),
        InlineKeyboardButton(text="Сегодня", callback_data="set_deadline_today")
    ]]
    await message.answer(
        "Укажи дедлайн в формате: ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.message(QuestCreation.waiting_for_minutes)
async def process_minutes(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введи число")
        return
    minutes = int(message.text)
    if minutes <= 0:
        await message.answer("❌ Значение должно быть больше 0")
        return
    await state.update_data(target_value=minutes)
    await state.set_state(QuestCreation.waiting_for_deadline)
    keyboard = [[
        InlineKeyboardButton(text="Пропустить", callback_data="skip_deadline"),
        InlineKeyboardButton(text="Сегодня", callback_data="set_deadline_today")
    ]]
    await message.answer(
        "Укажи дедлайн в формате: ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.in_(["custom_progress_yes", "custom_progress_no"]))
async def cb_custom_progress(callback: CallbackQuery, state: FSMContext):
    done = callback.data.endswith("yes")
    await state.update_data(target_value=1, custom_initial_done=done)
    # Переход к дедлайну: инструкция + Пропустить
    await state.set_state(QuestCreation.waiting_for_deadline)
    keyboard = [[
        InlineKeyboardButton(text="Пропустить", callback_data="skip_deadline"),
        InlineKeyboardButton(text="Сегодня", callback_data="set_deadline_today")
    ]]
    await callback.message.edit_text(
        "Укажи дедлайн в формате: ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


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
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_deadline")]]
    await message.answer(
        "Укажи дедлайн в формате: ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data == "skip_deadline")
async def cb_skip_deadline(callback: CallbackQuery, state: FSMContext):
    await state.update_data(deadline=None)
    # Переходим к комментарию: текст + Пропустить
    await state.set_state(QuestCreation.waiting_for_comment)
    data = await state.get_data()
    logger.info(f"[CREATE] skip_deadline by {callback.from_user.id} -> state: {data}")
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    await callback.message.edit_text(
        "Добавьте комментарий (введите текст сообщением)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@router.callback_query(F.data == "set_deadline_today")
async def cb_set_deadline_today(callback: CallbackQuery, state: FSMContext):
    # Установить текущую локальную дату как 00:00:00 (YYYY-MM-DD 00:00:00) и перейти к комментарию
    today_str = today_deadline_str()
    await state.update_data(deadline=today_str)
    data = await state.get_data()
    logger.info(f"[CREATE] set_deadline_today by {callback.from_user.id} -> deadline: {today_str}, state: {data}")
    await state.set_state(QuestCreation.waiting_for_comment)
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    await callback.message.edit_text(
        "Добавьте комментарий (введите текст сообщением)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@router.message(QuestCreation.waiting_for_deadline)
async def process_quest_deadline(message: Message, state: FSMContext):
    """Ввод даты дедлайна после выбора Да"""
    text = message.text.strip()
    try:
        deadline = normalize_user_deadline_input(text)
        logger.info(f"[CREATE] parse_deadline by {message.from_user.id} -> input: '{text}', normalized: '{deadline}'")
    except ValueError:
        await message.answer("❌ Неверный формат даты!\nИспользуй: ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ")
        return
    await state.update_data(deadline=deadline)
    # Переход к комментарию: текст + Пропустить
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    await state.set_state(QuestCreation.waiting_for_comment)
    await message.answer(
        "Добавьте комментарий (введите текст сообщением)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data == "skip_comment")
async def cb_skip_comment(callback: CallbackQuery, state: FSMContext):
    # Создаем квест без комментария
    user = callback.from_user
    await db.add_user(user.id, user.first_name or user.username or "User")
    data = await state.get_data()
    logger.info(f"[CREATE] skip_comment by {user.id} -> creating with: title='{data.get('title')}', quest_type='{data.get('quest_type')}', target='{data.get('target_value')}', deadline='{data.get('deadline')}', comment=None")
    quest_id, error = await db.create_quest(
        user_id=user.id,
        title=data["title"],
        quest_type=data["quest_type"],
        target_value=data["target_value"],
        deadline=data.get("deadline"),
        comment=None
    )
    if error:
        await state.clear()
        await callback.message.edit_text(f"❌ Ошибка: {error}")
    else:
        if data.get("quest_type") == "custom" and data.get("custom_initial_done") and quest_id:
            await db.update_quest_progress(user.id, quest_id, 1)
        await state.clear()
        # Показать список квестов (inline) без кнопки создания
        quests = await db.get_user_quests(user.id)
        if not quests:
            await callback.message.edit_text("📋 У тебя пока нет активных квестов!")
        else:
            keyboard = []
            now = datetime.now()
            for q in quests:
                q_id = q[0]
                q_title = q[2]
                q_type = q[3]
                q_deadline = q[7]
                status_emoji = "⚪"
                if q_deadline:
                    try:
                        d = datetime.strptime(q_deadline, "%Y-%m-%d %H:%M:%S")
                        if d.hour == 0 and d.minute == 0:
                            d = d.replace(hour=23, minute=0)
                        if now > d:
                            status_emoji = "🔴"
                        else:
                            if (d - now).total_seconds() <= 3600:
                                status_emoji = "🟡"
                    except Exception:
                        pass
                type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(q_type, "🎯")
                keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {q_title}", callback_data=f"quest_{q_id}")])
            await callback.message.edit_text("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.message(QuestCreation.waiting_for_comment)
async def process_quest_comment(message: Message, state: FSMContext):
    """Обработка комментария (текст) и создание квеста"""
    text = message.text.strip()
    data = await state.get_data()
    deadline_in_state = data.get("deadline")
    comment = text if comment_should_be_saved(text, deadline_in_state) else None
    if comment:
        is_valid, error_msg = db.validate_input(comment, "Комментарий")
        if not is_valid:
            await message.answer(f"❌ {error_msg}")
            return
    logger.info(f"[CREATE] comment by {message.from_user.id} -> raw='{text}', saved='{comment}', deadline_in_state='{deadline_in_state}'")
    # Гарантируем, что пользователь существует в БД
    await db.add_user(message.from_user.id, message.from_user.first_name or message.from_user.username or "User")

    quest_id, error = await db.create_quest(
        user_id=message.from_user.id,
        title=data["title"],
        quest_type=data["quest_type"],
        target_value=data["target_value"],
        deadline=data.get("deadline"),
        comment=comment
    )
    logger.info(f"[CREATE] create_quest requested by {message.from_user.id} -> title='{data.get('title')}', type='{data.get('quest_type')}', target='{data.get('target_value')}', deadline='{data.get('deadline')}', comment='{comment}', result_id='{quest_id}', error='{error}'")
    
    if error:
        await state.clear()
        await message.answer(
            f"❌ Ошибка: {error}",
            reply_markup=get_quests_menu_keyboard()
        )
        return
    else:
        if data.get("quest_type") == "custom" and data.get("custom_initial_done") and quest_id:
            await db.update_quest_progress(message.from_user.id, quest_id, 1)
        await state.clear()
        # Показать список квестов (inline)
        user_id = message.from_user.id
        quests = await db.get_user_quests(user_id)
        if not quests:
            await message.answer("📋 У тебя пока нет активных квестов!")
        else:
            keyboard = []
            now = datetime.now()
            for q in quests:
                q_id = q[0]
                q_title = q[2]
                q_type = q[3]
                q_deadline = q[7]
                status_emoji = "⚪"
                if q_deadline:
                    try:
                        d = datetime.strptime(q_deadline, "%Y-%m-%d %H:%M:%S")
                        if d.hour == 0 and d.minute == 0:
                            d = d.replace(hour=23, minute=0)
                        if now > d:
                            status_emoji = "🔴"
                        else:
                            if (d - now).total_seconds() <= 3600:
                                status_emoji = "🟡"
                    except Exception:
                        pass
                type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(q_type, "🎯")
                keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {q_title}", callback_data=f"quest_{q_id}")])
            await message.answer("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.message(F.text == "📋 Список квестов")
async def show_my_quests(message: Message):
    """Список квестов пользователя (только кнопки)"""
    user_id = message.from_user.id
    quests = await db.get_user_quests(user_id)
    if not quests:
        await message.answer("📋 У тебя пока нет активных квестов!")
        return
    keyboard = []
    now = datetime.now()
    for quest in quests:
        quest_id = quest[0]
        title = quest[2]
        quest_type = quest[3]
        deadline = quest[7]
        status_emoji = "⚪"
        if deadline:
            try:
                d = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
                if d.hour == 0 and d.minute == 0:
                    d = d.replace(hour=23, minute=0)
                if now > d:
                    status_emoji = "🔴"
                else:
                    if (d - now).total_seconds() <= 3600:
                        status_emoji = "🟡"
            except Exception:
                pass
        type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
        keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {title}", callback_data=f"quest_{quest_id}")])
    await message.answer("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


class QuestAction(StatesGroup):
    selecting_for_complete = State()
    selecting_for_detail = State()

@router.callback_query(F.data == "my_quests_inline")
async def cb_my_quests(callback: CallbackQuery):
    user_id = callback.from_user.id
    quests = await db.get_user_quests(user_id)
    if not quests:
        keyboard = [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]
        await callback.message.edit_text("📋 У тебя пока нет активных квестов!", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        await callback.answer()
        return
    keyboard = []
    now = datetime.now()
    for quest in quests:
        quest_id = quest[0]
        title = quest[2]
        quest_type = quest[3]
        deadline = quest[7]
        status_emoji = "⚪"
        if deadline:
            try:
                d = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
                if d.hour == 0 and d.minute == 0:
                    d = d.replace(hour=23, minute=0)
                if now > d:
                    status_emoji = "🔴"
                else:
                    if (d - now).total_seconds() <= 3600:
                        status_emoji = "🟡"
            except Exception:
                pass
        type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
        keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {title}", callback_data=f"quest_{quest_id}")])
    await callback.message.edit_text("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.callback_query(F.data.startswith("quest_"))
async def cb_quest_detail(callback: CallbackQuery):
    try:
        quest_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    user_id = callback.from_user.id
    quest = await db.get_quest(user_id, quest_id)
    if not quest:
        await callback.answer("Квест не найден")
        return
    logger.info(f"[DETAIL] open quest_id={quest_id} data={quest}")
    text = format_quest_text(quest)
    completed = bool(quest[6])
    quest_type = quest[3]
    await callback.message.edit_text(text, reply_markup=get_quest_detail_keyboard(quest_id, completed, quest_type), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("progress_"))
async def cb_progress(callback: CallbackQuery, state: FSMContext):
    try:
        quest_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    user_id = callback.from_user.id
    quest = await db.get_quest(user_id, quest_id)
    if not quest:
        await callback.answer("Квест не найден")
        return
    quest_type = quest[3]
    target_value = quest[4]
    current_value = quest[5]
    await state.set_state(QuestProgress.waiting_for_value)
    await state.update_data(progress_quest_id=quest_id, quest_type=quest_type)
    if quest_type in ["physical", "intellectual", "mental"]:
        text = f"Текущий прогресс: {current_value}/{target_value}\n\nВведи новое значение:"
    else:
        text = f"Текущий статус: {'выполнено' if current_value >= 1 else 'не выполнено'}\n\nОтметить как выполнено? (да/нет):"
    keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data=f"quest_{quest_id}")]]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.message(QuestProgress.waiting_for_value)
async def process_progress_value(message: Message, state: FSMContext):
    data = await state.get_data()
    quest_id = data.get("progress_quest_id")
    quest_type = data.get("quest_type")
    if quest_type == "custom":
        text = message.text.strip().lower()
        new_value = 1 if text in ["да", "yes", "+", "y"] else 0
    else:
        if not message.text.isdigit():
            await message.answer("❌ Введи число")
            return
        new_value = int(message.text)
        # Для percent-типов больше не используется, но на всякий случай ограничим отрицательные числа
        if new_value < 0:
            await message.answer("❌ Значение не может быть отрицательным")
            return
    quest = await db.update_quest_progress(message.from_user.id, quest_id, new_value)
    await state.clear()
    if quest:
        await message.answer("✅ Прогресс обновлён", reply_markup=get_quests_menu_keyboard())
    else:
        await message.answer("❌ Ошибка при обновлении", reply_markup=get_quests_menu_keyboard())

@router.callback_query(F.data.startswith("complete_"))
async def cb_complete(callback: CallbackQuery):
    try:
        quest_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    user_id = callback.from_user.id
    quest = await db.complete_quest(user_id, quest_id)
    if quest:
        await callback.answer("🎉 Готово")
        await cb_quest_detail(callback)
    else:
        await callback.answer("Ошибка завершения")

@router.callback_query(F.data.startswith("edit_"))
async def cb_edit_menu(callback: CallbackQuery):
    try:
        quest_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    keyboard = [
        [InlineKeyboardButton(text="📝 Название", callback_data=f"edit_title_{quest_id}")],
        [InlineKeyboardButton(text="🎯 Цель", callback_data=f"edit_target_{quest_id}")],
        [InlineKeyboardButton(text="📅 Дедлайн", callback_data=f"edit_deadline_{quest_id}")],
        [InlineKeyboardButton(text="💬 Комментарий", callback_data=f"edit_comment_{quest_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"quest_{quest_id}")],
    ]
    await callback.message.edit_text("Что изменить?", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.callback_query(F.data.startswith("edit_title_"))
async def cb_edit_title(callback: CallbackQuery, state: FSMContext):
    quest_id = int(callback.data.split("_")[2])
    await state.set_state(QuestEdit.waiting_for_title)
    await state.update_data(edit_quest_id=quest_id)
    keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data=f"quest_{quest_id}")]]
    await callback.message.edit_text("Введи новое название:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.message(QuestEdit.waiting_for_title)
async def process_edit_title(message: Message, state: FSMContext):
    text = message.text.strip()
    is_valid, error_msg = db.validate_input(text, "Название")
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    data = await state.get_data()
    quest_id = data.get("edit_quest_id")
    _, error = await db.update_quest(message.from_user.id, quest_id, title=text)
    await state.clear()
    if error:
        await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
    else:
        await message.answer("✅ Название обновлено", reply_markup=get_quests_menu_keyboard())

@router.callback_query(F.data.startswith("edit_target_"))
async def cb_edit_target(callback: CallbackQuery, state: FSMContext):
    quest_id = int(callback.data.split("_")[2])
    await state.set_state(QuestEdit.waiting_for_target)
    await state.update_data(edit_quest_id=quest_id)
    keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data=f"quest_{quest_id}")]]
    await callback.message.edit_text("Введи новое целевое значение:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.message(QuestEdit.waiting_for_target)
async def process_edit_target(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введи число")
        return
    value = int(message.text)
    if value <= 0:
        await message.answer("❌ Значение должно быть больше 0")
        return
    data = await state.get_data()
    quest_id = data.get("edit_quest_id")
    _, error = await db.update_quest(message.from_user.id, quest_id, target_value=value)
    await state.clear()
    if error:
        await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
    else:
        await message.answer("✅ Цель обновлена", reply_markup=get_quests_menu_keyboard())

@router.callback_query(F.data.startswith("edit_deadline_"))
async def cb_edit_deadline(callback: CallbackQuery, state: FSMContext):
    quest_id = int(callback.data.split("_")[2])
    await state.set_state(QuestEdit.waiting_for_deadline)
    await state.update_data(edit_quest_id=quest_id)
    keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data=f"quest_{quest_id}")]]
    await callback.message.edit_text("Введи новый дедлайн (ДД.ММ.ГГ или ДД.ММ.ГГ ЧЧ:ММ) или 'нет':", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.message(QuestEdit.waiting_for_deadline)
async def process_edit_deadline(message: Message, state: FSMContext):
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
            await message.answer("❌ Неверный формат даты!")
            return
    data = await state.get_data()
    quest_id = data.get("edit_quest_id")
    _, error = await db.update_quest(message.from_user.id, quest_id, deadline=deadline)
    await state.clear()
    if error:
        await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
    else:
        await message.answer("✅ Дедлайн обновлён", reply_markup=get_quests_menu_keyboard())

@router.callback_query(F.data.startswith("edit_comment_"))
async def cb_edit_comment(callback: CallbackQuery, state: FSMContext):
    quest_id = int(callback.data.split("_")[2])
    await state.set_state(QuestEdit.waiting_for_comment)
    await state.update_data(edit_quest_id=quest_id)
    keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data=f"quest_{quest_id}")]]
    await callback.message.edit_text("Введи новый комментарий или 'нет':", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.message(QuestEdit.waiting_for_comment)
async def process_edit_comment(message: Message, state: FSMContext):
    text = message.text.strip()
    comment = None if text.lower() in ["нет", "no", "skip"] else text
    if comment:
        is_valid, error_msg = db.validate_input(comment, "Комментарий")
        if not is_valid:
            await message.answer(f"❌ {error_msg}")
            return
    data = await state.get_data()
    quest_id = data.get("edit_quest_id")
    _, error = await db.update_quest(message.from_user.id, quest_id, comment=comment)
    await state.clear()
    if error:
        await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
    else:
        await message.answer("✅ Комментарий обновлён", reply_markup=get_quests_menu_keyboard())

@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню\n\nВыбери действие:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Квесты", callback_data="my_quests_inline")]]))
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Главное меню\n\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Квесты", callback_data="my_quests_inline")]])
    )
    await callback.answer()

@router.callback_query(F.data == "create_quest_inline")
async def cb_create_quest_inline(callback: CallbackQuery, state: FSMContext):
    await state.set_state(QuestCreation.waiting_for_type)
    await callback.message.answer("Выбери тип квеста:", reply_markup=get_quest_type_keyboard())
    await callback.answer()


# Старые callback-хендлеры не используются, т.к. все переведено на ReplyKeyboardMarkup


@router.message(F.text == "🤖 AI Квест")
async def callback_ai_quest_message(message: Message, state: FSMContext):
    """AI генерация квеста"""
    if not config.WINDSURF_API_KEY:
        await message.answer("⚠️ AI функция недоступна")
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
    await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())


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
    await callback.message.edit_text(
        "Главное меню\n\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📋 Квесты", callback_data="my_quests_inline")]]
        )
    )

@router.callback_query(F.data.startswith("meditate_"))
async def callback_meditate(callback: CallbackQuery):
    try:
        quest_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    user_id = callback.from_user.id
    quest = await db.get_quest(user_id, quest_id)
    if not quest:
        await callback.answer("Квест не найден")
        return
    minutes = int(quest[4])
    await callback.answer("Таймер запущен")
    await callback.message.answer(f"🧘 Медитация начата на {minutes} мин.")
    async def _timer(chat_id: int, mins: int):
        from asyncio import sleep
        await sleep(mins * 60)
        await callback.message.bot.send_message(chat_id, "⏰ Время медитации вышло! Как самочувствие?")
    try:
        import asyncio
        asyncio.create_task(_timer(callback.message.chat.id, minutes))
    except Exception:
        pass
