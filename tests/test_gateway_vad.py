from dataclasses import FrozenInstanceError

import pytest

from buddy_gateway.config import GatewaySettings
from buddy_gateway.server import build_parser
from buddy_gateway.vad import (
    VADDecision,
    VADProviderError,
    VADProviderNotImplemented,
    build_vad_provider,
    vad_provider_catalog,
)


def test_vad_decision_is_an_immutable_frame_result():
    decision = VADDecision(
        speech_probability=0.75,
        has_voice=True,
        speech_stopped=False,
    )

    assert decision.speech_probability == 0.75
    assert decision.has_voice is True
    assert decision.speech_stopped is False
    with pytest.raises(FrozenInstanceError):
        decision.has_voice = False


def test_silero_vad_is_selectable_but_fails_as_a_planned_provider():
    provider = build_vad_provider(GatewaySettings())

    assert isinstance(provider, VADProviderNotImplemented)
    assert provider.provider_name == "silero"
    with pytest.raises(VADProviderError, match="VAD provider 'silero' is planned but not implemented"):
        provider.create_session()


def test_vad_catalog_reports_stable_planned_provider_slot():
    catalog = vad_provider_catalog(GatewaySettings())

    assert catalog == {
        "current_provider": "silero",
        "implemented": [],
        "planned": ["silero"],
    }


def test_gateway_vad_settings_use_binding_defaults():
    settings = GatewaySettings()

    assert settings.vad_provider == "silero"
    assert settings.vad_threshold == 0.5
    assert settings.vad_threshold_low == 0.2
    assert settings.vad_min_silence_ms == 1000
    assert settings.vad_window_size == 5
    assert settings.vad_voice_votes == 3
    assert settings.vad_preroll_frames == 10
    assert settings.vad_min_turn_frames == 16


def test_gateway_vad_cli_accepts_environment_overrides(monkeypatch):
    monkeypatch.setenv("VAD_PROVIDER", "silero")
    monkeypatch.setenv("VAD_THRESHOLD", "0.65")
    monkeypatch.setenv("VAD_THRESHOLD_LOW", "0.15")
    monkeypatch.setenv("VAD_MIN_SILENCE_MS", "750")
    monkeypatch.setenv("VAD_WINDOW_SIZE", "7")
    monkeypatch.setenv("VAD_VOICE_VOTES", "4")
    monkeypatch.setenv("VAD_PREROLL_FRAMES", "12")
    monkeypatch.setenv("VAD_MIN_TURN_FRAMES", "20")

    args = build_parser().parse_args([])

    assert args.vad_provider == "silero"
    assert args.vad_threshold == 0.65
    assert args.vad_threshold_low == 0.15
    assert args.vad_min_silence_ms == 750
    assert args.vad_window_size == 7
    assert args.vad_voice_votes == 4
    assert args.vad_preroll_frames == 12
    assert args.vad_min_turn_frames == 20
