"""
Асинхронный модуль для работы с базой данных SQLite
Управляет квестами пользователей с валидацией данных
"""

import re
import aiosqlite
from datetime import datetime
from typing import Optional, Tuple, List
from loguru import logger
from config import config


class Database:
    """Класс для асинхронной работы с базой данных квестов"""
    
    def __init__(self, db_path: str = None):
        """
        Инициализация базы данных
        
        Args:
            db_path: Путь к файлу базы данных (по умолчанию из config)
        """
        self.db_path = db_path or config.DATABASE_PATH
        logger.info(f"📊 Инициализация базы данных: {self.db_path}")
    
    async def init_db(self):
        """Создание таблиц в базе данных"""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица пользователей
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    tz_offset_minutes INTEGER,
                    tz_prompted BOOLEAN DEFAULT FALSE
                )
            ''')

            # Проверяем существующие столбцы таблицы quests
            cursor = await db.execute("PRAGMA table_info('quests')")
            existing_columns_info = await cursor.fetchall()
            existing_columns = {row[1] for row in existing_columns_info}  # name at index 1

            if not existing_columns:
                # Таблица не существует — создаем по актуальной схеме
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS quests (
                        quest_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        title TEXT NOT NULL,
                        quest_type TEXT NOT NULL,
                        target_value INTEGER NOT NULL,
                        current_value INTEGER DEFAULT 0,
                        completed BOOLEAN DEFAULT FALSE,
                        deadline TIMESTAMP,
                        comment TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        has_date BOOLEAN DEFAULT FALSE,
                        has_time BOOLEAN DEFAULT FALSE,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
            else:
                # Легкая миграция: добавляем недостающие колонки
                migrations = []
                if 'current_value' not in existing_columns:
                    migrations.append("ALTER TABLE quests ADD COLUMN current_value INTEGER DEFAULT 0")
                if 'completed' not in existing_columns:
                    migrations.append("ALTER TABLE quests ADD COLUMN completed BOOLEAN DEFAULT FALSE")
                if 'deadline' not in existing_columns:
                    migrations.append("ALTER TABLE quests ADD COLUMN deadline TIMESTAMP")
                if 'comment' not in existing_columns:
                    migrations.append("ALTER TABLE quests ADD COLUMN comment TEXT")
                if 'has_date' not in existing_columns:
                    migrations.append("ALTER TABLE quests ADD COLUMN has_date BOOLEAN DEFAULT FALSE")
                if 'has_time' not in existing_columns:
                    migrations.append("ALTER TABLE quests ADD COLUMN has_time BOOLEAN DEFAULT FALSE")

                for sql in migrations:
                    try:
                        await db.execute(sql)
                        logger.info(f"🧩 Применена миграция: {sql}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка миграции '{sql}': {e}")

                if migrations:
                    # Проставим дефолты там, где NULL после добавления колонок
                    try:
                        await db.execute("UPDATE quests SET current_value = COALESCE(current_value, 0)")
                        await db.execute("UPDATE quests SET completed = COALESCE(completed, FALSE)")
                        # Инициализируем флаги дат/времени на основе существующего дедлайна
                        await db.execute("UPDATE quests SET has_date = CASE WHEN deadline IS NOT NULL THEN TRUE ELSE FALSE END WHERE has_date IS NULL OR has_date = FALSE")
                        await db.execute("UPDATE quests SET has_time = CASE WHEN deadline IS NOT NULL AND TIME(deadline) != '00:00:00' THEN TRUE ELSE FALSE END WHERE has_time IS NULL OR has_time = FALSE")
                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка установки значений по умолчанию: {e}")

            # Миграции для таблицы users
            try:
                cursor_u = await db.execute("PRAGMA table_info('users')")
                cols_u_info = await cursor_u.fetchall()
                cols_u = {row[1] for row in cols_u_info}
                if 'tz_offset_minutes' not in cols_u:
                    await db.execute("ALTER TABLE users ADD COLUMN tz_offset_minutes INTEGER")
                if 'tz_prompted' not in cols_u:
                    await db.execute("ALTER TABLE users ADD COLUMN tz_prompted BOOLEAN DEFAULT FALSE")
                if 'log_subscribed' not in cols_u:
                    await db.execute("ALTER TABLE users ADD COLUMN log_subscribed BOOLEAN DEFAULT FALSE")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка миграции users: {e}")

            await db.commit()
            logger.info("✅ База данных инициализирована")
    
    def validate_input(self, text: str, field_name: str = "input") -> Tuple[bool, str]:
        """
        Валидация пользовательского ввода на SQL-инъекции и опасные символы
        
        Args:
            text: Текст для проверки
            field_name: Название поля (для сообщения об ошибке)
            
        Returns:
            Tuple[bool, str]: (валиден ли ввод, сообщение об ошибке)
        """
        if not text:
            return False, "Поле не может быть пустым"
        
        # Проверка на SQL-инъекции
        dangerous_patterns = [
            r"(--|;|'|\"|\\|/\*|\*/|xp_|sp_|exec|execute|select|insert|update|delete|drop|create|alter|union|script|javascript|<script)",
            r"(\bor\b.*=|\band\b.*=|\bselect\b|\bunion\b|\binsert\b|\bupdate\b|\bdelete\b|\bdrop\b)"
        ]
        
        text_lower = text.lower()
        for pattern in dangerous_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return False, f"Некорректный ввод для поля '{field_name}'. Обнаружены запрещенные символы."
        
        # Проверка длины
        if len(text) > 500:
            return False, f"Текст слишком длинный (максимум 500 символов)"
        
        return True, ""
    
    async def add_user(self, user_id: int, username: str):
        """
        Добавление нового пользователя в базу данных
        
        Args:
            user_id: ID пользователя Telegram
            username: Имя пользователя
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)',
                (user_id, username)
            )
            await db.commit()
            logger.debug(f"👤 Пользователь {username} (ID: {user_id}) добавлен/обновлен")

    async def get_user_timezone(self, user_id: int) -> Tuple[Optional[int], bool]:
        """Получить смещение таймзоны и признак, что пользователя уже спрашивали"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT tz_offset_minutes, COALESCE(tz_prompted, FALSE) FROM users WHERE user_id = ?', (user_id,))
            row = await cursor.fetchone()
            if not row:
                return None, False
            return row[0], bool(row[1])

    async def set_user_timezone(self, user_id: int, offset_minutes: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('UPDATE users SET tz_offset_minutes = ?, tz_prompted = TRUE WHERE user_id = ?', (offset_minutes, user_id))
            await db.commit()

    async def set_user_tz_prompted(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('UPDATE users SET tz_prompted = TRUE WHERE user_id = ?', (user_id,))
            await db.commit()

    async def set_log_subscription(self, user_id: int, subscribed: bool) -> None:
        """Включить/выключить подписку на RT-логи для пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('UPDATE users SET log_subscribed = ? WHERE user_id = ?', (int(bool(subscribed)), user_id))
            await db.commit()

    async def get_log_subscribers(self) -> List[int]:
        """Получить user_id всех подписчиков логов"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT user_id FROM users WHERE COALESCE(log_subscribed, FALSE) = TRUE')
            rows = await cursor.fetchall()
            return [r[0] for r in rows]
    
    async def create_quest(
        self,
        user_id: int,
        title: str,
        quest_type: str,
        target_value: int,
        deadline: Optional[str] = None,
        comment: Optional[str] = None,
        has_date: Optional[bool] = None,
        has_time: Optional[bool] = None
    ) -> Tuple[Optional[int], Optional[str]]:
        """
        Создание нового квеста с валидацией
        
        Args:
            user_id: ID пользователя
            title: Название квеста
            quest_type: Тип квеста (physical, intellectual, mental, custom)
            target_value: Целевое значение
            deadline: Дедлайн (опционально)
            comment: Комментарий (опционально)
            
        Returns:
            Tuple[Optional[int], Optional[str]]: (ID квеста, сообщение об ошибке)
        """
        # Валидация названия
        is_valid, error_msg = self.validate_input(title, "Название")
        if not is_valid:
            return None, error_msg
        
        # Валидация комментария
        if comment:
            is_valid, error_msg = self.validate_input(comment, "Комментарий")
            if not is_valid:
                return None, error_msg
        
        try:
            # Нормализуем пустые значения
            if not deadline or str(deadline).strip() == "" or str(deadline).strip().lower() in {"none", "null", "0"}:
                deadline = None
            else:
                # Если передана только дата, приводим к 'YYYY-MM-DD 00:00:00'
                d_str = str(deadline).strip()
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}$", d_str):
                    deadline = f"{d_str} 00:00:00"
            # Вычислим флаги has_date/has_time, если не переданы
            if has_date is None or has_time is None:
                if deadline is None:
                    has_date = False if has_date is None else has_date
                    has_time = False if has_time is None else has_time
                else:
                    # deadline c временем или без
                    try:
                        tpart = str(deadline).strip().split(" ")[1] if " " in str(deadline).strip() else "00:00:00"
                    except Exception:
                        tpart = "00:00:00"
                    if has_date is None:
                        has_date = True
                    if has_time is None:
                        has_time = (tpart != "00:00:00")
            # Если флаги явно указаны и противоречат deadline, синхронизируем:
            if not has_date:
                deadline = None
            elif has_date and not has_time and deadline:
                # Принудительно обнуляем время, если передано
                try:
                    d = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
                    deadline = f"{d.strftime('%Y-%m-%d')} 00:00:00"
                except Exception:
                    pass
            # Не сохраняем комментарий, если он пустой или выглядит как дата/дата-время
            if comment is not None:
                c = str(comment).strip()
                if c == "":
                    comment = None
                else:
                    date_like = [
                        r"^\d{4}-\d{2}-\d{2}$",
                        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$",
                        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                        r"^\d{2}\.\d{2}\.\d{2}$",
                        r"^\d{2}\.\d{2}\.\d{2} \d{2}:\d{2}$",
                    ]
                    if any(re.fullmatch(p, c) for p in date_like) or (deadline and c == str(deadline)):
                        comment = None
            logger.info(f"[DB] create_quest normalized -> user_id={user_id}, title='{title}', type='{quest_type}', target={target_value}, deadline='{deadline}', comment='{comment}', has_date={has_date}, has_time={has_time}")
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    '''INSERT INTO quests (user_id, title, quest_type, target_value, deadline, comment, has_date, has_time) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id, title, quest_type, target_value, deadline, comment, int(bool(has_date)), int(bool(has_time)))
                )
                quest_id = cursor.lastrowid
                await db.commit()
                logger.info(f"✅ Квест '{title}' создан (ID: {quest_id}) для пользователя {user_id}")
                return quest_id, None
        except Exception as e:
            logger.error(f"❌ Ошибка создания квеста: {e}")
            return None, "Ошибка при создании квеста"
    
    async def get_user_quests(self, user_id: int) -> List[tuple]:
        """
        Получение всех активных квестов пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            List[tuple]: Список квестов
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT quest_id, user_id, title, quest_type, target_value, current_value, completed, deadline, comment, created_at, has_date, has_time '
                'FROM quests WHERE user_id = ? AND completed = FALSE ORDER BY created_at DESC',
                (user_id,)
            )
            quests = await cursor.fetchall()
            return quests

    async def sanitize_existing_data(self) -> None:
        """Привести БД в порядок:
        - Удалить датоподобные комментарии
        - Нормализовать дедлайны с только датой -> 'YYYY-MM-DD 00:00:00'
        - Исправить баг 'вчера + время' на дату создания '00:00:00'
        """
        async with aiosqlite.connect(self.db_path) as db:
            total = 0
            # 1) Удаляем комментарии, похожие на дату, или совпадающие с дедлайном
            # Используем GLOB/LIKE из-за отсутствия REGEXP в SQLite по умолчанию
            res = await db.execute(
                """
                UPDATE quests
                SET comment = NULL
                WHERE comment IS NOT NULL AND (
                    comment = deadline OR
                    comment GLOB '____-__-__' OR
                    comment GLOB '____-__-__ *__:__*' OR
                    comment GLOB '__.__.__' OR
                    comment GLOB '__.__.__ *__:__*'
                )
                """
            )
            c1 = res.rowcount if res.rowcount is not None else 0
            total += c1
            logger.info(f"[SANITIZE] cleared date-like comments: {c1}")

            # 2) Нормализуем дедлайны, где указана только дата (10 символов)
            res = await db.execute(
                """
                UPDATE quests
                SET deadline = deadline || ' 00:00:00'
                WHERE deadline IS NOT NULL AND LENGTH(deadline) = 10 AND deadline GLOB '____-__-__'
                """
            )
            c2 = res.rowcount if res.rowcount is not None else 0
            total += c2
            logger.info(f"[SANITIZE] normalized pure date deadlines to 00:00:00: {c2}")

            # 3) Исправляем дедлайны со сдвигом на 'вчера' с временем — ставим дату создания 00:00:00
            # Признак бага: date(deadline) = date(created_at, '-1 day') и time(deadline) != '00:00:00'
            res = await db.execute(
                """
                UPDATE quests
                SET deadline = DATE(created_at) || ' 00:00:00'
                WHERE deadline IS NOT NULL
                  AND TIME(deadline) != '00:00:00'
                  AND DATE(deadline) = DATE(created_at, '-1 day')
                """
            )
            c3 = res.rowcount if res.rowcount is not None else 0
            total += c3
            logger.info(f"[SANITIZE] fixed previous-day-with-time deadlines: {c3}")

            await db.commit()
            logger.info(f"[SANITIZE] done. total rows affected: {total}")
    
    async def get_quest(self, user_id: int, quest_id: int) -> Optional[tuple]:
        """
        Получение конкретного квеста пользователя
        
        Args:
            user_id: ID пользователя
            quest_id: ID квеста
            
        Returns:
            Optional[tuple]: Данные квеста или None
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT quest_id, user_id, title, quest_type, target_value, current_value, completed, deadline, comment, created_at, has_date, has_time '
                'FROM quests WHERE quest_id = ? AND user_id = ?',
                (quest_id, user_id)
            )
            quest = await cursor.fetchone()
            return quest
    
    async def update_quest_progress(
        self,
        user_id: int,
        quest_id: int,
        new_value: int
    ) -> Optional[tuple]:
        """
        Обновление прогресса квеста
        
        Args:
            user_id: ID пользователя
            quest_id: ID квеста
            new_value: Новое значение прогресса
            
        Returns:
            Optional[tuple]: Обновленный квест или None
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Получаем целевое значение
            cursor = await db.execute(
                'SELECT target_value FROM quests WHERE quest_id = ? AND user_id = ?',
                (quest_id, user_id)
            )
            result = await cursor.fetchone()
            
            if not result:
                return None
            
            target_value = result[0]
            # Ограничиваем значение целевым
            if new_value > target_value:
                new_value = target_value
            
            # Обновляем значение
            await db.execute(
                'UPDATE quests SET current_value = ? WHERE quest_id = ? AND user_id = ?',
                (new_value, quest_id, user_id)
            )
            
            # Если достигли цели - помечаем как завершенный
            if new_value >= target_value:
                await db.execute(
                    'UPDATE quests SET completed = TRUE WHERE quest_id = ? AND user_id = ?',
                    (quest_id, user_id)
                )
            
            await db.commit()
            
            # Возвращаем обновленный квест
            cursor = await db.execute(
                'SELECT * FROM quests WHERE quest_id = ? AND user_id = ?',
                (quest_id, user_id)
            )
            quest = await cursor.fetchone()
            logger.info(f"📈 Прогресс квеста {quest_id} обновлен: {new_value}/{target_value}")
            return quest
    
    async def complete_quest(self, user_id: int, quest_id: int) -> Optional[tuple]:
        """
        Отметить квест как выполненный
        
        Args:
            user_id: ID пользователя
            quest_id: ID квеста
            
        Returns:
            Optional[tuple]: Обновленный квест или None
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE quests SET completed = TRUE, current_value = target_value WHERE quest_id = ? AND user_id = ?',
                (quest_id, user_id)
            )
            await db.commit()
            
            cursor = await db.execute(
                'SELECT quest_id, user_id, title, quest_type, target_value, current_value, completed, deadline, comment, created_at, has_date, has_time '
                'FROM quests WHERE quest_id = ? AND user_id = ?',
                (quest_id, user_id)
            )
            quest = await cursor.fetchone()
            logger.info(f"✅ Квест {quest_id} завершен пользователем {user_id}")
            return quest
    
    async def delete_quest(self, user_id: int, quest_id: int) -> bool:
        """
        Удаление квеста пользователя
        
        Args:
            user_id: ID пользователя
            quest_id: ID квеста
            
        Returns:
            bool: True если квест удален
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'DELETE FROM quests WHERE quest_id = ? AND user_id = ?',
                (quest_id, user_id)
            )
            await db.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"🗑️ Квест {quest_id} удален пользователем {user_id}")
            return deleted
    
    async def update_quest(
        self,
        user_id: int,
        quest_id: int,
        title: Optional[str] = None,
        target_value: Optional[int] = None,
        deadline: Optional[str] = None,
        comment: Optional[str] = None
    ) -> Tuple[Optional[tuple], Optional[str]]:
        """
        Обновление параметров квеста с валидацией
        
        Args:
            user_id: ID пользователя
            quest_id: ID квеста
            title: Новое название (опционально)
            target_value: Новое целевое значение (опционально)
            deadline: Новый дедлайн (опционально)
            comment: Новый комментарий (опционально)
            
        Returns:
            Tuple[Optional[tuple], Optional[str]]: (Обновленный квест, сообщение об ошибке)
        """
        # Валидация названия
        if title is not None:
            is_valid, error_msg = self.validate_input(title, "Название")
            if not is_valid:
                return None, error_msg
        
        # Валидация комментария
        if comment is not None:
            is_valid, error_msg = self.validate_input(comment, "Комментарий")
            if not is_valid:
                return None, error_msg
        
        updates = []
        params = []
        
        if title is not None:
            updates.append('title = ?')
            params.append(title)
        if target_value is not None:
            updates.append('target_value = ?')
            params.append(target_value)
        # Обработка deadline: пустая строка означает очистку поля (NULL)
        if deadline is not None:
            if isinstance(deadline, str):
                dstr = deadline.strip()
                if dstr == "":
                    updates.append('deadline = NULL')
                else:
                    # Если только дата, приводим к 'YYYY-MM-DD 00:00:00'
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}$", dstr):
                        dstr = f"{dstr} 00:00:00"
                    updates.append('deadline = ?')
                    params.append(dstr)
            else:
                updates.append('deadline = ?')
                params.append(deadline)
        # Обработка comment: пустая строка означает очистку поля (NULL) и фильтрация датоподобных значений
        if comment is not None:
            if isinstance(comment, str):
                c = comment.strip()
                if c == "":
                    updates.append('comment = NULL')
                else:
                    date_like = [
                        r"^\d{4}-\d{2}-\d{2}$",
                        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$",
                        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                        r"^\d{2}\.\d{2}\.\d{2}$",
                        r"^\d{2}\.\d{2}\.\d{2} \d{2}:\d{2}$",
                    ]
                    if any(re.fullmatch(p, c) for p in date_like):
                        updates.append('comment = NULL')
                    else:
                        updates.append('comment = ?')
                        params.append(c)
            else:
                updates.append('comment = ?')
                params.append(comment)
        logger.info(f"[DB] update_quest -> quest_id={quest_id}, user_id={user_id}, updates={updates}, params={params}")
        
        if not updates:
            return None, "Нет данных для обновления"
        
        params.extend([quest_id, user_id])
        query = f'UPDATE quests SET {", ".join(updates)} WHERE quest_id = ? AND user_id = ?'
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(query, params)
                await db.commit()
                
                cursor = await db.execute(
                    'SELECT quest_id, user_id, title, quest_type, target_value, current_value, completed, deadline, comment, created_at, has_date, has_time '
                    'FROM quests WHERE quest_id = ? AND user_id = ?',
                    (quest_id, user_id)
                )
                quest = await cursor.fetchone()
                logger.info(f"✏️ Квест {quest_id} обновлен пользователем {user_id}")
                return quest, None
        except Exception as e:
            logger.error(f"❌ Ошибка обновления квеста: {e}")
            return None, "Ошибка при обновлении квеста"
    
    async def get_quests_with_deadlines(self) -> List[tuple]:
        """
        Получение всех квестов с дедлайнами для системы напоминаний
        
        Returns:
            List[tuple]: Список квестов с дедлайнами
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT quest_id, user_id, title, quest_type, target_value, current_value, completed, deadline, comment, created_at, has_date, has_time '
                'FROM quests WHERE deadline IS NOT NULL AND completed = FALSE'
            )
            quests = await cursor.fetchall()
            return quests


# Создаем глобальный экземпляр базы данных
db = Database()
