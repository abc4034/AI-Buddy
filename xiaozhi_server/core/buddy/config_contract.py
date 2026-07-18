from __future__ import annotations

from collections.abc import Mapping
from typing import Any


BUDDY_CORE_BASE_URL = "http://127.0.0.1:8010"


def validate_local_buddy_config(config: Mapping[str, Any]) -> None:
    """Reject the only local settings that could trigger a remote config fetch."""
    if not config.get("buddy_mode"):
        return

    manager_api = _mapping(config.get("manager-api"))
    if manager_api.get("url"):
        raise ValueError("Buddy ownership violation: manager-api.url must be empty.")
    if manager_api.get("secret"):
        raise ValueError("Buddy ownership violation: manager-api.secret must be empty.")
    if config.get("read_config_from_api") is True:
        raise ValueError("Buddy ownership violation: read_config_from_api must be false.")


def validate_effective_config(config: dict[str, Any]) -> None:
    """Fail closed when a Buddy-mode runtime could bypass Buddy Core ownership."""
    if not config.get("buddy_mode"):
        return

    validate_local_buddy_config(config)
    if config.get("read_config_from_api") is not False:
        raise ValueError("Buddy ownership violation: read_config_from_api must be false.")

    selected = _mapping(config.get("selected_module"))
    if selected.get("LLM") != "BuddyCoreLLM":
        raise ValueError("Buddy ownership violation: selected_module.LLM must be BuddyCoreLLM.")
    if selected.get("Memory") != "nomem":
        raise ValueError("Buddy ownership violation: selected_module.Memory must be nomem.")
    if selected.get("Intent") != "nointent":
        raise ValueError("Buddy ownership violation: selected_module.Intent must be nointent.")
    if selected.get("VLLM") is not None:
        raise ValueError("Buddy ownership violation: selected_module.VLLM must be disabled.")

    llm = _mapping(_mapping(config.get("LLM")).get("BuddyCoreLLM"))
    if llm.get("type") != "buddy_core":
        raise ValueError("Buddy ownership violation: BuddyCoreLLM.type must be buddy_core.")
    if llm.get("base_url") != BUDDY_CORE_BASE_URL:
        raise ValueError(f"Buddy ownership violation: BuddyCoreLLM.base_url must be {BUDDY_CORE_BASE_URL}.")

    if _mapping(config.get("end_prompt")).get("enable") is not False:
        raise ValueError("Buddy ownership violation: end_prompt.enable must be false.")
    if config.get("mcp_endpoint") not in (None, ""):
        raise ValueError("Buddy ownership violation: mcp_endpoint must be empty.")

    for name in ("tools", "context_provider", "voiceprint", "report", "VLLM"):
        if not _is_explicitly_disabled(config.get(name)):
            raise ValueError(f"Buddy ownership violation: {name} must be disabled.")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_explicitly_disabled(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, Mapping):
        return value.get("enable") is False
    return False
