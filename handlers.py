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
from datetime import datetime, timedelta
from datetime_utils import (
    comment_should_be_saved,
)
from loguru import logger

from database_async import db
from ai_client import ai_client
from config import config

# Создаем роутер для обработчиков
router = Router()

# Активные сессии медитации: {(user_id, quest_id): {"start": datetime, "task": asyncio.Task}}
MEDITATION_SESSIONS = {}


# FSM States для управления состояниями диалога
class QuestCreation(StatesGroup):
    waiting_for_type = State()
    waiting_for_title = State()
    waiting_for_reps = State()
    waiting_for_sets = State()
    waiting_for_pages = State()
    waiting_for_minutes = State()
    waiting_for_progress = State()
    waiting_for_deadline_input = State()
    waiting_for_deadline_time = State()
    waiting_for_comment = State()

class QuestEdit(StatesGroup):
    waiting_for_title = State()
    waiting_for_target = State()
    waiting_for_comment = State()

class QuestProgress(StatesGroup):
    waiting_for_value = State()

class AIQuest(StatesGroup):
    waiting_for_goal = State()

def get_quests_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="📋 Квесты"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="❓ Помощь"), KeyboardButton(text="➕ Создать квест")],
        [KeyboardButton(text="установить часовой пояс")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_quest_type_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="💪 Физические упражнения"), KeyboardButton(text="📚 Чтение")],
        [KeyboardButton(text="🧠 Медитация"), KeyboardButton(text="🎯 Произвольный квест")],
        [KeyboardButton(text="🔙 Отмена")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=False)


def compute_status_emoji(deadline_str: str | None) -> str:
    """Маркер статуса по дедлайну:
    ⚪ — времени достаточно или дедлайна нет
    🟡 — до дедлайна ≤ 1 часа
    🔴 — просрочен
    """
    try:
        if not deadline_str:
            return "⚪"
        dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M:%S")
        now_utc = datetime.utcnow()
        delta = dt - now_utc
        if delta.total_seconds() < 0:
            return "🔴"
        if delta.total_seconds() <= 3600:
            return "🟡"
        return "⚪"
    except Exception:
        return "⚪"

