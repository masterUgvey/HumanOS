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
    waiting_for_mode = State()
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
    # Daily-specific
    waiting_for_daily_days = State()
    waiting_for_daily_time = State()
    waiting_for_daily_time_custom = State()

class QuestEdit(StatesGroup):
    waiting_for_title = State()
    waiting_for_target = State()
    waiting_for_comment = State()
    waiting_for_deadline = State()

class QuestProgress(StatesGroup):
    waiting_for_value = State()

class AIQuest(StatesGroup):
    waiting_for_goal = State()

# ===== Lists FSM =====
class ListCreation(StatesGroup):
    waiting_for_title = State()

class ListItemAdd(StatesGroup):
    waiting_for_text = State()

def get_quests_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="📋 Квесты"), KeyboardButton(text="📝 Списки")],
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

def format_repeat_days_label(repeat_days: str | None) -> str:
    if not repeat_days or repeat_days.strip() == "":
        return "Каждый день"
    names = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}
    try:
        parts = [p.strip() for p in repeat_days.split(',') if p.strip()]
        nums = []
        for p in parts:
            v = int(p)
            if v == 0: v = 7
            nums.append(v)
        return ",".join(names.get(n, str(n)) for n in nums)
    except Exception:
        return repeat_days or "Каждый день"

def build_daily_days_keyboard(selected: list[int]) -> InlineKeyboardMarkup:
    names = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}
    rows = []
    row = []
    for i in range(1, 8):
        label = ("✅ " if i in selected else "⬜ ") + names[i]
        row.append(InlineKeyboardButton(text=label, callback_data=f"daily_days_toggle_{i}"))
        if i % 4 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="📅 Каждый день", callback_data="daily_days_preset_all"),
        InlineKeyboardButton(text="🏢 Будни", callback_data="daily_days_preset_weekdays"),
        InlineKeyboardButton(text="🌅 Выходные", callback_data="daily_days_preset_weekend"),
    ])
    rows.append([InlineKeyboardButton(text="Далее ➡️", callback_data="daily_days_next")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="create_quest_inline")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def start_daily_days_selection(message: Message, state: FSMContext):
    await state.set_state(QuestCreation.waiting_for_daily_days)
    await state.update_data(daily_days=[])  # empty -> каждый день по умолчанию допускаем, но пользователь сможет выбрать
    kb = build_daily_days_keyboard([])
    await message.answer("Выберите дни повторения:", reply_markup=kb)

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

def get_daily_detail_keyboard(quest_id: int, done_today: bool) -> InlineKeyboardMarkup:
    keyboard = []
    if not done_today:
        keyboard.append([InlineKeyboardButton(text="✅ Выполнить сегодня", callback_data=f"daily_done_{quest_id}")])
    else:
        keyboard.append([InlineKeyboardButton(text="↩️ Отменить выполнение", callback_data=f"daily_undo_{quest_id}")])
    keyboard.append([InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{quest_id}")])
    keyboard.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{quest_id}")])
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
    # Daily rendering
    if await db.is_quest_daily(quest_id):
        meta = await db.get_daily_meta(quest_id)
        if meta:
            repeat_days, streak, last_done_date, daily_reminder_time, owner_uid = meta
            done_today = await db.is_done_today(callback.from_user.id, quest_id)
            days_label = format_repeat_days_label(repeat_days)
            today_status = "✅ Выполнено сегодня" if done_today else "⏳ На сегодня"
            rt = daily_reminder_time or "нет"
            text += f"\n📅 Режим: Ежедневная задача\n📆 Дни: {days_label}\n🔥 Серия: {int(streak or 0)} дней\n⏰ Напоминание: {rt}\n📊 Сегодня: {today_status}\n"
            await callback.message.edit_text(text, reply_markup=get_daily_detail_keyboard(quest_id, done_today), parse_mode="HTML")
            await callback.answer()
            return
    await callback.message.edit_text(text, reply_markup=get_quest_detail_keyboard(quest_id, completed, quest_type, target_value), parse_mode="HTML")
    await callback.answer()

# ===== Daily: days selection =====
@router.callback_query(F.data.startswith("daily_days_toggle_"))
async def cb_daily_days_toggle(callback: CallbackQuery, state: FSMContext):
    try:
        day = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer("Ошибка")
        return
    data = await state.get_data()
    sel = set(data.get("daily_days") or [])
    if day in sel:
        sel.remove(day)
    else:
        sel.add(day)
    await state.update_data(daily_days=sorted(sel))
    kb = build_daily_days_keyboard(sorted(sel))
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        try:
            await callback.message.edit_text("Выберите дни повторения:", reply_markup=kb)
        except Exception:
            pass
    await callback.answer()

@router.callback_query(F.data.startswith("daily_days_preset_"))
async def cb_daily_days_preset(callback: CallbackQuery, state: FSMContext):
    preset = callback.data.split("_")[-1]
    if preset == "all":
        sel = [1,2,3,4,5,6,7]
    elif preset == "weekdays":
        sel = [1,2,3,4,5]
    else:
        sel = [6,7]
    await state.update_data(daily_days=sel)
    kb = build_daily_days_keyboard(sel)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        try:
            await callback.message.edit_text("Выберите дни повторения:", reply_markup=kb)
        except Exception:
            pass
    await callback.answer()

@router.callback_query(F.data == "daily_days_next")
async def cb_daily_days_next(callback: CallbackQuery, state: FSMContext):
    await state.set_state(QuestCreation.waiting_for_daily_time)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="09:00", callback_data="daily_time_09:00"), InlineKeyboardButton(text="12:00", callback_data="daily_time_12:00"), InlineKeyboardButton(text="18:00", callback_data="daily_time_18:00")],
        [InlineKeyboardButton(text="Без напоминания", callback_data="daily_time_none")],
        [InlineKeyboardButton(text="Ввести своё", callback_data="daily_time_custom")],
    ])
    await callback.message.edit_text("Во сколько напоминать?", reply_markup=kb)
    await callback.answer()

