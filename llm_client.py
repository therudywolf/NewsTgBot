"""LLM client for deduplication and aggregation."""
import aiohttp
import json
from typing import List, Dict, Any, Optional
import config


class LLMClient:
    """Client for interacting with LLM API."""
    
    def __init__(self, api_url: str = None, model_name: str = None):
        """Initialize LLM client."""
        self.api_url = api_url or config.LLM_API_URL
        self.model_name = model_name or config.LLM_MODEL_NAME
        
        # Remove trailing slash if present
        if self.api_url.endswith('/'):
            self.api_url = self.api_url.rstrip('/')
    
    async def _make_request(self, prompt: str, system_prompt: str = None) -> Optional[str]:
        """Make request to LLM API."""
        # Determine the API endpoint - common patterns are /v1/chat/completions or /api/v1/chat/completions
        # Try the most common endpoint first
        endpoint = f"{self.api_url}/v1/chat/completions"
        
        payload = {
            "model": self.model_name,
            "messages": []
        }
        
        if system_prompt:
            payload["messages"].append({
                "role": "system",
                "content": system_prompt
            })
        
        payload["messages"].append({
            "role": "user",
            "content": prompt
        })
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Extract the response text from common response formats
                        if "choices" in data and len(data["choices"]) > 0:
                            return data["choices"][0]["message"]["content"]
                        elif "text" in data:
                            return data["text"]
                        else:
                            # If response format is different, try to get the first available text field
                            return str(data)
                    else:
                        error_text = await response.text()
                        print(f"LLM API error {response.status}: {error_text}")
                        return None
        except aiohttp.ClientError as e:
            print(f"LLM API request error: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error in LLM request: {e}")
            return None
    
    async def deduplicate_news(self, news_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Use LLM to deduplicate news items."""
        if not news_items:
            return []
        
        # Format news items for the prompt
        news_text = ""
        for idx, item in enumerate(news_items, 1):
            text = item.get('text', '').strip()
            if text:
                news_text += f"{idx}. {text}\n\n"
        
        system_prompt = """Ты помощник для удаления дубликатов новостей. 
Твоя задача - проанализировать список новостей и определить, какие из них являются дубликатами или описывают одно и то же событие.
Верни только уникальные новости, удалив все дубликаты и повторы.

Важно: верни ТОЛЬКО номера уникальных новостей в формате JSON массива чисел, например: [1, 3, 5, 7]
Не включай в ответ никаких дополнительных объяснений или текста, только JSON массив."""
        
        user_prompt = f"""Проанализируй следующие новости и определи, какие из них уникальны (не дубликаты):

{news_text}

Верни JSON массив с номерами уникальных новостей (начиная с 1)."""
        
        response = await self._make_request(user_prompt, system_prompt)
        
        if not response:
            # If LLM fails, return all items
            return news_items
        
        # Try to parse the response as JSON
        try:
            # Clean the response - remove markdown code blocks if present
            response = response.strip()
            if response.startswith("```"):
                # Remove markdown code blocks
                lines = response.split('\n')
                response = '\n'.join(lines[1:-1]) if len(lines) > 2 else response
            if response.startswith("```json"):
                lines = response.split('\n')
                response = '\n'.join(lines[1:-1]) if len(lines) > 2 else response
            
            indices = json.loads(response)
            if isinstance(indices, list) and all(isinstance(i, int) for i in indices):
                # Convert 1-based indices to 0-based
                unique_indices = [i - 1 for i in indices if 1 <= i <= len(news_items)]
                return [news_items[i] for i in unique_indices if 0 <= i < len(news_items)]
        except (json.JSONDecodeError, ValueError, IndexError) as e:
            print(f"Error parsing deduplication response: {e}")
            print(f"Response was: {response}")
            # If parsing fails, return all items
            return news_items
        
        return news_items
    
    async def aggregate_news(self, news_items: List[Dict[str, Any]], period_description: str = "") -> str:
        """Use LLM to aggregate news items into a summary."""
        if not news_items:
            return "Новостей за указанный период не найдено."
        
        # Format news items for the prompt
        news_text = ""
        for idx, item in enumerate(news_items, 1):
            text = item.get('text', '').strip()
            channel = item.get('title') or item.get('username', 'Неизвестный канал')
            date = item.get('date', '')
            if text:
                news_text += f"{idx}. [{channel}] {text}\n\n"
        
        system_prompt = """Ты помощник для создания кратких сводок новостей.
Твоя задача - проанализировать список новостей и создать краткую, структурированную сводку того, что произошло.
Сводка должна быть информативной, но краткой. Сгруппируй похожие события вместе.
Используй понятный и структурированный формат."""
        
        user_prompt = f"""Создай краткую сводку новостей за период {period_description}:

{news_text}

Создай структурированную сводку основных событий. Будь кратким, но информативным."""
        
        response = await self._make_request(user_prompt, system_prompt)
        
        if not response:
            return "Ошибка при генерации сводки новостей. Попробуйте позже."
        
        return response.strip()

