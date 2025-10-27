"""
Скрипт автоматической установки и настройки проекта
Проверяет зависимости, создает .env файл, инициализирует базу данных
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def print_step(message):
    """Красивый вывод шага установки"""
    print(f"\n{'='*60}")
    print(f"  {message}")
    print(f"{'='*60}\n")


def check_python_version():
    """Проверка версии Python"""
    print_step("🐍 Проверка версии Python")
    
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print("❌ Требуется Python 3.11 или выше!")
        print(f"   Текущая версия: {version.major}.{version.minor}.{version.micro}")
        return False
    
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} - OK")
    return True


def install_dependencies():
    """Установка зависимостей из requirements.txt"""
    print_step("📦 Установка зависимостей")
    
    if not os.path.exists("requirements.txt"):
        print("❌ Файл requirements.txt не найден!")
        return False
    
    try:
        print("Установка пакетов...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("\n✅ Все зависимости установлены успешно!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при установке зависимостей: {e}")
        return False


def create_env_file():
    """Создание .env файла из .env.example"""
    print_step("⚙️ Настройка переменных окружения")
    
    if os.path.exists(".env"):
        response = input("Файл .env уже существует. Перезаписать? (y/N): ")
        if response.lower() != 'y':
            print("⏭️ Пропуск создания .env файла")
            return True
    
    if not os.path.exists(".env.example"):
        print("❌ Файл .env.example не найден!")
        return False
    
    try:
        shutil.copy(".env.example", ".env")
        print("✅ Файл .env создан из .env.example")
        print("\n⚠️ ВАЖНО: Отредактируйте файл .env и укажите:")
        print("   1. BOT_TOKEN - токен вашего Telegram-бота")
        print("   2. WINDSURF_API_KEY - API ключ Windsurf AI (опционально)")
        print("\n📝 Как получить токен бота:")
        print("   1. Откройте Telegram и найдите @BotFather")
        print("   2. Отправьте команду /newbot")
        print("   3. Следуйте инструкциям")
        print("   4. Скопируйте полученный токен в .env файл")
        return True
    except Exception as e:
        print(f"❌ Ошибка при создании .env файла: {e}")
        return False


def verify_env_file():
    """Проверка наличия обязательных переменных в .env"""
    print_step("🔍 Проверка конфигурации")
    
    if not os.path.exists(".env"):
        print("❌ Файл .env не найден! Запустите setup.py еще раз.")
        return False
    
    with open(".env", "r", encoding="utf-8") as f:
        content = f.read()
    
    if "your_telegram_bot_token_here" in content:
        print("⚠️ BOT_TOKEN не настроен!")
        print("   Отредактируйте файл .env и укажите токен бота")
        return False
    
    print("✅ Конфигурация выглядит корректно")
    return True


def create_gitignore():
    """Создание/обновление .gitignore"""
    print_step("📄 Настройка .gitignore")
    
    gitignore_content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
ENV/

# Environment variables
.env

# Database
*.db
*.sqlite
*.sqlite3

# Logs
*.log
bot.log

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Project specific
quests.db
quests_new.db
output.log
"""
    
    try:
        with open(".gitignore", "w", encoding="utf-8") as f:
            f.write(gitignore_content)
        print("✅ Файл .gitignore создан/обновлен")
        return True
    except Exception as e:
        print(f"⚠️ Не удалось создать .gitignore: {e}")
        return True  # Не критично


def test_imports():
    """Проверка импорта основных модулей"""
    print_step("🧪 Проверка импорта модулей")
    
    modules = [
        "aiogram",
        "aiohttp",
        "aiosqlite",
        "dotenv",
        "loguru"
    ]
    
    all_ok = True
    for module in modules:
        try:
            __import__(module)
            print(f"✅ {module}")
        except ImportError:
            print(f"❌ {module} - не установлен!")
            all_ok = False
    
    return all_ok


def main():
    """Основная функция установки"""
    print("""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║        🚀 HumanOS Bot - Автоматическая установка 🚀       ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Проверка версии Python
    if not check_python_version():
        sys.exit(1)
    
    # Установка зависимостей
    if not install_dependencies():
        print("\n❌ Установка прервана из-за ошибок")
        sys.exit(1)
    
    # Создание .env файла
    if not create_env_file():
        print("\n❌ Установка прервана из-за ошибок")
        sys.exit(1)
    
    # Создание .gitignore
    create_gitignore()
    
    # Проверка импорта модулей
    if not test_imports():
        print("\n⚠️ Некоторые модули не установлены корректно")
        print("   Попробуйте переустановить зависимости:")
        print("   pip install -r requirements.txt --force-reinstall")
    
    # Финальные инструкции
    print_step("✅ Установка завершена!")
    
    print("""
📋 Следующие шаги:

1. Отредактируйте файл .env и укажите BOT_TOKEN
   
2. (Опционально) Укажите WINDSURF_API_KEY для AI функций

3. Запустите бота:
   python main.py

4. Откройте Telegram и найдите своего бота

5. Отправьте команду /start

📚 Дополнительная информация в README.md

Удачи! 🎉
    """)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Установка прервана пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Неожиданная ошибка: {e}")
        sys.exit(1)