# ===== Daily: time selection =====
@router.callback_query(F.data.startswith("daily_time_"))
async def cb_daily_time(callback: CallbackQuery, state: FSMContext):
    tag = callback.data.split("_", 2)[-1]
    if tag == "custom":
        await state.set_state(QuestCreation.waiting_for_daily_time_custom)
        await callback.message.edit_text("Введите время в формате HH:MM (например, 09:00) или отправьте 'нет' для отключения напоминаний")
        await callback.answer()
        return
    reminder = None if tag == "none" else tag
    await finalize_daily_creation(callback, state, reminder)

@router.message(QuestCreation.waiting_for_daily_time_custom)
async def process_daily_time_custom(message: Message, state: FSMContext):
    t = (message.text or "").strip().lower()
    if t in {"нет", "no", "none"}:
        reminder = None
    else:
        try:
            hh, mm = map(int, t.split(":"))
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError
            reminder = f"{hh:02d}:{mm:02d}"
        except Exception:
            await message.answer("Некорректное время. Формат HH:MM")
            return
    await finalize_daily_creation(message, state, reminder)

async def finalize_daily_creation(event, state: FSMContext, reminder: str | None):
    # event can be Message or CallbackQuery
    get_uid = (lambda: event.from_user.id)
    send_answer = (lambda text, **kw: (event.message.answer if hasattr(event, 'message') else event.answer)(text, **kw))
    send_card = (lambda text, **kw: (event.message.answer if hasattr(event, 'message') else event.message.answer)(text, **kw))
    data = await state.get_data()
    user_id = get_uid()
    # Normalize days
    days = data.get("daily_days") or []
    # Empty -> каждый день
    repeat_days = ",".join(str(d) for d in days)
    # Create base quest
    quest_id, error = await db.create_quest(
        user_id=user_id,
        title=data.get("title"),
        quest_type=data.get("quest_type"),
        target_value=int(data.get("target_value") or 0),
        deadline=None,
        comment=None,
        has_date=False,
        has_time=False,
    )
    if error or not quest_id:
        await state.clear()
        await send_answer(f"❌ Ошибка: {error or 'не удалось создать задание'}")
        return
    # Update daily fields
    await db.update_quest(user_id, quest_id, is_daily=True, repeat_days=repeat_days, daily_reminder_time=reminder)
    await state.clear()
    # Show daily card
    quest = await db.get_quest(user_id, quest_id)
    tz_off, _ = await db.get_user_timezone(user_id)
    text = format_quest_text(quest, tz_off)
    meta = await db.get_daily_meta(quest_id)
    repeat_days_s, streak, last_done_date, daily_reminder_time, _ = meta if meta else ("", 0, None, None, None)
    done_today = await db.is_done_today(user_id, quest_id)
    text += f"\n📅 Режим: Ежедневная задача\n📆 Дни: {format_repeat_days_label(repeat_days_s)}\n🔥 Серия: {int(streak or 0)} дней\n⏰ Напоминание: {daily_reminder_time or 'нет'}\n📊 Сегодня: {'✅ Выполнено сегодня' if done_today else '⏳ На сегодня'}\n"
    kb = get_daily_detail_keyboard(quest_id, done_today)
    await send_card(text, reply_markup=kb, parse_mode="HTML")

# ===== Daily actions =====
@router.callback_query(F.data.startswith("daily_done_"))
async def cb_daily_done(callback: CallbackQuery):
    try:
        quest_id = int(callback.data.split("_")[2])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    ok = await db.mark_daily_done_for_today(callback.from_user.id, quest_id)
    if not ok:
        await callback.answer("Ошибка")
        return
    await cb_quest_detail(callback)

@router.callback_query(F.data.startswith("daily_undo_"))
async def cb_daily_undo(callback: CallbackQuery):
    try:
        quest_id = int(callback.data.split("_")[2])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    ok = await db.undo_daily_for_today(callback.from_user.id, quest_id)
    if not ok:
        await callback.answer("Ошибка")
        return
    await cb_quest_detail(callback)

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

