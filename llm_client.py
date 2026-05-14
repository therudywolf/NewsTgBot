"""LM Studio client for model discovery, loading, and news processing.

NewsTgBot - Self-hosted IT news aggregator
Copyright (C) 2026 therudywolf

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License.
See LICENSE file for details.
"""
import json
import logging
from typing import Any, Dict, List, Optional

import aiohttp

import config

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for LM Studio native v1 and OpenAI-compatible APIs."""

    def __init__(
        self,
        api_url: str = None,
        model_name: str = None,
        api_token: str = None,
        api_mode: str = None,
    ):
        self._api_url_explicit = api_url is not None
        self._api_mode_explicit = api_mode is not None
        self._model_explicit = model_name is not None
        self.api_url = self._normalize_base_url(api_url or config.get_lm_studio_base_url())
        self.model_name = model_name or config.get_lm_studio_model()
        self.api_token = api_token if api_token is not None else config.get_lm_studio_api_token()
        self.api_mode = (api_mode or config.get_lm_studio_api_mode() or "native").lower()

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        normalized = (url or "http://localhost:1234").strip().rstrip("/")
        for suffix in ("/api/v1", "/v1"):
            if normalized.endswith(suffix):
                return normalized[: -len(suffix)]
        return normalized

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token = self._resolve_api_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _resolve_model_name(self) -> Optional[str]:
        if self.model_name and self._model_explicit:
            return self.model_name

        try:
            from database import Database

            stored_model = Database().get_setting("lm_studio_model")
            if stored_model:
                self.model_name = stored_model
                return stored_model
        except Exception as e:
            logger.debug("Could not resolve LM Studio model from DB settings: %s", e)

        return self.model_name or None

    def _resolve_base_url(self) -> str:
        if self._api_url_explicit:
            return self.api_url

        try:
            from database import Database

            stored_url = Database().get_setting("lm_studio_base_url")
            if stored_url:
                self.api_url = self._normalize_base_url(stored_url)
        except Exception as e:
            logger.debug("Could not resolve LM Studio base URL from DB settings: %s", e)

        return self.api_url

    def _resolve_api_mode(self) -> str:
        if self._api_mode_explicit:
            return self.api_mode

        try:
            from database import Database

            stored_mode = Database().get_setting("lm_studio_api_mode")
            if stored_mode:
                self.api_mode = str(stored_mode).lower()
        except Exception as e:
            logger.debug("Could not resolve LM Studio API mode from DB settings: %s", e)

        return self.api_mode

    def _resolve_api_token(self) -> str:
        try:
            from database import Database

            stored_token = Database().get_setting("lm_studio_api_token")
            if stored_token:
                self.api_token = str(stored_token)
                return self.api_token
        except Exception as e:
            logger.debug("Could not resolve LM Studio API token from DB settings: %s", e)

        return self.api_token or ""

    async def _request(
        self,
        method: str,
        path: str,
        payload: Dict[str, Any] = None,
        timeout_seconds: int = 120,
    ) -> Dict[str, Any]:
        url = f"{self._resolve_base_url()}{path}"
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method,
                url,
                json=payload,
                headers=self._headers(),
            ) as response:
                text = await response.text()
                try:
                    data = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    data = {"raw": text}

                if response.status >= 400:
                    raise RuntimeError(f"LM Studio API error {response.status}: {data}")
                return data

    async def list_models(self) -> List[Dict[str, Any]]:
        """Return models from LM Studio, preferring the native v1 endpoint."""
        if self._resolve_api_mode() == "openai":
            data = await self._request("GET", "/v1/models", timeout_seconds=20)
            return [
                {
                    "key": item.get("id"),
                    "display_name": item.get("id"),
                    "type": "llm",
                    "loaded_instances": [],
                    "source": "openai-compatible",
                }
                for item in data.get("data", [])
            ]

        data = await self._request("GET", "/api/v1/models", timeout_seconds=20)
        return data.get("models", [])

    async def load_model(
        self,
        model: str,
        context_length: Optional[int] = None,
        flash_attention: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Load an LM Studio model through native v1 API."""
        payload: Dict[str, Any] = {"model": model, "echo_load_config": True}
        if context_length:
            payload["context_length"] = context_length
        if flash_attention is not None:
            payload["flash_attention"] = flash_attention

        data = await self._request("POST", "/api/v1/models/load", payload, timeout_seconds=600)
        self.model_name = model
        return data

    async def test_connection(self) -> Dict[str, Any]:
        """Check server reachability and return a small status payload."""
        models = await self.list_models()
        loaded = [
            model
            for model in models
            if model.get("loaded_instances")
        ]
        return {
            "base_url": self._resolve_base_url(),
            "api_mode": self._resolve_api_mode(),
            "models_count": len(models),
            "loaded_count": len(loaded),
            "selected_model": self._resolve_model_name(),
            "auth_configured": bool(self.api_token),
        }

    async def _make_request(self, prompt: str, system_prompt: str = None) -> Optional[str]:
        """Make a chat request to LM Studio."""
        model = self._resolve_model_name()
        if not model:
            logger.error("LM Studio model is not configured")
            return None

        try:
            if self._resolve_api_mode() == "openai":
                return await self._make_openai_request(model, prompt, system_prompt)
            return await self._make_native_request(model, prompt, system_prompt)
        except Exception as e:
            logger.error("LM Studio request failed: %s", e)
            return None

    async def _make_native_request(
        self,
        model: str,
        prompt: str,
        system_prompt: str = None,
    ) -> Optional[str]:
        payload = {
            "model": model,
            "input": prompt,
            "temperature": config.LLM_TEMPERATURE,
            "max_output_tokens": config.LLM_MAX_OUTPUT_TOKENS,
            "context_length": config.LLM_CONTEXT_LENGTH,
            "store": False,
        }
        if system_prompt:
            payload["system_prompt"] = system_prompt
        data = await self._request("POST", "/api/v1/chat", payload)
        return self._extract_native_text(data)

    async def _make_openai_request(
        self,
        model: str,
        prompt: str,
        system_prompt: str = None,
    ) -> Optional[str]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": config.LLM_TEMPERATURE,
            "max_tokens": config.LLM_MAX_OUTPUT_TOKENS,
        }
        data = await self._request("POST", "/v1/chat/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}
        return message.get("content")

    @staticmethod
    def _extract_native_text(data: Dict[str, Any]) -> Optional[str]:
        output = data.get("output")
        if isinstance(output, str):
            return output

        parts = []
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "message":
                    continue
                content = item.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and isinstance(block.get("text"), str):
                            parts.append(block["text"])

        if parts:
            return "\n".join(parts).strip()

        if isinstance(data.get("text"), str):
            return data["text"]
        return None

    @staticmethod
    def _format_news_list(news_items: List[Dict[str, Any]]) -> str:
        """Render a numbered transcript of news items for prompt insertion."""
        lines: List[str] = []
        for idx, item in enumerate(news_items, 1):
            text = (item.get("text") or "").strip()
            if not text:
                continue
            channel = item.get("title") or item.get("username") or "источник"
            date = item.get("date") or ""
            lines.append(f"{idx}. [{channel}] {date}\n{text}\n")
        return "\n".join(lines)

    def _load_active_prompt(self, task: str) -> Optional[Dict[str, str]]:
        """Look up an admin-configured prompt for *task* from the database."""
        try:
            from database import Database

            record = Database().get_active_prompt(task)
        except Exception as e:  # noqa: BLE001 — DB is best-effort here
            logger.debug("Could not load %s prompt from DB: %s", task, e)
            return None
        if not record:
            return None
        return {
            "system": record.get("system_prompt") or "",
            "user_template": record.get("user_template") or "",
        }

    async def chat(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Public single-turn chat helper used by posting/preview flows."""
        return await self._make_request(user_prompt, system_prompt)

    async def rewrite_post(
        self,
        news_items: List[Dict[str, Any]],
        instruction: Optional[str] = None,
        prompt_name: Optional[str] = None,
    ) -> Optional[str]:
        """Rewrite a batch of news into a publish-ready Telegram post.

        Uses the active 'repost' prompt from the DB if available; otherwise
        falls back to a generic instruction. *instruction* lets the caller
        override the user template inline (e.g. "make it shorter").
        """
        if not news_items:
            return None

        news_text = self._format_news_list(news_items)
        record = self._load_active_prompt("repost")
        system_prompt = (
            record["system"]
            if record and record["system"]
            else (
                "Ты редактор Telegram-канала об IT. Перепиши подборку новостей "
                "в один короткий пост на русском языке: 1-3 абзаца, без воды, "
                "с эмодзи в начале строки, в конце — отдельной строкой источники."
            )
        )

        template = (
            record["user_template"]
            if record and record["user_template"]
            else "Подборка для поста:\n\n{news}\n\nДополнительная инструкция: {instruction}"
        )
        formatted = template.replace("{news}", news_text).replace(
            "{instruction}", (instruction or "").strip() or "—"
        )
        if prompt_name:
            formatted = f"[Стиль: {prompt_name}]\n{formatted}"
        response = await self._make_request(formatted, system_prompt)
        return response.strip() if response else None

    async def deduplicate_news(self, news_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Use LLM to deduplicate news items."""
        if not news_items:
            return []

        news_text = ""
        for idx, item in enumerate(news_items, 1):
            text = item.get("text", "").strip()
            if text:
                news_text += f"{idx}. {text}\n\n"

        custom = self._load_active_prompt("dedup")
        default_system = """Ты помощник для удаления дубликатов новостей.
Твоя задача - проанализировать список новостей и определить, какие из них являются дубликатами или описывают одно и то же событие.
Верни только уникальные новости, удалив все дубликаты и повторы.

Важно: верни ТОЛЬКО номера уникальных новостей в формате JSON массива чисел, например: [1, 3, 5, 7]
Не включай в ответ никаких дополнительных объяснений или текста, только JSON массив."""
        default_user = f"""Проанализируй следующие новости и определи, какие из них уникальны:

{news_text}

Верни JSON массив с номерами уникальных новостей, начиная с 1."""

        system_prompt = custom["system"] if custom and custom["system"] else default_system
        if custom and custom["user_template"]:
            user_prompt = custom["user_template"].replace("{news}", news_text)
        else:
            user_prompt = default_user

        response = await self._make_request(user_prompt, system_prompt)
        if not response:
            return news_items

        try:
            cleaned = self._strip_json_markdown(response)
            indices = json.loads(cleaned)
            if isinstance(indices, list) and all(isinstance(i, int) for i in indices):
                unique_indices = [i - 1 for i in indices if 1 <= i <= len(news_items)]
                return [news_items[i] for i in unique_indices]
        except (json.JSONDecodeError, ValueError, IndexError) as e:
            logger.warning("Error parsing deduplication response: %s", e)
            logger.debug("Response was: %s", response)

        return news_items

    async def aggregate_news(self, news_items: List[Dict[str, Any]], period_description: str = "") -> str:
        """Use LLM to aggregate news items into a summary."""
        if not news_items:
            return "Новостей за указанный период не найдено."

        news_text = ""
        for idx, item in enumerate(news_items, 1):
            text = item.get("text", "").strip()
            channel = item.get("title") or item.get("username", "Неизвестный источник")
            date = item.get("date", "")
            if text:
                news_text += f"{idx}. [{channel}] {date}\n{text}\n\n"

        custom = self._load_active_prompt("summary")
        default_system = """Ты редактор IT-новостей.
Собери краткую, структурированную сводку. Группируй похожие события, убирай повторы, сохраняй факты и источники.
Пиши на русском языке, без рекламного тона."""
        default_user = f"""Создай краткую сводку новостей за период {period_description}:

{news_text}

Формат:
1. Короткий заголовок темы
2. 1-3 предложения с сутью
3. Источники в скобках, если они есть в списке"""

        system_prompt = custom["system"] if custom and custom["system"] else default_system
        if custom and custom["user_template"]:
            user_prompt = (
                custom["user_template"]
                .replace("{news}", news_text)
                .replace("{period}", period_description or "")
            )
        else:
            user_prompt = default_user

        response = await self._make_request(user_prompt, system_prompt)
        if not response:
            return "Ошибка при генерации сводки новостей. Проверьте LM Studio, модель и API token."

        return response.strip()

    async def generate_tags(self, news_text: str) -> List[str]:
        """Use LLM to generate tags for a news item."""
        if not news_text or not news_text.strip():
            return []

        custom = self._load_active_prompt("tags")
        default_system = """Ты помощник для генерации тегов новостей.
Верни только JSON массив из 3-5 коротких тегов на русском языке."""
        default_user = f"""Проанализируй новость и создай 3-5 релевантных тегов:

{news_text}"""

        system_prompt = custom["system"] if custom and custom["system"] else default_system
        if custom and custom["user_template"]:
            user_prompt = custom["user_template"].replace("{news}", news_text)
        else:
            user_prompt = default_user

        response = await self._make_request(user_prompt, system_prompt)
        if not response:
            return []

        try:
            tags = json.loads(self._strip_json_markdown(response))
            if isinstance(tags, list) and all(isinstance(tag, str) for tag in tags):
                return [tag.lower().strip() for tag in tags if tag.strip()][:5]
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Error parsing tags response: %s", e)
            logger.debug("Response was: %s", response)

        return []

    @staticmethod
    def _strip_json_markdown(response: str) -> str:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if len(lines) >= 2:
                cleaned = "\n".join(lines[1:-1]).strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        return cleaned
