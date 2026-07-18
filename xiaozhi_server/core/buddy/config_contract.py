from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse
import ipaddress
import os


BUDDY_CORE_BASE_URL = "http://127.0.0.1:8010"
BUDDY_NEUTRAL_PROMPT_TEMPLATE = "buddy-neutral-prompt.txt"


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
    fault_process = os.environ.get("BUDDY_FAULT_TEST_MODE") == "1"
    fault_mode = config.get("fault_test_mode") is True
    if fault_process or fault_mode:
        if config.get("buddy_mode") is not True:
            raise ValueError("Fault configuration requires buddy_mode: true.")
        if not fault_mode:
            raise ValueError("Fault configuration requires fault_test_mode: true.")
        _validate_fault_gate(config)

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
    if not fault_mode and llm.get("base_url") != BUDDY_CORE_BASE_URL:
        raise ValueError(f"Buddy ownership violation: BuddyCoreLLM.base_url must be {BUDDY_CORE_BASE_URL}.")

    if _mapping(config.get("end_prompt")).get("enable") is not False:
        raise ValueError("Buddy ownership violation: end_prompt.enable must be false.")
    if config.get("mcp_endpoint") not in (None, ""):
        raise ValueError("Buddy ownership violation: mcp_endpoint must be empty.")
    if config.get("context_providers") != []:
        raise ValueError("Buddy ownership violation: context_providers must be empty.")
    if config.get("voiceprint") is not False:
        raise ValueError("Buddy ownership violation: voiceprint must be false.")
    if config.get("prompt") != "":
        raise ValueError("Buddy ownership violation: prompt must be empty.")
    if config.get("prompt_template") != BUDDY_NEUTRAL_PROMPT_TEMPLATE:
        raise ValueError(
            f"Buddy ownership violation: prompt_template must be {BUDDY_NEUTRAL_PROMPT_TEMPLATE}."
        )

    for name in ("tools", "report", "VLLM"):
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


def _validate_fault_gate(config: Mapping[str, Any]) -> None:
    """Permit alternate local providers only in an explicit, process-scoped fault run."""
    if os.environ.get("BUDDY_FAULT_TEST_MODE") != "1":
        raise ValueError("Fault configuration requires BUDDY_FAULT_TEST_MODE=1.")

    from config.config_loader import get_fault_config_path

    if get_fault_config_path() is None:
        raise ValueError("Fault configuration requires an approved config path.")

    server = _mapping(config.get("server"))
    if not _is_loopback(server.get("ip")):
        raise ValueError("Fault configuration server must bind to loopback.")
    _validate_fault_listener_port(server, "port", 8000)
    _validate_fault_listener_port(server, "http_port", 8003)

    selected = _mapping(config.get("selected_module"))
    if selected.get("ASR") != "BuddyFaultASR":
        raise ValueError("Fault configuration must select buddy_fault ASR.")
    asr = _mapping(_mapping(config.get("ASR")).get("BuddyFaultASR"))
    if asr.get("type") != "buddy_fault" or not _is_fault_loopback_url(asr.get("base_url")):
        raise ValueError("Fault configuration ASR endpoint must be loopback.")

    llm = _mapping(_mapping(config.get("LLM")).get("BuddyCoreLLM"))
    if not _is_fault_loopback_url(llm.get("base_url")):
        raise ValueError("Fault configuration Buddy Core URL must be loopback.")

    if selected.get("TTS") != "BuddyFaultTTS":
        raise ValueError("Fault configuration must select the fault TTS provider.")
    tts = _mapping(_mapping(config.get("TTS")).get(selected.get("TTS")))
    tts_url = tts.get("api_url") or tts.get("base_url")
    if not _is_fault_loopback_url(tts_url):
        raise ValueError("Fault configuration TTS endpoint must be loopback.")


def _is_loopback(value: Any) -> bool:
    try:
        return ipaddress.ip_address(str(value)).is_loopback
    except ValueError:
        return False


def _is_loopback_url(value: Any) -> bool:
    parsed = urlparse(str(value))
    return parsed.scheme in {"http", "ws"} and _is_loopback(parsed.hostname)


def _is_fault_loopback_url(value: Any) -> bool:
    parsed = urlparse(str(value))
    return _is_loopback_url(value) and parsed.port not in {None, 8000, 8003, 8010}


def _validate_fault_listener_port(
    server: Mapping[str, Any], key: str, production_port: int
) -> None:
    value = server.get(key)
    if isinstance(value, bool):
        raise ValueError(
            f"Fault configuration server.{key} must be an explicit non-production port."
        )
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"Fault configuration server.{key} must be an explicit non-production port."
        ) from None
    if not 1 <= port <= 65535 or port == production_port:
        raise ValueError(f"Fault configuration server.{key} cannot use a production port.")


def is_approved_fault_provider_url(value: Any) -> bool:
    """Allow an alternate provider URL only inside the approved fault-test process."""
    if os.environ.get("BUDDY_FAULT_TEST_MODE") != "1" or not _is_fault_loopback_url(value):
        return False

    from config.config_loader import get_fault_config_path

    return get_fault_config_path() is not None