@router.callback_query(F.data.regexp(r"^edit_\d+$"))
async def cb_edit_menu(callback: CallbackQuery):
    try:
        quest_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    keyboard = [
        [InlineKeyboardButton(text="📝 Название", callback_data=f"edit_title_{quest_id}")],
        [InlineKeyboardButton(text="🔖 Тип", callback_data=f"edit_type_menu_{quest_id}")],
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
    # Сохраняем исходное сообщение для обновления карточки
    await state.update_data(orig_chat_id=callback.message.chat.id, orig_message_id=callback.message.message_id)
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
    # Обновляем карточку квеста
    data_after = await db.get_quest(message.from_user.id, quest_id)
    tz_off, _ = await db.get_user_timezone(message.from_user.id)
    if data_after:
        txt = format_quest_text(data_after, tz_off)
        completed = bool(data_after[6])
        quest_type = data_after[3]
        target_value = int(data_after[4])
        try:
            await message.bot.edit_message_text(
                chat_id=data.get("orig_chat_id"),
                message_id=data.get("orig_message_id"),
                text=txt,
                reply_markup=get_quest_detail_keyboard(quest_id, completed, quest_type, target_value),
                parse_mode="HTML",
            )
        except Exception:
            pass
    await state.clear()
    if error:
        await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
    else:
        await message.answer("✅ Название обновлено", reply_markup=get_quests_menu_keyboard())

@router.callback_query(F.data.startswith("edit_target_"))
async def cb_edit_target(callback: CallbackQuery, state: FSMContext):
    quest_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    quest = await db.get_quest(user_id, quest_id)
    if not quest:
        await callback.answer("Квест не найден")
        return
    q_type = quest[3]
    await state.update_data(edit_quest_id=quest_id, _editing_target=True)
    await state.update_data(orig_chat_id=callback.message.chat.id, orig_message_id=callback.message.message_id)
    if q_type == "physical":
        await state.set_state(QuestCreation.waiting_for_reps)
        await callback.message.edit_text("Введи количество повторений в одном подходе (число):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data=f"quest_{quest_id}")]]))
    elif q_type == "intellectual":
        await state.set_state(QuestCreation.waiting_for_pages)
        await callback.message.edit_text("Введи количество страниц (число):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data=f"quest_{quest_id}")]]))
    elif q_type == "mental":
        await state.set_state(QuestCreation.waiting_for_minutes)
        await callback.message.edit_text("Сколько минут? (число):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data=f"quest_{quest_id}")]]))
    else:
        # custom: спросим, есть ли прогресс (0% или 100%)
        await state.set_state(QuestCreation.waiting_for_progress)
        text = "У квеста есть прогресс?"
        keyboard = [[
            InlineKeyboardButton(text="Да", callback_data="custom_progress_yes"),
            InlineKeyboardButton(text="Нет", callback_data="custom_progress_no")
        ], [InlineKeyboardButton(text="❌ Отмена", callback_data=f"quest_{quest_id}")]]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
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
    # Обновляем карточку квеста
    data_after = await db.get_quest(message.from_user.id, quest_id)
    tz_off, _ = await db.get_user_timezone(message.from_user.id)
    if data_after:
        txt = format_quest_text(data_after, tz_off)
        completed = bool(data_after[6])
        quest_type = data_after[3]
        target_value = int(data_after[4])
        try:
            await message.bot.edit_message_text(
                chat_id=data.get("orig_chat_id"),
                message_id=data.get("orig_message_id"),
                text=txt,
                reply_markup=get_quest_detail_keyboard(quest_id, completed, quest_type, target_value),
                parse_mode="HTML",
            )
        except Exception:
            pass
    await state.clear()
    if error:
        await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
    else:
        await message.answer("✅ Цель обновлена", reply_markup=get_quests_menu_keyboard())

@router.callback_query(F.data.startswith("edit_deadline_"))
async def cb_edit_deadline(callback: CallbackQuery, state: FSMContext):
    quest_id = int(callback.data.split("_")[2])
    # Входим в те же шаги FSM, что и при создании дедлайна
    await state.set_state(QuestCreation.waiting_for_deadline_input)
    await state.update_data(edit_quest_id=quest_id, _editing_deadline=True)
    await state.update_data(orig_chat_id=callback.message.chat.id, orig_message_id=callback.message.message_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="сегодня", callback_data="deadline_today")],
        [InlineKeyboardButton(text="пропустить", callback_data="deadline_skip_all")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"quest_{quest_id}")],
    ])
    await callback.message.edit_text("Укажи дедлайн в формате dd.mm.yy hh:mm или выбери кнопку ниже", reply_markup=kb)
    await callback.answer()

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
    data = await state.get_data()
    if data.get("_editing_deadline"):
        # Режим редактирования: обновляем квест и карточку
        quest_id = data.get("edit_quest_id")
        _, error = await db.update_quest(message.from_user.id, quest_id, deadline=dt_utc_str)
        quest = await db.get_quest(message.from_user.id, quest_id)
        tz_off2, _ = await db.get_user_timezone(message.from_user.id)
        if quest:
            txt_card = format_quest_text(quest, tz_off2)
            completed = bool(quest[6])
            quest_type = quest[3]
            target_value = int(quest[4])
            try:
                await message.bot.edit_message_text(
                    chat_id=data.get("orig_chat_id"),
                    message_id=data.get("orig_message_id"),
                    text=txt_card,
                    reply_markup=get_quest_detail_keyboard(quest_id, completed, quest_type, target_value),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await state.clear()
        if error:
            await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
        else:
            await message.answer("✅ Дедлайн обновлён", reply_markup=get_quests_menu_keyboard())
        return
    # Режим создания: продолжаем как раньше
    await state.set_state(QuestCreation.waiting_for_comment)
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    await message.answer("Добавьте комментарий (введите текст сообщением)", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@router.callback_query(F.data.startswith("edit_type_menu_"))
async def cb_edit_type_menu(callback: CallbackQuery):
    quest_id = int(callback.data.split("_")[3])
    keyboard = [
        [InlineKeyboardButton(text="💪 Физические", callback_data=f"edit_type_physical_{quest_id}")],
        [InlineKeyboardButton(text="📚 Чтение", callback_data=f"edit_type_intellectual_{quest_id}")],
        [InlineKeyboardButton(text="🧠 Медитация", callback_data=f"edit_type_mental_{quest_id}")],
        [InlineKeyboardButton(text="🎯 Произвольный", callback_data=f"edit_type_custom_{quest_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"edit_{quest_id}")],
    ]
    await callback.message.edit_text("Выбери тип:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.callback_query(F.data.startswith("edit_type_"))
async def cb_edit_type(callback: CallbackQuery, state: FSMContext):
    # Формат: edit_type_{type}_{id}
    parts = callback.data.split("_")
    if len(parts) < 4 or parts[2] not in {"physical", "intellectual", "mental", "custom"}:
        await callback.answer("Некорректный тип")
        return
    quest_type = parts[2]
    quest_id = int(parts[3])
    user_id = callback.from_user.id
    # Сохраняем orig ids, чтобы обновить карточку после изменения
    await state.update_data(orig_chat_id=callback.message.chat.id, orig_message_id=callback.message.message_id)
    _, error = await db.update_quest(user_id, quest_id, quest_type=quest_type)
    # Обновляем карточку
    quest = await db.get_quest(user_id, quest_id)
    tz_off, _ = await db.get_user_timezone(user_id)
    if quest:
        txt = format_quest_text(quest, tz_off)
        completed = bool(quest[6])
        qtype = quest[3]
        target_value = int(quest[4])
        try:
            await callback.message.edit_text(txt, reply_markup=get_quest_detail_keyboard(quest_id, completed, qtype, target_value), parse_mode="HTML")
        except Exception:
            pass
    if error:
        await callback.message.answer(f"❌ {error}")
    else:
        await callback.message.answer("✅ Тип обновлён")
    await callback.answer()

@router.callback_query(F.data.startswith("edit_comment_"))
async def cb_edit_comment(callback: CallbackQuery, state: FSMContext):
    quest_id = int(callback.data.split("_")[2])
    await state.set_state(QuestEdit.waiting_for_comment)
    await state.update_data(edit_quest_id=quest_id)
    await state.update_data(orig_chat_id=callback.message.chat.id, orig_message_id=callback.message.message_id)
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
    # Обновляем карточку квеста
    data_after = await db.get_quest(message.from_user.id, quest_id)
    tz_off, _ = await db.get_user_timezone(message.from_user.id)
    if data_after:
        txt = format_quest_text(data_after, tz_off)
        completed = bool(data_after[6])
        quest_type = data_after[3]
        target_value = int(data_after[4])
        try:
            await message.bot.edit_message_text(
                chat_id=data.get("orig_chat_id"),
                message_id=data.get("orig_message_id"),
                text=txt,
                reply_markup=get_quest_detail_keyboard(quest_id, completed, quest_type, target_value),
                parse_mode="HTML",
            )
        except Exception:
            pass
    await state.clear()
    if error:
        await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
    else:
        await message.answer("✅ Комментарий обновлён", reply_markup=get_quests_menu_keyboard())

@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Главное меню\n\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Квесты", callback_data="my_quests_inline")], [InlineKeyboardButton(text="📝 Списки", callback_data="lists_menu")]])
    )
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Главное меню\n\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Квесты", callback_data="my_quests_inline")], [InlineKeyboardButton(text="📝 Списки", callback_data="lists_menu")]])
    )
    await callback.answer()

@router.callback_query(F.data == "create_quest_inline")
async def cb_create_quest_inline(callback: CallbackQuery, state: FSMContext):
    await state.set_state(QuestCreation.waiting_for_mode)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Обычный квест", callback_data="mode_regular")],
        [InlineKeyboardButton(text="📅 Ежедневная задача", callback_data="mode_daily")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
    ])
    await callback.message.answer("Выберите режим:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "mode_regular")
async def cb_mode_regular(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_daily=False)
    await state.set_state(QuestCreation.waiting_for_type)
    await callback.message.answer("Выбери тип квеста:", reply_markup=get_quest_type_keyboard())
    await callback.answer()

@router.callback_query(F.data == "mode_daily")
async def cb_mode_daily(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_daily=True)
    await state.set_state(QuestCreation.waiting_for_type)
    await callback.message.answer("Выбери тип ежедневной задачи:", reply_markup=get_quest_type_keyboard())
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
            inline_keyboard=[[InlineKeyboardButton(text="📋 Квесты", callback_data="my_quests_inline")], [InlineKeyboardButton(text="📝 Списки", callback_data="lists_menu")]]
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

# ===================== Lists / Checklists =====================
def format_list_text(list_row: tuple, items: list[tuple]) -> str:
    # list_row: (list_id, user_id, title, created_at, is_template)
    list_id, _, title, created_at, is_template = list_row
    text = f"📝 <b>{title}</b>\nID: {list_id}\n\n"
    if is_template:
        text += "Тип: шаблон\n\n"
    if not items:
        text += "Список пуст.\n"
    else:
        for item in items:
            # item: (item_id, list_id, text, completed, created_at)
            chk = "☑️" if bool(item[3]) else "⬜"
            text += f"{chk} {item[2]}\n"
    return text

def build_list_keyboard(list_id: int, items: list[tuple], owner_view: bool = True) -> InlineKeyboardMarkup:
    rows = []
    # For each item: toggle + delete
    for item_id, _, text, completed, _ in items:
        chk = "☑️" if bool(completed) else "⬜"
        if owner_view:
            rows.append([
                InlineKeyboardButton(text=f"{chk}", callback_data=f"toggle_item_{item_id}_{list_id}"),
                InlineKeyboardButton(text="🗑", callback_data=f"del_item_{item_id}_{list_id}"),
                InlineKeyboardButton(text=text[:24] + ("…" if len(text) > 24 else ""), callback_data=f"noop_{item_id}")
            ])
        else:
            rows.append([InlineKeyboardButton(text=f"{chk} {text}", callback_data=f"noop_{item_id}")])
    # Actions
    if owner_view:
        rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data=f"add_item_{list_id}")])
        rows.append([InlineKeyboardButton(text="🗑 Удалить список", callback_data=f"delete_list_{list_id}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="lists_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data == "lists_menu")
async def cb_lists_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Мои списки", callback_data="my_lists")],
        [InlineKeyboardButton(text="🆕 Создать список", callback_data="create_list_inline")],
        [InlineKeyboardButton(text="📑 Шаблоны", callback_data="list_templates")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
    ])
    await callback.message.edit_text("📝 Списки — выбери действие:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "my_lists")
async def cb_my_lists(callback: CallbackQuery):
    lists = await db.get_user_lists(callback.from_user.id)
    if not lists:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Создать список", callback_data="create_list_inline")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="lists_menu")],
        ])
        await callback.message.edit_text("У тебя пока нет списков.", reply_markup=kb)
        await callback.answer()
        return
    rows = []
    for l in lists:
        lid, _, title, _, _ = l
        rows.append([InlineKeyboardButton(text=f"📝 {title}", callback_data=f"list_{lid}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="lists_menu")])
    await callback.message.edit_text("📂 Мои списки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()

@router.callback_query(F.data == "list_templates")
async def cb_list_templates(callback: CallbackQuery):
    templates = await db.get_templates()
    if not templates:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="lists_menu")]])
        await callback.message.edit_text("Шаблоны отсутствуют.", reply_markup=kb)
        await callback.answer()
        return
    rows = []
    for l in templates:
        lid, _, title, _, _ = l
        rows.append([InlineKeyboardButton(text=f"📑 {title}", callback_data=f"list_{lid}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="lists_menu")])
    await callback.message.edit_text("📑 Шаблоны:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()

@router.callback_query(F.data == "create_list_inline")
async def cb_create_list_inline(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ListCreation.waiting_for_title)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="lists_menu")]])
    await callback.message.edit_text("Введи название списка:", reply_markup=kb)
    await callback.answer()

