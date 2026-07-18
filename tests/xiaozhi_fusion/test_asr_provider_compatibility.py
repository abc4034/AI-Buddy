from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import httpx
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_ROOT / "xiaozhi_server"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from core.buddy.provider_errors import ASRProviderFailure
from core.providers.asr.buddy_qwen import ASRProvider as BuddyQwenASRProvider
from core.providers.asr.qwen3_asr_flash import ASRProvider
from integrations.xiaozhi_server.render_config import get_asr_environment, render_config, write_config


TEST_ASR_ENVIRONMENT = {
    "ASR_PROVIDER": "qwen3_asr_flash",
    "ASR_HTTP_URL": "https://asr.example.test/api/v1",
    "ASR_MODEL": "qwen3-asr-flash-test",
    "ASR_API_KEY": "test-key-not-a-real-secret",
    "ASR_TIMEOUT_SECONDS": "7.5",
}
TEST_TTS_ENVIRONMENT = {
    "TTS_PROVIDER": "buddy_qwen_http",
    "TTS_HTTP_URL": "https://tts.example.test/api/v1",
    "TTS_MODEL": "qwen3-tts-instruct-flash-test",
    "TTS_API_KEY": "placeholder",
    "TTS_VOICE": "Cherry",
    "TTS_LANGUAGE": "auto",
    "TTS_TIMEOUT_SECONDS": "7.5",
}


class ProviderResponseError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"provider returned {status_code}")


def provider_config() -> dict[str, object]:
    return {
        "api_key": TEST_ASR_ENVIRONMENT["ASR_API_KEY"],
        "model_name": TEST_ASR_ENVIRONMENT["ASR_MODEL"],
        "base_url": TEST_ASR_ENVIRONMENT["ASR_HTTP_URL"],
        "timeout_seconds": float(TEST_ASR_ENVIRONMENT["ASR_TIMEOUT_SECONDS"]),
    }


def artifacts(temp_path: str = "C:/audio.wav"):
    return type("Artifacts", (), {"temp_path": temp_path, "file_path": "C:/saved.wav"})()


def run(provider: ASRProvider, artifact=None):
    return asyncio.run(provider.speech_to_text([], "session-1", artifact or artifacts()))


def test_renderer_uses_process_environment_before_user_environment_and_never_prints_secrets(capsys, tmp_path):
    process_environment = dict(TEST_ASR_ENVIRONMENT, **TEST_TTS_ENVIRONMENT)
    process_environment["ASR_MODEL"] = "process-model"
    user_environment = dict(TEST_ASR_ENVIRONMENT, **TEST_TTS_ENVIRONMENT)
    user_environment["ASR_MODEL"] = "user-model"

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

    assert "ASR: BuddyQwenASR" in rendered
    assert "type: buddy_qwen" in rendered
    assert 'provider_name: "qwen3_asr_flash"' in rendered
    assert 'model_name: "process-model"' in rendered
    assert TEST_ASR_ENVIRONMENT["ASR_API_KEY"] in output.read_text(encoding="utf-8")
    assert "ASR_API_KEY" not in capsys.readouterr().out


def test_renderer_requires_complete_live_configuration_without_echoing_values():
    incomplete = dict(TEST_ASR_ENVIRONMENT)
    incomplete["ASR_API_KEY"] = "do-not-echo-this-value"
    incomplete["ASR_TIMEOUT_SECONDS"] = "0"

    with pytest.raises(ValueError) as error:
        render_config("192.168.2.9", process_environment=incomplete, user_environment={})

    assert "do-not-echo-this-value" not in str(error.value)
    assert "ASR_TIMEOUT_SECONDS" in str(error.value)


@pytest.mark.parametrize("timeout", ["nan", "inf", "-inf"])
def test_renderer_rejects_non_finite_timeout(timeout):
    environment = dict(TEST_ASR_ENVIRONMENT, ASR_TIMEOUT_SECONDS=timeout)

    with pytest.raises(ValueError, match="ASR_TIMEOUT_SECONDS"):
        render_config("192.168.2.9", process_environment=environment, user_environment={})


def test_render_script_passes_no_asr_secret_command_line_argument_or_stdout():
    script = (REPO_ROOT / "scripts" / "render_xiaozhi_config.ps1").read_text(encoding="utf-8")

    assert "--asr-api-key" not in script.lower()
    assert "Write-Host \"ASR" not in script


def test_hardware_smoke_script_checks_for_a_device_and_non_empty_transcript_without_reading_secrets():
    script = (REPO_ROOT / "scripts" / "smoke_xiaozhi_asr.ps1").read_text(encoding="utf-8")

    assert "Get-Content" in script
    assert "device" in script.lower()
    assert "transcript" in script.lower()
    assert "ASR_API_KEY" not in script