def get_quest_detail_keyboard(quest_id: int, completed: bool, quest_type: str, target_value: int) -> InlineKeyboardMarkup:
    keyboard = []
    # Скрываем обновление прогресса для custom без шкалы и для медитации
    if not completed and not (quest_type == "custom" and int(target_value or 0) == 0) and quest_type != "mental":
        keyboard.append([InlineKeyboardButton(text="📈 Обновить прогресс", callback_data=f"progress_{quest_id}")])
    if not completed:
        keyboard.append([InlineKeyboardButton(text="✅ Завершить", callback_data=f"complete_{quest_id}")])
    keyboard.append([InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{quest_id}")])
    keyboard.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{quest_id}")])
    if quest_type == "mental":
        keyboard.append([InlineKeyboardButton(text="▶️ Начать медитацию", callback_data=f"meditate_{quest_id}")])
    keyboard.append([InlineKeyboardButton(text="🔙 К списку", callback_data="my_quests_inline")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

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
    tz_off, _ = await db.get_user_timezone(user_id)
    text = format_quest_text(quest, tz_off)
    completed = bool(quest[6])
    quest_type = quest[3]
    target_value = int(quest[4])
    await callback.message.edit_text(text, reply_markup=get_quest_detail_keyboard(quest_id, completed, quest_type, target_value), parse_mode="HTML")
    await callback.answer()

def format_quest_text(quest: tuple, tz_offset_minutes: int | None = None) -> str:
    """Форматирование текста квеста с учетом наличия даты/времени"""
    # Порядок колонок: quest_id, user_id, title, quest_type, target_value, current_value,
    # completed, deadline, comment, created_at, has_date, has_time
    quest_id, user_id, title, quest_type, target_value, current_value, completed, deadline, comment, created_at, has_date, has_time = quest
    
    type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
    
    if quest_type in ["physical", "intellectual", "mental"]:
        progress_text = f"{current_value}/{target_value}"
    else:
        # Произвольный без прогресса (target_value == 0) — скрываем строку прогресса
        progress_text = None if int(target_value or 0) == 0 else f"{current_value}%"
    
    status = "✅ Завершен" if completed else "⏳ В процессе"
    
    text = f"{type_emoji} <b>{title}</b>\nID: {quest_id}\n\n"
    text += f"Тип: {config.QUEST_TYPES.get(quest_type, quest_type)}\n"
    if progress_text is not None:
        text += f"Прогресс: {progress_text}\n"
    text += f"Статус: {status}\n"
    # Дедлайн (логика через флаги has_date/has_time)
    try:
        hd = bool(has_date)
        ht = bool(has_time)
    except Exception:
        hd = deadline is not None
        # если есть строка дедлайна, но 00:00:00 — считаем без времени
        ht = bool(deadline) and (str(deadline).strip()[-8:] != "00:00:00")

    if not hd:
        text += "Дедлайн: без даты и времени\n"
    else:
        # есть дата; если строки нет (на всякий случай), выход
        if not deadline:
            text += "Дедлайн: без даты и времени\n"
        else:
            try:
                dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
                if tz_offset_minutes is not None:
                    dt = dt + timedelta(minutes=int(tz_offset_minutes))
                date_str = dt.strftime("%d.%m.%y")
                if not ht:
                    text += f"Дедлайн: {date_str}, без времени\n"
                else:
                    time_str = dt.strftime("%H:%M")
                    text += f"Дедлайн: {date_str} {time_str}\n"
            except Exception:
                text += "Дедлайн: указан\n"
    
    if comment and comment_should_be_saved(str(comment), None):
        text += f"\n💬 Комментарий: {comment}\n"
    
    return text

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


@router.callback_query(F.data.startswith("delete_"))
async def cb_delete_quest(callback: CallbackQuery):
    try:
        quest_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    user_id = callback.from_user.id
    ok = await db.delete_quest(user_id, quest_id)
    if ok:
        await callback.answer("🗑 Удалено")
        # Обновляем список квестов
        quests = await db.get_user_quests(user_id)
        if not quests:
            keyboard = [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]
            await callback.message.edit_text("📋 У тебя пока нет активных квестов!", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        else:
            keyboard = []
            for quest in quests:
                q_id = quest[0]
                title = quest[2]
                q_type = quest[3]
                status_emoji = compute_status_emoji(quest[7])
                type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(q_type, "🎯")
                keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {title}", callback_data=f"quest_{q_id}")])
            await callback.message.edit_text("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    else:
        await callback.answer("Ошибка удаления")

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

## Редактирование дедлайна удалено

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
    # Сообщение с кнопкой отмены медитации
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_meditation_{quest_id}")]]
    )
    await callback.message.answer(f"🧘 Медитация начата на {minutes} мин.", reply_markup=cancel_kb)
    # Запускаем таймер и сохраняем сессию
    try:
        import asyncio
        start_time = datetime.now()
        async def _timer(chat_id: int, mins: int, u_id: int, q_id: int):
            from asyncio import sleep
            await sleep(mins * 60)
            # Убираем сессию, если есть
            MEDITATION_SESSIONS.pop((u_id, q_id), None)
            # Завершаем квест автоматически
            try:
                await db.complete_quest(u_id, q_id)
            except Exception:
                pass
            # Сообщение и возврат к списку квестов
            await callback.message.bot.send_message(chat_id, "медитация завершена")
            # Показать список квестов (inline)
            quests = await db.get_user_quests(u_id)
            keyboard = []
            for q in quests:
                q_id2 = q[0]
                title2 = q[2]
                q_type2 = q[3]
                status_emoji = compute_status_emoji(q[7])
                type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(q_type2, "🎯")
                keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {title2}", callback_data=f"quest_{q_id2}")])
            await callback.message.bot.send_message(chat_id, "📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

        task = asyncio.create_task(_timer(callback.message.chat.id, minutes, user_id, quest_id))
        MEDITATION_SESSIONS[(user_id, quest_id)] = {"start": start_time, "task": task}
    except Exception:
        pass

@router.callback_query(F.data.startswith("cancel_meditation_"))
async def cancel_meditation(callback: CallbackQuery):
    try:
        quest_id = int(callback.data.split("_")[2])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    user_id = callback.from_user.id
    sess = MEDITATION_SESSIONS.pop((user_id, quest_id), None)
    elapsed_minutes = 0
    if sess:
        try:
            task = sess.get("task")
            if task:
                task.cancel()
        except Exception:
            pass
        try:
            start = sess.get("start")
            if isinstance(start, datetime):
                elapsed_minutes = int(max(0, (datetime.now() - start).total_seconds() // 60))
        except Exception:
            elapsed_minutes = 0
    # Обновим прогресс медитации прошедшими минутами, не превышая цель
    quest = await db.get_quest(user_id, quest_id)
    if quest:
        target_minutes = int(quest[4])
        new_value = min(elapsed_minutes, target_minutes)
        try:
            await db.update_quest_progress(user_id, quest_id, new_value)
        except Exception:
            pass
    await callback.answer("медитация прервана")
    # Вернёмся на форму квеста
    quest = await db.get_quest(user_id, quest_id)
    if quest:
        tz_off, _ = await db.get_user_timezone(user_id)
        text = format_quest_text(quest, tz_off)
        completed = bool(quest[6])
        quest_type = quest[3]
        target_value = int(quest[4])
        await callback.message.edit_text(text, reply_markup=get_quest_detail_keyboard(quest_id, completed, quest_type, target_value), parse_mode="HTML")
        # Низовое меню доступно через стандартное reply-меню уже имеющееся у пользователя

@router.message(F.text.casefold() == "отмена")
async def cancel_creation(message: Message, state: FSMContext):
    cur = await state.get_state()
    # Отмена работает только в процессе создания
    if cur and cur.startswith(QuestCreation.__name__):
        await state.clear()
        await message.answer("📋 Квесты\n\nВыбери действие:", reply_markup=get_quests_menu_keyboard())


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    await db.add_user(user.id, user.first_name or user.username or "User")
    welcome_text = (
        f"Привет, {user.first_name}! 🚀\n\n"
        "Я — твой проводник на пути к Сверхчеловеку.\n"
        "Вместе мы превратим рутину в увлекательную игру!\n\n"
        "Выбери действие:"
    )
    await message.answer(welcome_text, reply_markup=get_quests_menu_keyboard())


@router.message(Command("logs_on"))
async def cmd_logs_on(message: Message):
    await db.add_user(message.from_user.id, message.from_user.first_name or message.from_user.username or "User")
    await db.set_log_subscription(message.from_user.id, True)
    await message.answer("📡 RT-логи включены для этого чата")


@router.message(Command("logs_off"))
async def cmd_logs_off(message: Message):
    await db.set_log_subscription(message.from_user.id, False)
    await message.answer("🛰 RT-логи выключены для этого чата")


@router.message((F.text == "📋 Квесты") | (F.text.casefold() == "квесты"))
async def show_my_quests(message: Message, state: FSMContext):
    try:
        await state.clear()
    except Exception:
        pass
    user_id = message.from_user.id
    quests = await db.get_user_quests(user_id)
    if not quests:
        await message.answer("📋 У тебя пока нет активных квестов!")
        return
    keyboard = []
    for quest in quests:
        q_id = quest[0]
        title = quest[2]
        q_type = quest[3]
        status_emoji = compute_status_emoji(quest[7])
        type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(q_type, "🎯")
        keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {title}", callback_data=f"quest_{q_id}")])
    await message.answer("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.message(F.text == "➕ Создать квест")
async def create_quest_menu(message: Message, state: FSMContext):
    # Один раз предложим установить TZ, если ещё не предлагали
    tz_off, prompted = await db.get_user_timezone(message.from_user.id)
    if not prompted:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Установить сейчас", callback_data="tz_setup_now")],
            [InlineKeyboardButton(text="Пропустить", callback_data="tz_setup_skip")],
        ])
        await state.update_data(_pending_creation_after_tz=True)
        await message.answer("Для точного дедлайна укажи свой часовой пояс. Сделать сейчас?", reply_markup=kb)
        return
    await state.set_state(QuestCreation.waiting_for_type)
    await message.answer("Выбери тип квеста:", reply_markup=get_quest_type_keyboard())


class TimezoneSetup(StatesGroup):
    waiting_for_local_time = State()

@router.message(F.text.casefold() == "установить часовой пояс")
async def cmd_set_timezone(message: Message, state: FSMContext):
    await state.set_state(TimezoneSetup.waiting_for_local_time)
    await message.answer("Отправьте ваше текущее локальное время в формате HH:MM")

@router.callback_query(F.data == "tz_setup_now")
async def cb_tz_setup_now(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TimezoneSetup.waiting_for_local_time)
    await callback.message.answer("Отправьте ваше текущее локальное время в формате HH:MM")
    await callback.answer()

@router.callback_query(F.data == "tz_setup_skip")
async def cb_tz_setup_skip(callback: CallbackQuery, state: FSMContext):
    await db.set_user_tz_prompted(callback.from_user.id)
    pending = (await state.get_data()).get("_pending_creation_after_tz")
    await callback.answer("Ок, используем время по умолчанию")
    if pending:
        await state.set_state(QuestCreation.waiting_for_type)
        await callback.message.answer("Выбери тип квеста:", reply_markup=get_quest_type_keyboard())
    else:
        await callback.message.answer("Часовой пояс можно установить в главном меню")

@router.message(TimezoneSetup.waiting_for_local_time)
async def process_local_time(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    try:
        hh, mm = map(int, txt.split(":"))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
    except Exception:
        await message.answer("Формат времени HH:MM, например 14:05. Попробуйте снова")
        return
    now_utc = datetime.utcnow()
    utc_minutes = now_utc.hour * 60 + now_utc.minute
    local_minutes = hh * 60 + mm
    diff = local_minutes - utc_minutes
    while diff <= -12*60:
        diff += 24*60
    while diff > 14*60:
        diff -= 24*60
    await db.set_user_timezone(message.from_user.id, diff)
    pending = (await state.get_data()).get("_pending_creation_after_tz")
    await state.clear()
    await message.answer("Часовой пояс сохранён", reply_markup=get_quests_menu_keyboard())
    if pending:
        await state.set_state(QuestCreation.waiting_for_type)
        await message.answer("Выбери тип квеста:", reply_markup=get_quest_type_keyboard())


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
    for quest in quests:
        quest_id = quest[0]
        title = quest[2]
        quest_type = quest[3]
        status_emoji = compute_status_emoji(quest[7])
        type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
        keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {title}", callback_data=f"quest_{quest_id}")])
    await callback.message.edit_text("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()


@router.message(QuestCreation.waiting_for_type)
async def select_quest_type(message: Message, state: FSMContext):
    mapping = {
        "💪 Физические упражнения": "physical",
        "📚 Чтение": "intellectual",
        "🧠 Медитация": "mental",
        "🎯 Произвольный квест": "custom",
    }
    quest_type = mapping.get(message.text)
    if not quest_type:
        await message.answer("Пожалуйста, выбери тип из кнопок ниже")
        return
    await state.update_data(quest_type=quest_type)
    if quest_type == "mental":
        await state.update_data(title="Медитация")
        await state.set_state(QuestCreation.waiting_for_minutes)
        await message.answer("Сколько минут медитации? (число):", reply_markup=ReplyKeyboardRemove())
        return
    if quest_type == "intellectual":
        await state.set_state(QuestCreation.waiting_for_title)
        await message.answer("тип квеста: чтение\n\nвведите название книги:", reply_markup=ReplyKeyboardRemove())
        return
    await state.set_state(QuestCreation.waiting_for_title)
    await message.answer("Введи название квеста:", reply_markup=ReplyKeyboardRemove())


@router.message(QuestCreation.waiting_for_title)
async def process_quest_title(message: Message, state: FSMContext):
    title = message.text.strip()
    is_valid, error_msg = db.validate_input(title, "Название")
    if not is_valid:
        await message.answer(f"❌ {error_msg}\n\nПопробуй ещё раз:")
        return
    await state.update_data(title=title)
    data = await state.get_data()
    quest_type = data.get("quest_type")
    if quest_type == "physical":
        await state.set_state(QuestCreation.waiting_for_reps)
        await message.answer(f"Название: {title}\n\nВведи количество повторений в одном подходе (число):")
    elif quest_type == "intellectual":
        await state.set_state(QuestCreation.waiting_for_pages)
        await message.answer(f"Название: {title}\n\nВведи количество страниц (число):")
    elif quest_type == "custom":
        await state.set_state(QuestCreation.waiting_for_progress)
        text = f"Название: {title}\n\nУ квеста есть прогресс?"
        keyboard = [[
            InlineKeyboardButton(text="Да", callback_data="custom_progress_yes"),
            InlineKeyboardButton(text="Нет", callback_data="custom_progress_no")
        ]]
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


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
    await state.set_state(QuestCreation.waiting_for_deadline_input)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="сегодня", callback_data="deadline_today")],
        [InlineKeyboardButton(text="пропустить", callback_data="deadline_skip_all")],
    ])
    await message.answer("Укажи дедлайн в формате dd.mm.yy hh:mm или выбери кнопку ниже", reply_markup=kb)


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
    await state.set_state(QuestCreation.waiting_for_deadline_input)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="сегодня", callback_data="deadline_today")],
        [InlineKeyboardButton(text="пропустить", callback_data="deadline_skip_all")],
    ])
    await message.answer("Укажи дедлайн в формате dd.mm.yy hh:mm или выбери кнопку ниже", reply_markup=kb)


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
    await state.set_state(QuestCreation.waiting_for_deadline_input)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="сегодня", callback_data="deadline_today")],
        [InlineKeyboardButton(text="пропустить", callback_data="deadline_skip_all")],
    ])
    await message.answer("Укажи дедлайн в формате dd.mm.yy hh:mm или выбери кнопку ниже", reply_markup=kb)