@router.message(ListCreation.waiting_for_title)
async def process_list_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    list_id, error = await db.create_list(message.from_user.id, title)
    await state.clear()
    if error:
        await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
        return
    # Открываем карточку списка
    lst = await db.get_list(message.from_user.id, list_id)
    items = await db.get_list_items(message.from_user.id, list_id)
    text = format_list_text(lst, items)
    kb = build_list_keyboard(list_id, items, owner_view=True)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("list_"))
async def cb_open_list(callback: CallbackQuery):
    try:
        list_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    lst = await db.get_list(callback.from_user.id, list_id)
    if not lst:
        await callback.answer("Список не найден")
        return
    items = await db.get_list_items(callback.from_user.id, list_id)
    text = format_list_text(lst, items)
    owner_view = (lst[1] == callback.from_user.id)
    kb = build_list_keyboard(list_id, items, owner_view=owner_view)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("add_item_"))
async def cb_add_item(callback: CallbackQuery, state: FSMContext):
    try:
        list_id = int(callback.data.split("_")[2])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    # Проверим доступ
    lst = await db.get_list(callback.from_user.id, list_id)
    if not lst or lst[1] != callback.from_user.id:
        await callback.answer("Нет доступа")
        return
    await state.set_state(ListItemAdd.waiting_for_text)
    await state.update_data(list_id=list_id, orig_chat_id=callback.message.chat.id, orig_message_id=callback.message.message_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data=f"list_{list_id}")]])
    await callback.message.answer("Введи текст элемента:", reply_markup=kb)
    await callback.answer()