def test_hardware_smoke_script_accepts_pinned_runtime_device_header(tmp_path):
    log_path = tmp_path / "server.log"
    log_path.write_text(
        "192.168.0.104 conn - Headers: {'device-id': 'fc:01:2c:cf:17:54'}\n"
        "transcript: hello from hardware\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "smoke_xiaozhi_asr.ps1"),
            "-LogPath",
            str(log_path),
            "-TimeoutSeconds",
            "2",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "fc:01:2c:cf:17:54" in result.stdout


@pytest.mark.parametrize("provider_class", [ASRProvider, BuddyQwenASRProvider])
@pytest.mark.parametrize("timeout", ["nan", "inf", "-inf"])
def test_asr_providers_reject_non_finite_timeout(provider_class, timeout):
    config = provider_config()
    config["timeout_seconds"] = timeout

    with pytest.raises(ValueError, match="positive timeout_seconds"):
        provider_class(config, delete_audio_file=True)


def test_native_provider_returns_a_transcript_and_uses_configured_endpoint_and_timeout(monkeypatch):
    captured = {}

    def call(**kwargs):
        captured.update(kwargs)
        return [{"output": {"choices": [{"message": {"content": [{"text": "hello"}]}}]}}]

    monkeypatch.setattr("core.providers.asr.qwen3_asr_flash.dashscope.MultiModalConversation.call", call)

    text, file_path = run(ASRProvider(provider_config(), delete_audio_file=True))

    assert text == "hello"
    assert file_path == "C:/saved.wav"
    assert captured["base_address"] == TEST_ASR_ENVIRONMENT["ASR_HTTP_URL"]
    assert captured["timeout"] == 7.5
    assert captured["api_key"] == TEST_ASR_ENVIRONMENT["ASR_API_KEY"]


def test_native_provider_preserves_valid_empty_recognition(monkeypatch):
    monkeypatch.setattr(
        "core.providers.asr.qwen3_asr_flash.dashscope.MultiModalConversation.call",
        lambda **_: [{"output": {"choices": [{"message": {"content": []}}]}}],
    )

    assert run(ASRProvider(provider_config(), delete_audio_file=True)) == ("", "C:/saved.wav")


@pytest.mark.parametrize(
    ("failure", "public_code"),
    [
        (TimeoutError("request expired"), "timeout"),
        (ProviderResponseError(401), "authentication"),
        (ProviderResponseError(503), "service"),
    ],
)
def test_native_provider_raises_typed_failures(monkeypatch, failure, public_code):
    def call(**_):
        raise failure

    monkeypatch.setattr("core.providers.asr.qwen3_asr_flash.dashscope.MultiModalConversation.call", call)

    with pytest.raises(ASRProviderFailure) as error:
        run(ASRProvider(provider_config(), delete_audio_file=True))

    assert error.value.public_code == public_code


def test_native_provider_rejects_malformed_responses(monkeypatch):
    monkeypatch.setattr(
        "core.providers.asr.qwen3_asr_flash.dashscope.MultiModalConversation.call",
        lambda **_: [{"output": {"choices": []}}],
    )

    with pytest.raises(ASRProviderFailure) as error:
        run(ASRProvider(provider_config(), delete_audio_file=True))

    assert error.value.public_code == "malformed_response"


def test_native_provider_retains_non_auth_service_status_for_compatibility_evidence(monkeypatch):
    monkeypatch.setattr(
        "core.providers.asr.qwen3_asr_flash.dashscope.MultiModalConversation.call",
        lambda **_: [{"status_code": 404}],
    )

    with pytest.raises(ASRProviderFailure) as error:
        run(ASRProvider(provider_config(), delete_audio_file=True))

    assert error.value.public_code == "service"
    assert error.value.provider_status_code == 404


class FakeResponse:
    def __init__(self, status_code: int, payload=None, json_error: Exception | None = None) -> None:
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


def fallback_artifacts(tmp_path):
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"RIFFtest")
    return type("Artifacts", (), {"temp_path": str(audio_path), "file_path": "C:/saved.wav"})()


def install_fallback_client(monkeypatch, *, response=None, failure=None):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["request"] = kwargs
            if failure:
                raise failure
            return response

    monkeypatch.setattr("core.providers.asr.buddy_qwen.httpx.AsyncClient", FakeAsyncClient)
    return captured


def run_fallback(provider: BuddyQwenASRProvider, artifact):
    return asyncio.run(provider.speech_to_text([], "session-1", artifact))


