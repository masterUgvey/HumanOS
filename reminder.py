import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Set

class ReminderSystem:
    def __init__(self, bot, database):
        self.bot = bot
        self.database = database
        self.sent_reminders: Dict[int, Set[str]] = {}  # quest_id -> set of reminder types sent
        self.is_running = False

    async def start(self):
        """Запуск системы напоминаний"""
        self.is_running = True
        logging.info("Система напоминаний запущена")
        await self.check_reminders_loop()

    async def stop(self):
        """Остановка системы напоминаний"""
        self.is_running = False
        logging.info("Система напоминаний остановлена")

    async def check_reminders_loop(self):
        """Основной цикл проверки напоминаний"""
        while self.is_running:
            try:
                await self.check_and_send_reminders()
            except Exception as e:
                logging.error(f"Ошибка в системе напоминаний: {e}")

            # Проверяем каждые 5 минут
            await asyncio.sleep(300)

    async def check_and_send_reminders(self):
        """Проверка и отправка напоминаний"""
        quests = self.database.get_quests_with_deadlines()
        now = datetime.now()

        for quest in quests:
            quest_id = quest[0]
            user_id = quest[1]
            title = quest[2]
            deadline_str = quest[7]

            if not deadline_str:
                continue

            try:
                # Парсим дедлайн
                try:
                    deadline = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    deadline = datetime.strptime(deadline_str, "%Y-%m-%d")
                    deadline = deadline.replace(hour=23, minute=59, second=59)

                # Инициализируем множество отправленных напоминаний для этого квеста
                if quest_id not in self.sent_reminders:
                    self.sent_reminders[quest_id] = set()

                # Проверяем, нужно ли отправить напоминание
                time_until_deadline = deadline - now

                # Напоминание за день до дедлайна (если задача на несколько дней)
                deadline_date = deadline.date()
                today_date = now.date()

                # Если дедлайн сегодня
                if deadline_date == today_date:
                    # Напоминание за час до дедлайна
                    if timedelta(minutes=55) <= time_until_deadline <= timedelta(hours=1, minutes=5):
                        if "hour_before" not in self.sent_reminders[quest_id]:
                            await self.send_reminder(user_id, title, "за час до дедлайна", deadline)
                            self.sent_reminders[quest_id].add("hour_before")

                # Если дедлайн завтра
                elif deadline_date == (today_date + timedelta(days=1)):
                    # Напоминание за день
                    if "day_before" not in self.sent_reminders[quest_id]:
                        # Отправляем в начале дня дедлайна (с 00:00 до 01:00)
                        if now.hour == 0:
                            await self.send_reminder(user_id, title, "за день до дедлайна", deadline)
                            self.sent_reminders[quest_id].add("day_before")

                # Если квест просрочен, удаляем из отслеживания
                if time_until_deadline < timedelta(0):
                    if quest_id in self.sent_reminders:
                        del self.sent_reminders[quest_id]

            except Exception as e:
                logging.error(f"Ошибка обработки напоминания для квеста {quest_id}: {e}")

    async def send_reminder(self, user_id, quest_title, reminder_type, deadline):
        """Отправка напоминания пользователю"""
        try:
            deadline_str = deadline.strftime("%d.%m.%Y %H:%M") if deadline.hour != 0 or deadline.minute != 0 else deadline.strftime("%d.%m.%Y")
            message = f"⏰ Напоминание {reminder_type}!\n\n🎯 Квест: {quest_title}\n📅 Дедлайн: {deadline_str}"

            await self.bot.send_message(chat_id=user_id, text=message)
            logging.info(f"Отправлено напоминание пользователю {user_id} для квеста '{quest_title}'")
        except Exception as e:
            logging.error(f"Ошибка отправки напоминания пользователю {user_id}: {e}")


