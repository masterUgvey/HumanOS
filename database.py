import sqlite3
import logging
from datetime import datetime

class Database:
    def __init__(self, db_path='quests.db'):
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
                level INTEGER DEFAULT 1,
                experience INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица квестов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quests (
                quest_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT NOT NULL,
                quest_type TEXT NOT NULL,
                target_value INTEGER,
                current_value INTEGER DEFAULT 0,
                completed BOOLEAN DEFAULT FALSE,
                deadline TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        # Попытка добавить колонку deadline, если таблица уже существовала без неё
        try:
            cursor.execute('ALTER TABLE quests ADD COLUMN deadline TIMESTAMP')
        except Exception:
            pass
        
        conn.commit()
        conn.close()
        logging.info("База данных инициализирована")

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

    def create_quest(self, user_id, title, quest_type, target_value, deadline=None):
        """Создание квеста с опциональным дедлайном"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO quests (user_id, title, quest_type, target_value, deadline) 
               VALUES (?, ?, ?, ?, ?)''',
            (user_id, title, quest_type, target_value, deadline)
        )
        conn.commit()
        conn.close()

    def get_user_quests(self, user_id):
        """Получение всех квестов пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM quests WHERE user_id = ? AND completed = FALSE ORDER BY created_at',
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

    def update_quest_progress(self, user_id, quest_id, delta):
        """Увеличивает текущее значение квеста на delta и возвращает обновленный квест"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Получаем текущее значение
        cursor.execute('SELECT current_value FROM quests WHERE quest_id = ? AND user_id = ?', (quest_id, user_id))
        result = cursor.fetchone()
        if not result:
            conn.close()
            return None
        current_value = result[0]
        new_value = current_value + delta
        print(f"DEBUG: Updating quest {quest_id} from {current_value} to {new_value}")
        # Обновляем значение в базе
        cursor.execute('UPDATE quests SET current_value = ? WHERE quest_id = ? AND user_id = ?', (new_value, quest_id, user_id))
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
        cursor.execute('UPDATE quests SET completed = TRUE WHERE quest_id = ? AND user_id = ?', (quest_id, user_id))
        conn.commit()
        # Возвращаем обновленный квест
        cursor.execute('SELECT * FROM quests WHERE quest_id = ? AND user_id = ?', (quest_id, user_id))
        quest = cursor.fetchone()
        conn.close()
        return quest