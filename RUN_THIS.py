# -*- coding: utf-8 -*-
import os
import shutil

print("Установка нового бота...")

# Резервная копия
if os.path.exists('bot.py') and not os.path.exists('bot_old_backup.py'):
    shutil.copy('bot.py', 'bot_old_backup.py')
    print("Резервная копия создана")

# Читаем старый main
with open('bot_old_backup.py', 'r', encoding='utf-8') as f:
    old = f.read()
    
# Находим функцию main
main_start = old.find('def main():')
if main_start > 0:
    main_func = old[main_start:]
    # Берем до конца файла
    main_func = main_func[:main_func.rfind("if __name__") + 100]
else:
    main_func = """
def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
"""

# Читаем части нового бота из файла parts.txt если есть
if os.path.exists('bot_parts.txt'):
    with open('bot_parts.txt', 'r', encoding='utf-8') as f:
        new_code = f.read()
else:
    # Если нет файла с частями, используем минимальную версию
    print("Файл bot_parts.txt не найден")
    print("Создайте его или используйте другой метод установки")
    exit(1)

# Записываем новый bot.py
with open('bot.py', 'w', encoding='utf-8') as f:
    f.write(new_code + "\n\n" + main_func)

print("✅ bot.py создан успешно!")
print("Запустите: python bot.py")
