# ⚡ Быстрый старт HumanOS Bot

## 🚀 Запуск за 5 минут

### Шаг 1: Установка зависимостей

```bash
# Активируйте виртуальное окружение (если есть)
# Windows:
venv\Scripts\activate

# Linux/Mac:
source venv/bin/activate

# Запустите автоматическую установку
python setup.py
```

### Шаг 2: Получение токена бота

1. Откройте Telegram
2. Найдите [@BotFather](https://t.me/BotFather)
3. Отправьте `/newbot`
4. Придумайте имя и username для бота
5. Скопируйте полученный токен

### Шаг 3: Настройка .env

Откройте файл `.env` и вставьте токен:

```env
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

### Шаг 4: Запуск

```bash
python main.py
```

Готово! 🎉

## 📱 Первые команды

В Telegram отправьте боту:

- `/start` - Начать работу
- `/help` - Справка
- `/add_task` - Добавить задачу

## 🤖 AI Функции (опционально)

Для использования AI генерации квестов:

1. Получите API ключ Windsurf AI
2. Добавьте в `.env`:
   ```env
   WINDSURF_API_KEY=your_api_key_here
   ```
3. Используйте команду `/quest` в боте

## ❓ Проблемы?

### Бот не отвечает

- Проверьте, что `python main.py` запущен
- Убедитесь, что токен правильный в `.env`

### Ошибка импорта модулей

```bash
pip install -r requirements.txt --force-reinstall
```

### Другие вопросы

Смотрите полную документацию в [README.md](README.md)

---

**Приятного использования! 🚀**
