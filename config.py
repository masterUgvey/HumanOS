"""
Модуль конфигурации приложения
Загружает переменные окружения из .env файла и предоставляет доступ к настройкам
"""

import os
from dotenv import load_dotenv
from loguru import logger

# Загружаем переменные окружения из .env файла
load_dotenv()


class Config:
    """Класс для хранения конфигурации приложения"""
    
    # Telegram Bot Token
    BOT_TOKEN: str = os.getenv('BOT_TOKEN', '')
    
    # Windsurf AI настройки
    WINDSURF_API_KEY: str = os.getenv('WINDSURF_API_KEY', '')
    WINDSURF_API_URL: str = os.getenv('WINDSURF_API_URL', 'https://api.windsurf.ai/v1/chat/completions')
    
    # База данных
    DATABASE_PATH: str = os.getenv('DATABASE_PATH', 'quests.db')
    
    # Логирование
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    
    # Типы квестов
    QUEST_TYPES = {
        "physical": "💪 Физические упражнения",
        "intellectual": "📚 Интеллектуальная задача",
        "mental": "🧠 Ментальная задача",
        "custom": "🎯 Произвольный квест"
    }
    # Timezone offset in minutes relative to UTC for user-local computations
    TZ_OFFSET_MINUTES: int = int(os.getenv('TZ_OFFSET_MINUTES', '0'))
    
    @classmethod
    def validate(cls) -> bool:
        """
        Проверяет наличие обязательных переменных окружения
        
        Returns:
            bool: True если все обязательные переменные установлены
        """
        if not cls.BOT_TOKEN:
            logger.error("❌ BOT_TOKEN не установлен! Проверьте файл .env")
            return False
        
        logger.info("✅ Конфигурация загружена успешно")
        logger.info(f"📊 База данных: {cls.DATABASE_PATH}")
        logger.info(f"🔧 Уровень логирования: {cls.LOG_LEVEL}")
        
        if cls.WINDSURF_API_KEY:
            logger.info("🤖 Windsurf AI: подключен")
        else:
            logger.warning("⚠️ Windsurf AI: API ключ не установлен (функция /quest будет недоступна)")
        
        return True


# Создаем экземпляр конфигурации
config = Config()
