"""
Модуль для интеграции с Windsurf AI
Отправляет запросы к AI для генерации квестов и задач на основе целей пользователя
"""

import aiohttp
import json
from typing import Optional, Dict, Any
from loguru import logger
from config import config


class WindsurfAIClient:
    """Клиент для работы с Windsurf AI API"""
    
    def __init__(self):
        """Инициализация клиента"""
        self.api_url = config.WINDSURF_API_URL
        self.api_key = config.WINDSURF_API_KEY
        self.timeout = aiohttp.ClientTimeout(total=30)
    
    async def generate_quest(self, user_goal: str) -> Optional[Dict[str, Any]]:
        """
        Генерация квеста на основе цели пользователя через Windsurf AI
        
        Args:
            user_goal: Цель пользователя (например, "Хочу похудеть на 5 кг")
            
        Returns:
            Optional[Dict[str, Any]]: Словарь с данными квеста или None при ошибке
            Формат: {
                "title": "Название квеста",
                "quest_type": "physical/intellectual/mental/custom",
                "target_value": 100,
                "description": "Описание квеста",
                "tips": ["Совет 1", "Совет 2"]
            }
        """
        if not self.api_key:
            logger.warning("⚠️ API ключ Windsurf AI не установлен")
            return None
        
        # Формируем промт для AI
        prompt = f"""
Ты — эксперт по постановке целей и созданию мотивирующих квестов.

Пользователь хочет: {user_goal}

Создай для него квест в формате JSON со следующими полями:
- title: краткое название квеста (до 50 символов)
- quest_type: тип квеста (physical для физических задач, intellectual для обучения, mental для привычек, custom для остального)
- target_value: целевое значение (для physical/intellectual - конкретное число, для mental/custom - всегда 100)
- description: подробное описание квеста и как его выполнить (до 200 символов)
- tips: массив из 3-5 практических советов для достижения цели

Ответь ТОЛЬКО в формате JSON, без дополнительного текста.
"""
        
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            payload = {
                "model": "gpt-3.5-turbo",  # Можно заменить на другую модель
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты — помощник по созданию мотивирующих квестов. Отвечай только в формате JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.7,
                "max_tokens": 500
            }
            
            logger.info(f"🤖 Отправка запроса к Windsurf AI: {user_goal[:50]}...")
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(self.api_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Извлекаем ответ AI
                        ai_response = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        
                        # Парсим JSON из ответа
                        quest_data = json.loads(ai_response)
                        
                        logger.info(f"✅ Квест сгенерирован AI: {quest_data.get('title', 'Без названия')}")
                        return quest_data
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка API Windsurf AI ({response.status}): {error_text}")
                        return None
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON от AI: {e}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"❌ Ошибка соединения с Windsurf AI: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при работе с AI: {e}")
            return None
    
    async def get_motivation(self, quest_title: str, progress: int, target: int) -> Optional[str]:
        """
        Получение мотивационного сообщения от AI на основе прогресса квеста
        
        Args:
            quest_title: Название квеста
            progress: Текущий прогресс
            target: Целевое значение
            
        Returns:
            Optional[str]: Мотивационное сообщение или None
        """
        if not self.api_key:
            return None
        
        progress_percent = (progress / target * 100) if target > 0 else 0
        
        prompt = f"""
Квест: {quest_title}
Прогресс: {progress}/{target} ({progress_percent:.1f}%)

Напиши короткое мотивационное сообщение (до 100 символов) для пользователя, учитывая его прогресс.
Если прогресс низкий - подбодри. Если высокий - похвали. Используй эмодзи.
"""
        
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            payload = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {"role": "system", "content": "Ты — мотивационный коуч. Пиши кратко и вдохновляюще."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.8,
                "max_tokens": 100
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(self.api_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        motivation = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        return motivation.strip()
                    else:
                        return None
        
        except Exception as e:
            logger.error(f"❌ Ошибка получения мотивации от AI: {e}")
            return None
    
    async def analyze_goal(self, goal_text: str) -> Optional[str]:
        """
        Анализ цели пользователя и предоставление рекомендаций
        
        Args:
            goal_text: Текст цели пользователя
            
        Returns:
            Optional[str]: Анализ и рекомендации или None
        """
        if not self.api_key:
            return None
        
        prompt = f"""
Пользователь поставил цель: {goal_text}

Проанализируй эту цель и дай краткие рекомендации (до 300 символов):
1. Насколько цель конкретна и измерима
2. Реалистична ли она
3. Какие первые шаги стоит предпринять

Ответь кратко и по делу, используй эмодзи для структурирования.
"""
        
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            payload = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {"role": "system", "content": "Ты — эксперт по постановке целей и планированию."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 300
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(self.api_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        analysis = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        return analysis.strip()
                    else:
                        return None
        
        except Exception as e:
            logger.error(f"❌ Ошибка анализа цели AI: {e}")
            return None


# Создаем глобальный экземпляр клиента
ai_client = WindsurfAIClient()
