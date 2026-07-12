from collections import deque
from dataclasses import FrozenInstanceError
import math

import numpy as np
import pytest

from buddy_gateway.config import GatewaySettings
from buddy_gateway.server import build_parser
from buddy_gateway.vad import (
    IMPLEMENTED_VAD_PROVIDERS,
    PLANNED_VAD_PROVIDERS,
    SileroVADProvider,
    VADDecision,
    build_vad_provider,
    vad_provider_catalog,
)


PCM_CHUNK = b"\x00\x00" * 512
PCM_FRAME = b"\x00\x00" * 960


class SequenceRunner:
    def __init__(self, probabilities: list[float]) -> None:
        self.probabilities = deque(probabilities)
        self.inputs: list[np.ndarray] = []
        self.states: list[np.ndarray] = []

    def run(self, audio_input: np.ndarray, state: np.ndarray) -> tuple[float, np.ndarray]:
        self.inputs.append(audio_input.copy())
        self.states.append(state.copy())
        return self.probabilities.popleft(), state + 1


class SequenceClock:
    def __init__(self, times_ms: list[float]) -> None:
        self.times_ms = deque(times_ms)

    def __call__(self) -> float:
        return self.times_ms.popleft()


def make_provider(
    probabilities: list[float],
    *,
    times_ms: list[float] | None = None,
) -> tuple[SileroVADProvider, SequenceRunner]:
    runner = SequenceRunner(probabilities)
    clock = SequenceClock(times_ms or [float(index) for index in range(len(probabilities))])
    provider = SileroVADProvider(GatewaySettings(), runner=runner, monotonic_ms=clock)
    return provider, runner


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


def test_silero_hysteresis_retains_previous_chunk_state_between_thresholds():
    provider, _ = make_provider([0.6, 0.3, 0.1, 0.3, 0.6])
    session = provider.create_session()

    decisions = [session.analyze(PCM_CHUNK) for _ in range(5)]

    assert [decision.has_voice for decision in decisions] == [False, False, False, False, True]
    assert decisions[-1].speech_probability == 0.6


def test_silero_votes_at_chunk_level_and_carries_partial_60ms_frames():
    provider, runner = make_provider([0.9, 0.9, 0.9])
    session = provider.create_session()

    first = session.analyze(PCM_FRAME)
    second = session.analyze(PCM_FRAME)

    assert first.has_voice is False
    assert second.has_voice is True
    assert len(runner.inputs) == 3
    assert all(audio_input.shape == (1, 576) for audio_input in runner.inputs)


def test_silero_marks_stop_only_after_voted_speech_and_1000ms_trailing_silence():
    provider, _ = make_provider(
        [0.9, 0.9, 0.9, 0.0, 0.0, 0.0, 0.0],
        times_ms=[0.0, 100.0, 200.0, 300.0, 400.0, 1399.0, 1400.0],
    )
    session = provider.create_session()

    decisions = [session.analyze(PCM_CHUNK) for _ in range(7)]

    assert decisions[2].has_voice is True
    assert decisions[5].has_voice is False
    assert decisions[5].speech_stopped is False
    assert decisions[6].speech_stopped is True


def test_silero_reset_clears_hysteresis_window_carry_and_inference_tensors():
    provider, runner = make_provider([0.9, 0.9, 0.9, 0.9])
    session = provider.create_session()
    session.analyze(PCM_FRAME)
    session.analyze(PCM_FRAME)
    assert session.analyze(b"").has_voice is True

    session.reset()
    calls_after_reset = len(runner.inputs)
    decision = session.analyze(b"\x00\x00" * 128)

    assert len(runner.inputs) == calls_after_reset

    decision = session.analyze(b"\x00\x00" * 384)

    assert decision.has_voice is False
    assert np.count_nonzero(runner.states[-1]) == 0
    assert np.count_nonzero(runner.inputs[-1][:, :64]) == 0


def test_two_silero_sessions_keep_inference_and_voice_state_independent():
    class StateIsolationRunner:
        def __init__(self) -> None:
            self.calls_by_sample: dict[int, int] = {}

        def run(self, audio_input: np.ndarray, state: np.ndarray) -> tuple[float, np.ndarray]:
            sample = int(round(float(audio_input[0, -1]) * 32768))
            expected_state_value = self.calls_by_sample.get(sample, 0)
            assert np.all(state == expected_state_value)
            self.calls_by_sample[sample] = expected_state_value + 1
            return 0.9, np.full_like(state, expected_state_value + 1)

    provider = SileroVADProvider(GatewaySettings(), runner=StateIsolationRunner(), monotonic_ms=lambda: 0.0)
    first_session = provider.create_session()
    second_session = provider.create_session()
    first_chunk = np.full(512, 12000, dtype=np.int16).tobytes()
    second_chunk = np.full(512, 24000, dtype=np.int16).tobytes()

    first_session.analyze(first_chunk)
    first_session.analyze(first_chunk)
    second_decision = second_session.analyze(second_chunk)
    first_decision = first_session.analyze(first_chunk)

    assert first_decision.has_voice is True
    assert second_decision.has_voice is False


def test_silero_manual_mode_accepts_audio_without_running_inference():
    provider, runner = make_provider([])
    session = provider.create_session(listen_mode="manual")

    decision = session.analyze(PCM_FRAME)

    assert decision == VADDecision(speech_probability=1.0, has_voice=True, speech_stopped=False)
    assert runner.inputs == []


def test_packaged_silero_onnx_loads_on_cpu_and_analyzes_silence():
    provider = SileroVADProvider(GatewaySettings())
    session = provider.create_session()

    decision = session.analyze(PCM_FRAME)

    assert provider.execution_providers == ["CPUExecutionProvider"]
    assert math.isfinite(decision.speech_probability)
    assert 0.0 <= decision.speech_probability <= 1.0
    assert decision.has_voice is False
    assert decision.speech_stopped is False


def test_silero_vad_is_the_implemented_default_provider():
    provider = build_vad_provider(GatewaySettings())

    assert isinstance(provider, SileroVADProvider)
    assert provider.provider_name == "silero"
    assert IMPLEMENTED_VAD_PROVIDERS == ("silero",)
    assert PLANNED_VAD_PROVIDERS == ()


def test_vad_catalog_reports_silero_as_implemented():
    catalog = vad_provider_catalog(GatewaySettings())

    assert catalog == {
        "current_provider": "silero",
        "implemented": ["silero"],
        "planned": [],
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


@pytest.mark.parametrize("field", ["vad_preroll_frames", "vad_min_turn_frames"])
def test_gateway_settings_reject_non_positive_segmentation_values(field):
    with pytest.raises(ValueError, match=field):
        GatewaySettings(**{field: 0})


@pytest.mark.parametrize(
    "option",
    ["--vad-preroll-frames", "--vad-min-turn-frames"],
)
def test_gateway_vad_cli_rejects_non_positive_segmentation_values(option):
    with pytest.raises(SystemExit):
        build_parser().parse_args([option, "0"])