@router.message(ListItemAdd.waiting_for_text)
async def process_add_item(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    data = await state.get_data()
    list_id = data.get("list_id")
    item_id, error = await db.add_list_item(message.from_user.id, list_id, text)
    # Обновляем карточку
    lst = await db.get_list(message.from_user.id, list_id)
    items = await db.get_list_items(message.from_user.id, list_id)
    txt = format_list_text(lst, items)
    kb = build_list_keyboard(list_id, items, owner_view=True)
    try:
        await message.bot.edit_message_text(
            chat_id=data.get("orig_chat_id"),
            message_id=data.get("orig_message_id"),
            text=txt,
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        pass
    await state.clear()
    if error:
        await message.answer(f"❌ {error}")
    else:
        await message.answer("✅ Элемент добавлен", reply_markup=get_quests_menu_keyboard())

@router.callback_query(F.data.startswith("toggle_item_"))
async def cb_toggle_item(callback: CallbackQuery):
    try:
        _, _, item_id_str, list_id_str = callback.data.split("_", 3)
        item_id = int(item_id_str)
        list_id = int(list_id_str)
    except Exception:
        await callback.answer("Ошибка ID")
        return
    ok = await db.toggle_list_item(callback.from_user.id, item_id)
    if not ok:
        await callback.answer("Ошибка")
        return
    # Перерисуем
    lst = await db.get_list(callback.from_user.id, list_id)
    items = await db.get_list_items(callback.from_user.id, list_id)
    text = format_list_text(lst, items)
    kb = build_list_keyboard(list_id, items, owner_view=(lst and lst[1] == callback.from_user.id))
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("del_item_"))
async def cb_del_item(callback: CallbackQuery):
    try:
        _, _, item_id_str, list_id_str = callback.data.split("_", 3)
        item_id = int(item_id_str)
        list_id = int(list_id_str)
    except Exception:
        await callback.answer("Ошибка ID")
        return
    ok = await db.delete_list_item(callback.from_user.id, item_id)
    if not ok:
        await callback.answer("Ошибка удаления")
        return
    lst = await db.get_list(callback.from_user.id, list_id)
    items = await db.get_list_items(callback.from_user.id, list_id)
    text = format_list_text(lst, items)
    kb = build_list_keyboard(list_id, items, owner_view=(lst and lst[1] == callback.from_user.id))
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer("🗑 Удалено")

@router.callback_query(F.data.startswith("delete_list_"))
async def cb_delete_list(callback: CallbackQuery):
    try:
        list_id = int(callback.data.split("_")[2])
    except Exception:
        await callback.answer("Ошибка ID")
        return
    ok = await db.delete_list(callback.from_user.id, list_id)
    if not ok:
        await callback.answer("Ошибка удаления")
        return
    # Показать мои списки
    await cb_my_lists(callback)

@router.callback_query(F.data.startswith("share_list_"))
async def cb_share_list(callback: CallbackQuery):
    await callback.answer("Функция временно недоступна")
    return

@router.callback_query(F.data.startswith("copy_list_"))
async def cb_copy_list(callback: CallbackQuery):
    await callback.answer("Функция временно недоступна")
    return
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


@router.message((F.text == "📝 Списки") | (F.text.casefold() == "списки"))
async def open_lists_menu(message: Message, state: FSMContext):
    try:
        await state.clear()
    except Exception:
        pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Мои списки", callback_data="my_lists")],
        [InlineKeyboardButton(text="🆕 Создать список", callback_data="create_list_inline")],
        [InlineKeyboardButton(text="📑 Шаблоны", callback_data="list_templates")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
    ])
    await message.answer("📝 Списки — выбери действие:", reply_markup=kb)


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
    await state.set_state(QuestCreation.waiting_for_mode)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Обычный квест", callback_data="mode_regular")],
        [InlineKeyboardButton(text="📅 Ежедневная задача", callback_data="mode_daily")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
    ])
    await message.answer("Выберите режим:", reply_markup=kb)


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
        await state.set_state(QuestCreation.waiting_for_mode)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Обычный квест", callback_data="mode_regular")],
            [InlineKeyboardButton(text="📅 Ежедневная задача", callback_data="mode_daily")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
        ])
        await callback.message.answer("Выберите режим:", reply_markup=kb)
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
        await state.set_state(QuestCreation.waiting_for_mode)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Обычный квест", callback_data="mode_regular")],
            [InlineKeyboardButton(text="📅 Ежедневная задача", callback_data="mode_daily")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
        ])
        await message.answer("Выберите режим:", reply_markup=kb)


