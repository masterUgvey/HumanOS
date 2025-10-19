# -*- coding: utf-8 -*-
import os
import shutil
from datetime import datetime

print("="*70)
print("ФИНАЛЬНОЕ ОБНОВЛЕНИЕ БОТА")
print("="*70)

# Резервная копия
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy('bot.py', f'bot_backup_{timestamp}.py')
print(f"✅ Резервная копия создана")

# Читаем старую функцию main
with open('bot.py', 'r', encoding='utf-8') as f:
    old = f.read()

main_start = old.find('def main():')
main_func = old[main_start:] if main_start > 0 else """
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

# Читаем новый код из файла new_bot_code.txt
if os.path.exists('new_bot_code.txt'):
    with open('new_bot_code.txt', 'r', encoding='utf-8') as f:
        new_code = f.read()
    
    # Записываем новый bot.py
    with open('bot.py', 'w', encoding='utf-8') as f:
        f.write(new_code + "\n\n" + main_func)
    
    print("✅ bot.py обновлен успешно!")
    print("\nЗапустите: python bot.py")
else:
    print("❌ Файл new_bot_code.txt не найден")
    print("Создаю его сейчас...")
    
    # Создаем файл с новым кодом
    exec(open('create_new_code.py').read())