@router.callback_query(F.data.in_(["custom_progress_yes", "custom_progress_no"]))
async def cb_custom_progress(callback: CallbackQuery, state: FSMContext):
    has_progress = callback.data.endswith("yes")
    await state.update_data(target_value=(100 if has_progress else 0))
    await state.set_state(QuestCreation.waiting_for_deadline_input)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="сегодня", callback_data="deadline_today")],
        [InlineKeyboardButton(text="пропустить", callback_data="deadline_skip_all")],
    ])
    await callback.message.edit_text("Укажи дедлайн в формате dd.mm.yy hh:mm или выбери кнопку ниже", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "skip_comment")
async def cb_skip_comment(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    await db.add_user(user.id, user.first_name or user.username or "User")
    data = await state.get_data()
    quest_id, error = await db.create_quest(
        user_id=user.id,
        title=data["title"],
        quest_type=data["quest_type"],
        target_value=data["target_value"],
        comment=None,
        deadline=(await state.get_data()).get("deadline"),
        has_date=(await state.get_data()).get("has_date"),
        has_time=(await state.get_data()).get("has_time"),
    )
    if error:
        await state.clear()
        await callback.message.edit_text(f"❌ Ошибка: {error}")
    else:
        await state.clear()
        # Показать карточку только что созданного квеста
        if quest_id:
            quest = await db.get_quest(user.id, quest_id)
            if quest:
                tz_off, _ = await db.get_user_timezone(user.id)
                text = format_quest_text(quest, tz_off)
                completed = bool(quest[6])
                quest_type = quest[3]
                target_value = int(quest[4])
                await callback.message.edit_text(text, reply_markup=get_quest_detail_keyboard(quest_id, completed, quest_type, target_value), parse_mode="HTML")
                await callback.message.answer("Главное меню\n\nВыбери действие:", reply_markup=get_quests_menu_keyboard())
                await callback.answer()
                return
        # Fallback: список квестов
        quests = await db.get_user_quests(user.id)
        if not quests:
            await callback.message.edit_text("📋 У тебя пока нет активных квестов!")
        else:
            keyboard = []
            for q in quests:
                q_id = q[0]
                q_title = q[2]
                q_type = q[3]
                status_emoji = "⚪"
                type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(q_type, "🎯")
                keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {q_title}", callback_data=f"quest_{q_id}")])
            await callback.message.edit_text("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
            await callback.message.answer("Главное меню\n\nВыбери действие:", reply_markup=get_quests_menu_keyboard())
        await callback.answer()


@router.message(QuestCreation.waiting_for_comment)
async def process_quest_comment(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    comment = text if comment_should_be_saved(text, None) else None
    if comment:
        is_valid, error_msg = db.validate_input(comment, "Комментарий")
        if not is_valid:
            await message.answer(f"❌ {error_msg}")
            return
    await db.add_user(message.from_user.id, message.from_user.first_name or message.from_user.username or "User")
    quest_id, error = await db.create_quest(
        user_id=message.from_user.id,
        title=data["title"],
        quest_type=data["quest_type"],
        target_value=data["target_value"],
        comment=comment,
        deadline=(await state.get_data()).get("deadline"),
        has_date=(await state.get_data()).get("has_date"),
        has_time=(await state.get_data()).get("has_time"),
    )
    if error:
        await state.clear()
        await message.answer(f"❌ Ошибка: {error}", reply_markup=get_quests_menu_keyboard())
        return
    await state.clear()
    # Показать карточку только что созданного квеста
    if quest_id:
        quest = await db.get_quest(message.from_user.id, quest_id)
        if quest:
            tz_off, _ = await db.get_user_timezone(message.from_user.id)
            text = format_quest_text(quest, tz_off)
            completed = bool(quest[6])
            quest_type = quest[3]
            target_value = int(quest[4])
            await message.answer(text, reply_markup=get_quest_detail_keyboard(quest_id, completed, quest_type, target_value), parse_mode="HTML")
            await message.answer("Главное меню\n\nВыбери действие:", reply_markup=get_quests_menu_keyboard())
            return
    # Fallback: список квестов
    user_id = message.from_user.id
    quests = await db.get_user_quests(user_id)
    if not quests:
        await message.answer("📋 У тебя пока нет активных квестов!")
    else:
        keyboard = []
        for quest in quests:
            qid = quest[0]
            title = quest[2]
            qtype = quest[3]
            status_emoji = "⚪"
            type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(qtype, "🎯")
            keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {title}", callback_data=f"quest_{qid}")])
        await message.answer("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        await message.answer("Главное меню\n\nВыбери действие:", reply_markup=get_quests_menu_keyboard())


# ===== Дедлайн: обработчики кнопок и ввода =====
@router.message(QuestCreation.waiting_for_deadline_input)
async def process_deadline_input(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) not in (1, 2):
        await message.answer("Формат: dd.mm.yy или dd.mm.yy hh:mm")
        return
    try:
        local_date = datetime.strptime(parts[0], "%d.%m.%y")
    except Exception:
        await message.answer("Некорректная дата. Формат: dd.mm.yy")
        return
    hh = mm = None
    if len(parts) == 2:
        try:
            hh, mm = map(int, parts[1].split(":"))
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError
        except Exception:
            await message.answer("Некорректное время. Формат: hh:mm")
            return
    tz_off, _ = await db.get_user_timezone(message.from_user.id)
    h = hh if hh is not None else 0
    m = mm if mm is not None else 0
    dt_local = datetime(local_date.year, local_date.month, local_date.day, h, m, 0)
    if tz_off is None:
        dt_utc_str = dt_local.strftime("%Y-%m-%d %H:%M:%S")
    else:
        dt_utc = dt_local - timedelta(minutes=int(tz_off))
        dt_utc_str = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
    await state.update_data(deadline=dt_utc_str)
    await state.update_data(has_date=True, has_time=(hh is not None))
    logger.info(f"[DEADLINE] manual parsed -> local={dt_local}, utc_str='{dt_utc_str}', tz_off={tz_off}")
    await state.set_state(QuestCreation.waiting_for_comment)
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    await message.answer("Добавьте комментарий (введите текст сообщением)", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data == "deadline_today")
async def cb_deadline_today(callback: CallbackQuery, state: FSMContext):
    tz_off, _ = await db.get_user_timezone(callback.from_user.id)
    now_utc = datetime.utcnow()
    local_now = now_utc + timedelta(minutes=int(tz_off)) if tz_off is not None else now_utc
    logger.info(f"[DEADLINE] button today pressed, tz_off={tz_off}, local_now={local_now}")
    await state.update_data(_deadline_local_date=(local_now.year, local_now.month, local_now.day))
    await state.set_state(QuestCreation.waiting_for_deadline_time)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="пропустить", callback_data="deadline_time_skip")]])
    await callback.message.edit_text("Введи время в формате hh:mm (или нажми Пропустить)", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "deadline_time_skip")
