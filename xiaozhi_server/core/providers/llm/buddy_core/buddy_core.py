from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from core.buddy.config_contract import BUDDY_CORE_BASE_URL, is_approved_fault_provider_url
from core.buddy.provider_errors import BuddyProviderFailure
from core.buddy.session_context import get_context
from core.providers.llm.base import LLMProviderBase


class LLMProvider(LLMProviderBase):
    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config.get("base_url") or "").rstrip("/")
        self.timeout_seconds = float(config.get("timeout_seconds", 30))
        if self.base_url != BUDDY_CORE_BASE_URL and not is_approved_fault_provider_url(
            self.base_url
        ):
            raise ValueError(f"Buddy Core LLM requires base_url {BUDDY_CORE_BASE_URL}.")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Buddy Core LLM requires a positive timeout_seconds.")

    def response(self, session_id, dialogue):
        context = get_context(session_id)
        if context is None:
            raise BuddyProviderFailure("buddy_invalid_request", "Buddy Core LLM requires a registered session context.")
        user_turn = _latest_user_turn(dialogue)
        if user_turn is None:
            raise BuddyProviderFailure("buddy_invalid_request", "Buddy Core LLM requires a current user turn.")

        payload = {
            "messages": [{"role": "user", "content": user_turn}],
            "metadata": {
                "device_id": context.device_id,
                "client_id": context.client_id,
                "session_id": context.session_id,
                "source": context.source,
            },
            "stream": False,
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}/v1/chat/completions", json=payload)
                response.raise_for_status()
                assistant_text = _assistant_text(response.json())
        except httpx.TimeoutException as error:
            raise BuddyProviderFailure("buddy_timeout", "Buddy Core LLM request timed out.") from error
        except httpx.HTTPError as error:
            raise BuddyProviderFailure("buddy_failed", "Buddy Core LLM request failed.") from error

        yield assistant_text


def _latest_user_turn(dialogue: Iterable[Any]) -> str | None:
    for message in reversed(list(dialogue)):
        role, content = _message_values(message)
        if role == "user" and content and content.strip():
            return content.strip()
    return None


def _message_values(message: Any) -> tuple[str | None, str | None]:
    if isinstance(message, Mapping):
        role = message.get("role")
        content = message.get("content")
    else:
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
    return role if isinstance(role, str) else None, content if isinstance(content, str) else None


def _assistant_text(payload: Any) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (IndexError, KeyError, TypeError):
        raise BuddyProviderFailure("buddy_invalid_response", "Buddy Core LLM returned an invalid response.") from None
    if not isinstance(content, str) or not content.strip():
        raise BuddyProviderFailure("buddy_invalid_response", "Buddy Core LLM returned an invalid response.")
    return content
