from __future__ import annotations

import asyncio
import base64
import importlib
import sys
from pathlib import Path

import pytest
import requests


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_ROOT / "xiaozhi_server"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from integrations.xiaozhi_server.render_config import get_tts_environment, render_config, write_config


TEST_TTS_ENVIRONMENT = {
    "TTS_PROVIDER": "buddy_qwen_http",
    "TTS_HTTP_URL": "https://tts.example.test/api/v1",
    "TTS_MODEL": "qwen3-tts-instruct-flash-test",
    "TTS_API_KEY": "test-key-not-a-real-secret",
    "TTS_VOICE": "Cherry",
    "TTS_LANGUAGE": "English",
    "TTS_TIMEOUT_SECONDS": "7.5",
}
TEST_ASR_ENVIRONMENT = {
    "ASR_PROVIDER": "qwen3_asr_flash",
    "ASR_HTTP_URL": "https://asr.example.test/api/v1",
    "ASR_MODEL": "qwen3-asr-flash-test",
    "ASR_API_KEY": "test-asr-key-not-a-real-secret",
    "ASR_TIMEOUT_SECONDS": "7.5",
}


def render_environment(**overrides: str) -> dict[str, str]:
    environment = dict(TEST_ASR_ENVIRONMENT)
    environment.update(TEST_TTS_ENVIRONMENT)
    environment.update(overrides)
    return environment


def provider_config() -> dict[str, object]:
    return {
        "api_key": TEST_TTS_ENVIRONMENT["TTS_API_KEY"],
        "api_url": TEST_TTS_ENVIRONMENT["TTS_HTTP_URL"],
        "model": TEST_TTS_ENVIRONMENT["TTS_MODEL"],
        "voice": TEST_TTS_ENVIRONMENT["TTS_VOICE"],
        "language": TEST_TTS_ENVIRONMENT["TTS_LANGUAGE"],
        "timeout_seconds": float(TEST_TTS_ENVIRONMENT["TTS_TIMEOUT_SECONDS"]),
    }


def provider():
    module = importlib.import_module("core.providers.tts.buddy_qwen_http")
    return module.TTSProvider(provider_config(), delete_audio_file=True)


class FakeResponse:
    def __init__(self, status_code: int, *, content: bytes = b"", payload=None, json_error: Exception | None = None):
        self.status_code = status_code
        self.content = content
        self.payload = payload
        self.json_error = json_error
        self.headers = {"content-type": "application/json"}
        self.text = "provider response"

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


def install_requests(monkeypatch, *, post_response=None, get_response=None, post_failure=None):
    captured = {}

    def post(url, **kwargs):
        captured["post_url"] = url
        captured["post"] = kwargs
        if post_failure:
            raise post_failure
        return post_response

    def get(url, **kwargs):
        captured["get_url"] = url
        captured["get"] = kwargs
        return get_response

    monkeypatch.setattr("core.providers.tts.buddy_qwen_http.requests.post", post)
    monkeypatch.setattr("core.providers.tts.buddy_qwen_http.requests.get", get)
    return captured


def test_flat_loader_resolves_the_buddy_qwen_tts_provider(monkeypatch):
    from core.providers.tts.base import TTSProviderBase
    from core.utils.tts import create_instance

    monkeypatch.chdir(RUNTIME_DIR)
    instance = create_instance("buddy_qwen_http", provider_config(), True)

    assert isinstance(instance, TTSProviderBase)


def test_provider_returns_inline_audio_and_honors_configured_request_settings(monkeypatch):
    audio = b"RIFF-inline-audio"
    captured = install_requests(
        monkeypatch,
        post_response=FakeResponse(
            200,
            payload={"output": {"audio": {"data": base64.b64encode(audio).decode("ascii"), "format": "wav"}}},
        ),
    )

    result = asyncio.run(provider().text_to_speak(" hello ", None))

    assert result == audio
    assert captured["post_url"].endswith("/services/aigc/multimodal-generation/generation")
    assert captured["post"]["timeout"] == 7.5
    assert captured["post"]["headers"]["Authorization"].endswith(TEST_TTS_ENVIRONMENT["TTS_API_KEY"])
    assert captured["post"]["json"] == {
        "model": TEST_TTS_ENVIRONMENT["TTS_MODEL"],
        "input": {"text": "hello", "voice": TEST_TTS_ENVIRONMENT["TTS_VOICE"], "language_type": "English"},
    }


def test_provider_downloads_audio_url_and_writes_requested_output_file(monkeypatch, tmp_path):
    audio = b"RIFF-downloaded-audio"
    captured = install_requests(
        monkeypatch,
        post_response=FakeResponse(200, payload={"output": {"audio": {"url": "https://audio.example.test/result.wav"}}}),
        get_response=FakeResponse(200, content=audio),
    )
    output_file = tmp_path / "speech.wav"

    result = asyncio.run(provider().text_to_speak("Hello", str(output_file)))

    assert result is None
    assert output_file.read_bytes() == audio
    assert captured["get_url"] == "https://audio.example.test/result.wav"
    assert captured["get"]["timeout"] == 7.5