@router.callback_query(F.data == "my_quests_inline")
async def cb_my_quests(callback: CallbackQuery):
    user_id = callback.from_user.id
    dailies = await db.get_user_daily_quests(user_id)
    regular = await db.get_user_regular_quests(user_id)
    if not dailies and not regular:
        keyboard = [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]
        await callback.message.edit_text("📋 У тебя пока нет активных квестов!", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        await callback.answer()
        return
    rows = []
    if dailies:
        rows.append([InlineKeyboardButton(text="📅 Ежедневные задачи", callback_data="noop")])
        for q in dailies:
            qid, _, title, qtype = q[0], q[1], q[2], q[3]
            status = "✅" if await db.is_done_today(user_id, qid) else "⏳"
            rows.append([InlineKeyboardButton(text=f"{status} {title}", callback_data=f"quest_{qid}")])
    if regular:
        if dailies:
            rows.append([InlineKeyboardButton(text="────────", callback_data="noop")])
        rows.append([InlineKeyboardButton(text="🎯 Обычные квесты", callback_data="noop")])
        for quest in regular:
            quest_id = quest[0]
            title = quest[2]
            quest_type = quest[3]
            status_emoji = compute_status_emoji(quest[7])
            type_emoji = {"physical": "💪", "intellectual": "📚", "mental": "🧠", "custom": "🎯"}.get(quest_type, "🎯")
            rows.append([InlineKeyboardButton(text=f"{status_emoji} {type_emoji} {title}", callback_data=f"quest_{quest_id}")])
    await callback.message.edit_text("📋 Выбери квест:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
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
    # Для daily продолжаем тем же сценарием, но далее ветвимся на выбор дней/времени
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
    # Если редактируем цель — сразу обновляем квест и карточку
    if data.get("_editing_target"):
        quest_id = data.get("edit_quest_id")
        _, error = await db.update_quest(message.from_user.id, quest_id, target_value=target_value)
        # Обновляем карточку
        quest = await db.get_quest(message.from_user.id, quest_id)
        tz_off, _ = await db.get_user_timezone(message.from_user.id)
        if quest:
            txt = format_quest_text(quest, tz_off)
            completed = bool(quest[6])
            qtype = quest[3]
            tval = int(quest[4])
            try:
                await message.bot.edit_message_text(
                    chat_id=data.get("orig_chat_id"),
                    message_id=data.get("orig_message_id"),
                    text=txt,
                    reply_markup=get_quest_detail_keyboard(quest_id, completed, qtype, tval),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await state.clear()
        if error:
            await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
        else:
            await message.answer("✅ Цель обновлена", reply_markup=get_quests_menu_keyboard())
        return
    # Иначе — сценарий создания
    data = await state.get_data()
    if data.get("is_daily"):
        await start_daily_days_selection(message, state)
    else:
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
    data = await state.get_data()
    if data.get("_editing_target"):
        quest_id = data.get("edit_quest_id")
        _, error = await db.update_quest(message.from_user.id, quest_id, target_value=pages)
        quest = await db.get_quest(message.from_user.id, quest_id)
        tz_off, _ = await db.get_user_timezone(message.from_user.id)
        if quest:
            txt = format_quest_text(quest, tz_off)
            completed = bool(quest[6])
            qtype = quest[3]
            tval = int(quest[4])
            try:
                await message.bot.edit_message_text(
                    chat_id=data.get("orig_chat_id"),
                    message_id=data.get("orig_message_id"),
                    text=txt,
                    reply_markup=get_quest_detail_keyboard(quest_id, completed, qtype, tval),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await state.clear()
        if error:
            await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
        else:
            await message.answer("✅ Цель обновлена", reply_markup=get_quests_menu_keyboard())
        return
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
    data = await state.get_data()
    if data.get("_editing_target"):
        quest_id = data.get("edit_quest_id")
        _, error = await db.update_quest(message.from_user.id, quest_id, target_value=minutes)
        quest = await db.get_quest(message.from_user.id, quest_id)
        tz_off, _ = await db.get_user_timezone(message.from_user.id)
        if quest:
            txt = format_quest_text(quest, tz_off)
            completed = bool(quest[6])
            qtype = quest[3]
            tval = int(quest[4])
            try:
                await message.bot.edit_message_text(
                    chat_id=data.get("orig_chat_id"),
                    message_id=data.get("orig_message_id"),
                    text=txt,
                    reply_markup=get_quest_detail_keyboard(quest_id, completed, qtype, tval),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await state.clear()
        if error:
            await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
        else:
            await message.answer("✅ Цель обновлена", reply_markup=get_quests_menu_keyboard())
        return
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
    data = await state.get_data()
    if data.get("_editing_target"):
        quest_id = data.get("edit_quest_id")
        tval = 100 if has_progress else 0
        _, error = await db.update_quest(callback.from_user.id, quest_id, target_value=tval)
        quest = await db.get_quest(callback.from_user.id, quest_id)
        tz_off, _ = await db.get_user_timezone(callback.from_user.id)
        if quest:
            txt = format_quest_text(quest, tz_off)
            completed = bool(quest[6])
            qtype = quest[3]
            tval2 = int(quest[4])
            try:
                await callback.message.edit_text(txt, reply_markup=get_quest_detail_keyboard(quest_id, completed, qtype, tval2), parse_mode="HTML")
            except Exception:
                pass
        await state.clear()
        if error:
            await callback.message.answer(f"❌ {error}")
        else:
            await callback.message.answer("✅ Цель обновлена")
        await callback.answer()
        return
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
    # Сохраняем 23:59 локального дня в БД, но отображаем "без времени" через флаг has_time=False
    dt_local = datetime(y, m, d, 23, 59, 0)
    if tz_off is None:
        dt_utc_str = dt_local.strftime("%Y-%m-%d %H:%M:%S")
    else:
        dt_utc = dt_local - timedelta(minutes=int(tz_off))
        dt_utc_str = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
    await state.update_data(deadline=dt_utc_str)
    await state.update_data(has_date=True, has_time=False)
    logger.info(f"[DEADLINE] time skipped -> local={dt_local}, utc_str='{dt_utc_str}', tz_off={tz_off}")
    if data.get("_editing_deadline"):
        quest_id = data.get("edit_quest_id")
        _, error = await db.update_quest(callback.from_user.id, quest_id, deadline=dt_utc_str, has_date=True, has_time=False)
        quest = await db.get_quest(callback.from_user.id, quest_id)
        tz_off2, _ = await db.get_user_timezone(callback.from_user.id)
        if quest:
            txt = format_quest_text(quest, tz_off2)
            completed = bool(quest[6])
            qtype = quest[3]
            target_value = int(quest[4])
            try:
                await callback.message.edit_text(txt, reply_markup=get_quest_detail_keyboard(quest_id, completed, qtype, target_value), parse_mode="HTML")
            except Exception:
                pass
        await state.clear()
        if error:
            await callback.message.answer(f"❌ {error}")
        else:
            await callback.message.answer("✅ Дедлайн обновлён")
        await callback.answer()
        return
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
    if data.get("_editing_deadline"):
        quest_id = data.get("edit_quest_id")
        _, error = await db.update_quest(message.from_user.id, quest_id, deadline=dt_utc_str)
        quest = await db.get_quest(message.from_user.id, quest_id)
        tz_off2, _ = await db.get_user_timezone(message.from_user.id)
        if quest:
            txt = format_quest_text(quest, tz_off2)
            completed = bool(quest[6])
            qtype = quest[3]
            target_value = int(quest[4])
            try:
                await message.bot.edit_message_text(
                    chat_id=data.get("orig_chat_id"),
                    message_id=data.get("orig_message_id"),
                    text=txt,
                    reply_markup=get_quest_detail_keyboard(quest_id, completed, qtype, target_value),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await state.clear()
        if error:
            await message.answer(f"❌ {error}", reply_markup=get_quests_menu_keyboard())
        else:
            await message.answer("✅ Дедлайн обновлён", reply_markup=get_quests_menu_keyboard())
        return
    await state.set_state(QuestCreation.waiting_for_comment)
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    shown_time = f"{hh:02d}:{mm:02d}"
    await message.answer(f"📌 Дедлайн установлен: сегодня, {shown_time}.\n\nДобавьте комментарий (введите текст сообщением)", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data == "deadline_skip_all")
async def cb_deadline_skip_all(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(deadline=None, has_date=False, has_time=False)
    if data.get("_editing_deadline"):
        quest_id = data.get("edit_quest_id")
        _, error = await db.update_quest(callback.from_user.id, quest_id, deadline="")
        quest = await db.get_quest(callback.from_user.id, quest_id)
        tz_off2, _ = await db.get_user_timezone(callback.from_user.id)
        if quest:
            txt = format_quest_text(quest, tz_off2)
            completed = bool(quest[6])
            qtype = quest[3]
            target_value = int(quest[4])
            try:
                await callback.message.edit_text(txt, reply_markup=get_quest_detail_keyboard(quest_id, completed, qtype, target_value), parse_mode="HTML")
            except Exception:
                pass
        await state.clear()
        if error:
            await callback.message.answer(f"❌ {error}")
        else:
            await callback.message.answer("✅ Дедлайн удалён")
        await callback.answer()
        return
    await state.set_state(QuestCreation.waiting_for_comment)
    keyboard = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    await callback.message.edit_text("Добавьте комментарий (введите текст сообщением)", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()
