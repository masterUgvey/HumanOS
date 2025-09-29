import sqlite3
import logging
from datetime import datetime, timedelta
from telegram import Bot
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()


class ReminderSystem:
    def __init__(self, db_path='quests.db'):
        self.db_path = db_path
        self.bot = Bot(token=os.getenv('BOT_TOKEN'))

    async def check_deadlines(self):
        """Проверяет дедлайны и отправляет уведомления"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now()

        # Находим квесты с дедлайнами которые еще не завершены
        cursor.execute('''
            SELECT q.quest_id, q.user_id, q.title, q.deadline, u.username 
            FROM quests q 
            JOIN users u ON q.user_id = u.user_id 
            WHERE q.deadline IS NOT NULL AND q.completed = FALSE
        ''')

        quests = cursor.fetchall()
        conn.close()

        notifications_sent = 0

        for quest in quests:
            quest_id, user_id, title, deadline_str, username = quest

            # Пробуем оба формата даты
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d")

        try:
            time_diff = deadline - now
            
            # 1. УВЕДОМЛЕНИЕ В ДЕНЬ ДЕДЛАЙНА (если дедлайн не сегодня)
            if deadline.date() == now.date() and deadline > now:
                try:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=f"📅 Напоминание: сегодня дедлайн квеста '{title}'!\n" +
                            (f"⏰ До конца: {deadline.strftime('%H:%M')}" if deadline.hour != 0 or deadline.minute != 0 else "")
                    )
                    notifications_sent += 1
                except Exception as e:
                    logging.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")

            # 2. УВЕДОМЛЕНИЕ ЗА 10 МИНУТ ДО ДЕДЛАЙНА
            if timedelta(minutes=0) <= time_diff <= timedelta(minutes=10):
                try:
                    minutes_left = int(time_diff.total_seconds() / 60)
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=f"⏰ Срочное напоминание: до дедлайна квеста '{title}' осталось {minutes_left} минут!"
                    )
                    notifications_sent += 1
                except Exception as e:
                    logging.error(f"Не удалось отправить 10-минутное уведомление: {e}")

            # 3. УВЕДОМЛЕНИЕ О ПРОСРОЧКЕ
            if time_diff < timedelta(0):
                overdue_hours = abs(time_diff.total_seconds() / 3600)
                
                # Если указано время и прошло 2 часа
                if (deadline.hour != 0 or deadline.minute != 0) and timedelta(hours=2) <= abs(time_diff) <= timedelta(hours=3):
                    try:
                        await self.bot.send_message(
                            chat_id=user_id,
                            text=f"❌ Квест '{title}' просрочен на 2 часа!"
                        )
                        notifications_sent += 1
                    except Exception as e:
                        logging.error(f"Не удалось отправить уведомление о просрочке: {e}")
                # Если указан только день - уведомляем на следующий день
                elif deadline.hour == 0 and deadline.minute == 0 and deadline.date() < now.date():
                    try:
                        await self.bot.send_message(
                            chat_id=user_id,
                            text=f"❌ Квест '{title}' просрочен! Дедлайн был {deadline.strftime('%d.%m.%Y')}"
                        )
                        notifications_sent += 1
                    except Exception as e:
                        logging.error(f"Не удалось отправить уведомление о просрочке: {e}")
            
        except Exception as e:
            logging.error(f"Ошибка обработки дедлайна квеста {quest_id}: {e}")

        return notifications_sent