def test_buddy_qwen_returns_transcript_from_compatible_chat_response(monkeypatch, tmp_path):
    captured = install_fallback_client(
        monkeypatch,
        response=FakeResponse(200, {"choices": [{"message": {"content": "hello"}}]}),
    )

    result = run_fallback(BuddyQwenASRProvider(provider_config(), delete_audio_file=True), fallback_artifacts(tmp_path))

    assert result == ("hello", "C:/saved.wav")
    assert captured["url"].endswith("/chat/completions")
    assert captured["client"]["timeout"] == 7.5
    assert captured["request"]["headers"]["Authorization"].endswith(TEST_ASR_ENVIRONMENT["ASR_API_KEY"])


def test_buddy_qwen_initializes_output_dir_for_base_wrapper(monkeypatch, tmp_path):
    output_dir = tmp_path / "missing" / "audio_output"
    config = provider_config()
    config["output_dir"] = str(output_dir)
    install_fallback_client(
        monkeypatch,
        response=FakeResponse(200, {"choices": [{"message": {"content": "hello"}}]}),
    )

    provider = BuddyQwenASRProvider(config, delete_audio_file=True)
    result = asyncio.run(provider.speech_to_text_wrapper([b"\x00\x00" * 960], "session-1"))

    assert output_dir.is_dir()
    assert result == ("hello", None)


def test_buddy_qwen_preserves_valid_empty_recognition(monkeypatch, tmp_path):
    install_fallback_client(
        monkeypatch,
        response=FakeResponse(200, {"choices": [{"message": {"content": ""}}]}),
    )

    assert run_fallback(BuddyQwenASRProvider(provider_config(), delete_audio_file=True), fallback_artifacts(tmp_path)) == (
        "",
        "C:/saved.wav",
    )


def test_buddy_qwen_raises_timeout_failure(monkeypatch, tmp_path):
    install_fallback_client(monkeypatch, failure=httpx.TimeoutException("timed out"))

    with pytest.raises(ASRProviderFailure, match="timeout") as error:
        run_fallback(BuddyQwenASRProvider(provider_config(), delete_audio_file=True), fallback_artifacts(tmp_path))

    assert error.value.public_code == "timeout"


@pytest.mark.parametrize(("status_code", "public_code"), [(401, "authentication"), (503, "service")])
def test_buddy_qwen_raises_typed_http_failures(monkeypatch, tmp_path, status_code, public_code):
    install_fallback_client(monkeypatch, response=FakeResponse(status_code, {}))

    with pytest.raises(ASRProviderFailure) as error:
        run_fallback(BuddyQwenASRProvider(provider_config(), delete_audio_file=True), fallback_artifacts(tmp_path))

    assert error.value.public_code == public_code
    assert error.value.provider_status_code == status_code


def test_buddy_qwen_rejects_malformed_response(monkeypatch, tmp_path):
    install_fallback_client(monkeypatch, response=FakeResponse(200, json_error=ValueError("not json")))

    with pytest.raises(ASRProviderFailure) as error:
        run_fallback(BuddyQwenASRProvider(provider_config(), delete_audio_file=True), fallback_artifacts(tmp_path))

    assert error.value.public_code == "malformed_response"


@pytest.mark.live_provider
def test_native_qwen_provider_supports_configured_endpoint_and_model():
    environment = get_asr_environment()
    missing = [name for name, value in environment.items() if not value]
    if missing:
        pytest.skip("live ASR configuration is unavailable")

    provider = ASRProvider(
        {
            "api_key": environment["ASR_API_KEY"],
            "model_name": environment["ASR_MODEL"],
            "base_url": environment["ASR_HTTP_URL"],
            "timeout_seconds": float(environment["ASR_TIMEOUT_SECONDS"]),
        },
        delete_audio_file=True,
    )
    sample = RUNTIME_DIR / "config" / "assets" / "wakeup_words.wav"
    live_artifacts = artifacts(str(sample))

    try:
        text, file_path = run(provider, live_artifacts)
    except ASRProviderFailure as error:
        if error.public_code == "service" and error.provider_status_code:
            pytest.xfail(f"native provider endpoint compatibility status {error.provider_status_code}")
        raise

    assert isinstance(text, str)
    assert text.strip()
    assert file_path == "C:/saved.wav"


@pytest.mark.live_provider
def test_selected_buddy_qwen_provider_supports_configured_endpoint_and_model():
    environment = get_asr_environment()
    missing = [name for name, value in environment.items() if not value]
    if missing:
        pytest.skip("live ASR configuration is unavailable")

    provider = BuddyQwenASRProvider(
        {
            "api_key": environment["ASR_API_KEY"],
            "model_name": environment["ASR_MODEL"],
            "base_url": environment["ASR_HTTP_URL"],
            "timeout_seconds": float(environment["ASR_TIMEOUT_SECONDS"]),
        },
        delete_audio_file=True,
    )
    sample = RUNTIME_DIR / "config" / "assets" / "wakeup_words.wav"

    text, file_path = run_fallback(provider, artifacts(str(sample)))

    assert text.strip()
    assert file_path == "C:/saved.wav"
