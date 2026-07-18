from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path

import pytest
import yaml


RUNTIME_DIR = Path(__file__).resolve().parents[2] / "xiaozhi_server"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from config import config_loader
from core.buddy.config_contract import validate_effective_config


def buddy_config() -> dict[str, object]:
    return {
        "buddy_mode": True,
        "manager-api": {"url": "", "secret": ""},
        "read_config_from_api": False,
        "selected_module": {"LLM": "BuddyCoreLLM", "Memory": "nomem", "Intent": "nointent"},
        "LLM": {
            "BuddyCoreLLM": {
                "type": "buddy_core",
                "base_url": "http://127.0.0.1:8010",
                "timeout_seconds": 15,
            }
        },
        "Memory": {"nomem": {"type": "nomem"}},
        "Intent": {"nointent": {"type": "nointent"}},
        "end_prompt": {"enable": False},
        "tools": {"enable": False},
        "mcp_endpoint": "",
        "context_providers": [],
        "voiceprint": False,
        "report": {"enable": False},
        "VLLM": {"enable": False},
        "prompt": "",
        "prompt_template": "buddy-neutral-prompt.txt",
    }


def set_path(config: dict[str, object], path: tuple[str, ...], value: object) -> None:
    current = config
    for key in path[:-1]:
        current = current[key]  # type: ignore[index, assignment]
    current[path[-1]] = value  # type: ignore[index]


def test_buddy_ownership_configuration_is_accepted():
    validate_effective_config(buddy_config())


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("manager-api", "url"), "http://manager.example.test", "manager-api.url"),
        (("manager-api", "secret"), "not-empty", "manager-api.secret"),
        (("read_config_from_api",), True, "read_config_from_api"),
        (("selected_module", "Memory"), "mem_local_short", "Memory"),
        (("selected_module", "Intent"), "function_call", "Intent"),
        (("selected_module", "LLM"), "OpenAILLM", "LLM"),
        (("selected_module", "VLLM"), "OpenAIVLLM", "VLLM"),
        (("end_prompt", "enable"), True, "end_prompt"),
        (("tools", "enable"), True, "tools"),
        (("mcp_endpoint",), "ws://mcp.example.test", "mcp_endpoint"),
        (("context_providers",), [{"url": "https://context.example.test"}], "context_providers"),
        (("voiceprint",), {"enable": False, "url": "https://voice.example.test/?key=test"}, "voiceprint"),
        (("report", "enable"), True, "report"),
        (("VLLM", "enable"), True, "VLLM"),
        (("prompt",), "upstream persona", "prompt"),
        (("prompt_template",), "agent-base-prompt.txt", "prompt_template"),
    ],
)
def test_buddy_ownership_configuration_fails_closed(path, value, match):
    config = buddy_config()
    set_path(config, path, value)

    with pytest.raises(ValueError, match=match):
        validate_effective_config(config)


def test_buddy_mode_rejects_a_remote_manager_before_fetching_remote_configuration(monkeypatch):
    custom = buddy_config()
    custom["manager-api"] = {"url": "http://manager.example.test", "secret": ""}
    monkeypatch.setattr(config_loader, "get_project_dir", lambda: "unused/")
    monkeypatch.setattr(config_loader, "read_config", lambda _: copy.deepcopy(custom))

    async def remote_config(_: dict[str, object]):
        raise AssertionError("remote configuration must not be fetched in Buddy mode")

    monkeypatch.setattr(config_loader, "get_config_from_api_async", remote_config)
    from core.utils.cache.manager import CacheType, cache_manager

    monkeypatch.setattr(cache_manager, "get", lambda *_: None)
    monkeypatch.setattr(cache_manager, "set", lambda *_: None)

    with pytest.raises(ValueError, match="manager-api.url"):
        asyncio.run(config_loader.load_config())


def test_config_renderer_enables_buddy_ownership_overlay():
    from integrations.xiaozhi_server.render_config import render_config

    environment = {
        "ASR_PROVIDER": "qwen3_asr_flash",
        "ASR_HTTP_URL": "https://asr.example.test/v1",
        "ASR_MODEL": "qwen3-asr-flash",
        "ASR_TIMEOUT_SECONDS": "7.5",
    }
    environment["ASR_" + "API_KEY"] = "fixture"
    rendered = render_config(
        "192.168.2.9",
        process_environment=environment,
        user_environment={},
    )

    assert "buddy_mode: true" in rendered
    assert "LLM: BuddyCoreLLM" in rendered
    assert "base_url: http://127.0.0.1:8010" in rendered
    assert "Memory: nomem" in rendered
    assert "Intent: nointent" in rendered
    assert "enable: false" in rendered
    assert "context_providers: []" in rendered
    assert "voiceprint: false" in rendered
    assert "prompt_template: buddy-neutral-prompt.txt" in rendered

    overlay = yaml.safe_load(rendered)
    default = config_loader.read_config(str(RUNTIME_DIR / "config.yaml"))
    effective = config_loader.merge_configs(default, overlay)
    assert effective["prompt"] == ""
    assert effective["prompt_template"] == "buddy-neutral-prompt.txt"
    assert (RUNTIME_DIR / effective["prompt_template"]).read_text(encoding="utf-8").strip() == "{{ base_prompt }}"
