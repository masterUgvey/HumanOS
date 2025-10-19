import sqlite3
import logging
import re
from datetime import datetime

class Database:
    def __init__(self, db_path='quests_new.db'):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица квестов с новой структурой
        cursor.execute('''
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
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        logging.info("База данных инициализирована")

    def validate_input(self, text, field_name="input"):
        """Проверка ввода на SQL-инъекции и опасные символы"""
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
                return False, f"Некорректный ввод для поля '{field_name}'. Обнаружены запрещенные символы или команды."
        
        # Проверка длины
        if len(text) > 500:
            return False, f"Текст слишком длинный (максимум 500 символов)"
        
        return True, ""

    def add_user(self, user_id, username):
        """Добавление нового пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)',
            (user_id, username)
        )
        conn.commit()
        conn.close()

    def create_quest(self, user_id, title, quest_type, target_value, deadline=None, comment=None):
        """Создание квеста с валидацией"""
        # Валидация названия
        is_valid, error_msg = self.validate_input(title, "Название")
        if not is_valid:
            return None, error_msg
        
        # Валидация комментария если есть
        if comment:
            is_valid, error_msg = self.validate_input(comment, "Комментарий")
            if not is_valid:
                return None, error_msg
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''INSERT INTO quests (user_id, title, quest_type, target_value, deadline, comment) 
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (user_id, title, quest_type, target_value, deadline, comment)
            )
            quest_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return quest_id, None
        except Exception as e:
            conn.close()
            logging.error(f"Ошибка создания квеста: {e}")
            return None, "Ошибка при создании квеста"

    def get_user_quests(self, user_id):
        """Получение всех активных квестов пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM quests WHERE user_id = ? AND completed = FALSE ORDER BY created_at DESC',
            (user_id,)
        )
        quests = cursor.fetchall()
        conn.close()
        return quests

    def get_quest(self, user_id, quest_id):
        """Получение конкретного квеста пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM quests WHERE quest_id = ? AND user_id = ?',
            (quest_id, user_id)
        )
        quest = cursor.fetchone()
        conn.close()
        return quest

    def update_quest_progress(self, user_id, quest_id, new_value):
        """Обновляет прогресс квеста"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Получаем целевое значение
        cursor.execute('SELECT target_value FROM quests WHERE quest_id = ? AND user_id = ?', (quest_id, user_id))
        result = cursor.fetchone()
        if not result:
            conn.close()
            return None
        
        target_value = result[0]
        # Ограничиваем значение целевым
        if new_value > target_value:
            new_value = target_value
        
        # Обновляем значение в базе
        cursor.execute('UPDATE quests SET current_value = ? WHERE quest_id = ? AND user_id = ?', (new_value, quest_id, user_id))
        
        # Если достигли цели - помечаем как завершенный
        if new_value >= target_value:
            cursor.execute('UPDATE quests SET completed = TRUE WHERE quest_id = ? AND user_id = ?', (quest_id, user_id))
        
        conn.commit()
        
        # Возвращаем обновленный квест
        cursor.execute('SELECT * FROM quests WHERE quest_id = ? AND user_id = ?', (quest_id, user_id))
        quest = cursor.fetchone()
        conn.close()
        return quest

    def complete_quest(self, user_id, quest_id):
        """Отмечает квест как выполненный"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('UPDATE quests SET completed = TRUE, current_value = target_value WHERE quest_id = ? AND user_id = ?', (quest_id, user_id))
        conn.commit()
        
        # Возвращаем обновленный квест
        cursor.execute('SELECT * FROM quests WHERE quest_id = ? AND user_id = ?', (quest_id, user_id))
        quest = cursor.fetchone()
        conn.close()
        return quest

    def delete_quest(self, user_id, quest_id):
        """Удаляет квест пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM quests WHERE quest_id = ? AND user_id = ?', (quest_id, user_id))
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        return deleted

    def update_quest(self, user_id, quest_id, title=None, target_value=None, deadline=None, comment=None):
        """Обновляет параметры квеста с валидацией"""
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
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if title is not None:
            updates.append('title = ?')
            params.append(title)
        if target_value is not None:
            updates.append('target_value = ?')
            params.append(target_value)
        if deadline is not None:
            updates.append('deadline = ?')
            params.append(deadline)
        if comment is not None:
            updates.append('comment = ?')
            params.append(comment)
        
        if not updates:
            conn.close()
            return None, "Нет данных для обновления"
        
        params.extend([quest_id, user_id])
        query = f'UPDATE quests SET {', '.join(updates)} WHERE quest_id = ? AND user_id = ?'
        
        try:
            cursor.execute(query, params)
            conn.commit()
            
            # Возвращаем обновленный квест
            cursor.execute('SELECT * FROM quests WHERE quest_id = ? AND user_id = ?', (quest_id, user_id))
            quest = cursor.fetchone()
            conn.close()
            return quest, None
        except Exception as e:
            conn.close()
            logging.error(f"Ошибка обновления квеста: {e}")
            return None, "Ошибка при обновлении квеста"

    def get_quests_with_deadlines(self):
        """Получение всех квестов с дедлайнами для системы напоминаний"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM quests WHERE deadline IS NOT NULL AND completed = FALSE'
        )
        quests = cursor.fetchall()
        conn.close()
        return quests