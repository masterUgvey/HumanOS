import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Загружаем переменные из .env файла
load_dotenv()

# Включаем логирование, чтобы видеть ошибки
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Читаем токен из переменной окружения
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("Токен не найден! Проверь файл .env")

# Функция-обработчик команды /start
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    
    # Создаем инлайн-кнопки
    keyboard = [
        [InlineKeyboardButton("📋 Мои квесты", callback_data="my_quests")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = f"""
Привет, {user_name}! 🚀

Я — твой проводник на пути к Сверхчеловеку. 
Вместе мы превратим рутину в увлекательную игру!

Выбери действие:
    """
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
# Функция-обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    Доступные команды:
    /start - Начать работу
    /help - Получить справку
    """
    await update.message.reply_text(help_text)

# Функция для обработки обычных текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    response = f"Ты написал: '{text}'. Пока я умею только на команды отвечать."
    await update.message.reply_text(response)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "my_quests":
        await query.edit_message_text("📋 Раздел 'Мои квесты' в разработке...")
    elif query.data == "stats":
        await query.edit_message_text("📊 Раздел 'Статистика' в разработке...")
    elif query.data == "help":
        await query.edit_message_text("❓ Раздел 'Помощь' в разработке...")

# Главная функция, где все собирается
def main():
    # Создаем приложение и передаем ему токен
    application = Application.builder().token(TOKEN).build()

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # Добавляем обработчик для текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

     # ДОБАВЛЯЕМ ОБРАБОТЧИК ДЛЯ INLINE-КНОПОК
    application.add_handler(CallbackQueryHandler(button_callback))

    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
