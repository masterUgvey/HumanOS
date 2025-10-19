# -*- coding: utf-8 -*-
"""
Скрипт установки нового бота HumanOS
Запуск: python SETUP_BOT.py
"""

import os
import shutil

print("="*60)
print("Установка нового бота HumanOS")
print("="*60)

# Создаем резервную копию
if os.path.exists('bot.py'):
    if not os.path.exists('bot_old_backup.py'):
        shutil.copy('bot.py', 'bot_old_backup.py')
        print("✅ Резервная копия создана")

# Код нового бота (часть 1 - импорты и настройки)
code_part1 = """import os
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from reminder import ReminderSystem
from database import Database

load_dotenv()
db = Database()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("Токен не найден! Проверь файл .env")

QUEST_TYPES = {
    "physical": "💪 Физическая задача",
    "intellectual": "📚 Интеллектуальная задача",
    "mental": "🧠 Ментальная задача",
    "custom": "🎯 Произвольная задача"
}
"""

# Сохраняем части в отдельные файлы
with open('_part1.txt', 'w', encoding='utf-8') as f:
    f.write(code_part1)

print("📝 Часть 1 сохранена")

# Загружаем остальные части из файлов parts
parts = []
for i in range(1, 6):
    filename = f'_part{i}.txt'
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            parts.append(f.read())
        print(f"✅ Загружена часть {i}")

if len(parts) < 5:
    print("⚠️ Не все части найдены, использую встроенный код...")
    # Здесь будет полный код если файлы не найдены
    exec(open('_generate_full_bot.py').read())
else:
    # Собираем все части
    full_code = ''.join(parts)
    
    # Записываем bot.py
    with open('bot.py', 'w', encoding='utf-8') as f:
        f.write(full_code)
    
    print(f"\n✅ bot.py создан ({len(full_code)} символов)")
    
    # Проверка синтаксиса
    try:
        compile(full_code, 'bot.py', 'exec')
        print("✅ Синтаксис корректен!")
    except SyntaxError as e:
        print(f"❌ Ошибка: {e}")

print("\n"+"="*60)
print("✅ Установка завершена!")
print("="*60)
print("\nЗапуск: python bot.py")