@pytest.mark.parametrize(
    ("post_response", "post_failure", "expected"),
    [
        (None, requests.Timeout("request expired"), "timeout"),
        (FakeResponse(401, payload={}), None, "authentication"),
        (FakeResponse(503, payload={}), None, "service"),
        (FakeResponse(200, json_error=ValueError("not json")), None, "malformed"),
    ],
)
def test_provider_raises_redacted_errors_for_request_failures(monkeypatch, post_response, post_failure, expected):
    install_requests(monkeypatch, post_response=post_response, post_failure=post_failure)

    with pytest.raises(RuntimeError, match=expected) as error:
        asyncio.run(provider().text_to_speak("Hello", None))

    assert TEST_TTS_ENVIRONMENT["TTS_API_KEY"] not in str(error.value)


def test_provider_source_contains_only_synthesis_and_audio_retrieval_logic():
    source = (RUNTIME_DIR / "core" / "providers" / "tts" / "buddy_qwen_http.py").read_text(encoding="utf-8").lower()

    for forbidden in ("websocket", "opus", "queue", "vad", "playback", "abort", "connection-state"):
        assert forbidden not in source


def test_renderer_uses_process_tts_environment_before_user_environment_without_printing_secret(capsys, tmp_path):
    process_environment = render_environment(TTS_MODEL="process-model")
    user_environment = render_environment(TTS_MODEL="user-model")

    rendered = render_config(
        "192.168.2.9",
        process_environment=process_environment,
        user_environment=user_environment,
    )
    output = tmp_path / "xiaozhi_server" / "data" / ".config.yaml"
    write_config(
        "192.168.2.9",
        output,
        repo_root=tmp_path,
        process_environment=process_environment,
        user_environment=user_environment,
    )

    assert "TTS: BuddyQwenTTS" in rendered
    assert 'type: "buddy_qwen_http"' in rendered
    assert 'model: "process-model"' in rendered
    assert TEST_TTS_ENVIRONMENT["TTS_API_KEY"] in output.read_text(encoding="utf-8")
    assert TEST_TTS_ENVIRONMENT["TTS_API_KEY"] not in capsys.readouterr().out
    assert get_tts_environment(process_environment=process_environment, user_environment=user_environment)["TTS_MODEL"] == "process-model"


def test_renderer_rejects_incomplete_or_invalid_live_tts_configuration_without_echoing_values():
    incomplete = render_environment(TTS_API_KEY="do-not-echo-this-value", TTS_TIMEOUT_SECONDS="0")

    with pytest.raises(ValueError) as error:
        render_config("192.168.2.9", process_environment=incomplete, user_environment={})

    assert "do-not-echo-this-value" not in str(error.value)
    assert "TTS_TIMEOUT_SECONDS" in str(error.value)


def test_renderer_rejects_an_unexpected_tts_provider():
    environment = render_environment(TTS_PROVIDER="some_other_provider")

    with pytest.raises(ValueError, match="TTS_PROVIDER"):
        render_config("192.168.2.9", process_environment=environment, user_environment={})


def test_render_script_injects_tts_environment_without_passing_or_printing_secrets():
    script = (REPO_ROOT / "scripts" / "render_xiaozhi_config.ps1").read_text(encoding="utf-8")

    assert "Assert-LiveTtsEnvironment" in script
    assert "TTS_API_KEY" in script
    assert "--tts-api-key" not in script.lower()
    assert 'Write-Host "TTS' not in script


def test_tts_smoke_observes_native_queue_output_without_reading_tts_secrets():
    script = (REPO_ROOT / "scripts" / "smoke_xiaozhi_tts.ps1").read_text(encoding="utf-8")

    assert "integrations.xiaozhi_server.smoke_tts" in script
    assert "Get-Content" not in script
    assert "TTS_API_KEY" not in script


def test_tts_smoke_drives_the_selected_provider_through_native_send_path(monkeypatch, tmp_path):
    from integrations.xiaozhi_server import smoke_tts

    config_path = tmp_path / ".config.yaml"
    config_path.write_text(
        """
selected_module:
  TTS: BuddyQwenTTS
TTS:
  BuddyQwenTTS:
    type: buddy_qwen_http
    api_key: placeholder
    api_url: https://tts.example.test/api/v1
    model: fixture-model
    voice: Cherry
""".strip(),
        encoding="utf-8",
    )

    class FakeProvider:
        tts_audio_first_sentence = True
        conn = None

        def to_tts(self, text):
            assert text == "known turn"
            return [b"opus-a", b"opus-b"]

    monkeypatch.setattr(smoke_tts, "create_instance", lambda provider_type, config, delete: FakeProvider())

    result = smoke_tts.run_smoke(config_path, "known turn")

    assert result.provider_type == "buddy_qwen_http"
    assert result.opus_frame_count == 2
    assert result.tts_start_count == 1


def test_tts_smoke_rejects_an_inactive_runtime_provider(tmp_path):
    from integrations.xiaozhi_server import smoke_tts

    config_path = tmp_path / ".config.yaml"
    config_path.write_text("selected_module: {TTS: OtherTTS}\nTTS: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="BuddyQwenTTS"):
        smoke_tts.run_smoke(config_path, "known turn")