async def cb_deadline_time_skip(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    y, m, d = data.get("_deadline_local_date")
    tz_off, _ = await db.get_user_timezone(callback.from_user.id)
    dt_local = datetime(y, m, d, 0, 0, 0)
    if tz_off is None:
        dt_utc_str = dt_local.strftime("%Y-%m-%d %H:%M:%S")
    else:
        dt_utc = dt_local - timedelta(minutes=int(tz_off))
        dt_utc_str = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
    await state.update_data(deadline=dt_utc_str)
    await state.update_data(has_date=True, has_time=False)
    logger.info(f"[DEADLINE] time skipped -> local={dt_local}, utc_str='{dt_utc_str}', tz_off={tz_off}")
    await state.set_state(QuestCreation.waiting_for_comment)
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    await callback.message.edit_text("📌 Дедлайн установлен: сегодня, без времени.\n\nДобавьте комментарий (введите текст сообщением)", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()


@router.message(QuestCreation.waiting_for_deadline_time)
async def process_deadline_time(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        hh, mm = map(int, (message.text or "").strip().split(":"))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
    except Exception:
        await message.answer("Некорректное время. Формат: hh:mm")
        return
    y, m, d = data.get("_deadline_local_date")
    tz_off, _ = await db.get_user_timezone(message.from_user.id)
    dt_local = datetime(y, m, d, hh, mm, 0)
    if tz_off is None:
        dt_utc_str = dt_local.strftime("%Y-%m-%d %H:%M:%S")
    else:
        dt_utc = dt_local - timedelta(minutes=int(tz_off))
        dt_utc_str = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
    await state.update_data(deadline=dt_utc_str)
    await state.update_data(has_date=True, has_time=True)
    logger.info(f"[DEADLINE] time set -> local={dt_local}, utc_str='{dt_utc_str}', tz_off={tz_off}")
    await state.set_state(QuestCreation.waiting_for_comment)
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    shown_time = f"{hh:02d}:{mm:02d}"
    await message.answer(f"📌 Дедлайн установлен: сегодня, {shown_time}.\n\nДобавьте комментарий (введите текст сообщением)", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data == "deadline_skip_all")
async def cb_deadline_skip_all(callback: CallbackQuery, state: FSMContext):
    await state.update_data(deadline=None, has_date=False, has_time=False)
    await state.set_state(QuestCreation.waiting_for_comment)
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    await callback.message.edit_text("Добавьте комментарий (введите текст сообщением)", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()
