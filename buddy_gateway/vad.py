from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from importlib.resources import files
import time
from typing import Any, Callable, Protocol

import numpy as np
import onnxruntime


IMPLEMENTED_VAD_PROVIDERS = ("silero",)
PLANNED_VAD_PROVIDERS: tuple[str, ...] = ()

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512
CONTEXT_SAMPLES = 64


class VADProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class VADDecision:
    speech_probability: float
    has_voice: bool
    speech_stopped: bool


class VADSession(Protocol):
    def analyze(self, pcm_frame: bytes) -> VADDecision:
        ...

    def reset(self) -> None:
        ...

    def close(self) -> None:
        ...


class VADProvider(Protocol):
    provider_name: str

    def create_session(self, listen_mode: str = "auto") -> VADSession:
        ...


class SileroInferenceRunner(Protocol):
    def run(self, audio_input: np.ndarray, state: np.ndarray) -> tuple[float, np.ndarray]:
        ...


class OnnxSileroRunner:
    def __init__(self, model_path: str | None = None) -> None:
        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        resolved_model_path = model_path or str(files("buddy_gateway").joinpath("assets", "silero_vad.onnx"))
        self.session = onnxruntime.InferenceSession(
            resolved_model_path,
            providers=["CPUExecutionProvider"],
            sess_options=options,
        )

    @property
    def execution_providers(self) -> list[str]:
        return self.session.get_providers()

    def run(self, audio_input: np.ndarray, state: np.ndarray) -> tuple[float, np.ndarray]:
        output, next_state = self.session.run(
            None,
            {
                "input": audio_input,
                "state": state,
                "sr": np.array(SAMPLE_RATE, dtype=np.int64),
            },
        )
        return float(output.item()), next_state


class SileroVADSession:
    def __init__(
        self,
        *,
        runner: SileroInferenceRunner,
        monotonic_ms: Callable[[], float],
        listen_mode: str,
        threshold: float,
        threshold_low: float,
        min_silence_ms: int,
        window_size: int,
        voice_votes: int,
    ) -> None:
        self._runner = runner
        self._monotonic_ms = monotonic_ms
        self.listen_mode = listen_mode
        self.threshold = threshold
        self.threshold_low = threshold_low
        self.min_silence_ms = min_silence_ms
        self.window_size = window_size
        self.voice_votes = voice_votes
        self._closed = False
        self.reset()

    def analyze(self, pcm_frame: bytes) -> VADDecision:
        if self._closed:
            raise VADProviderError("VAD session is closed")
        if self.listen_mode == "manual":
            return VADDecision(speech_probability=1.0, has_voice=True, speech_stopped=False)

        self._pcm_carry.extend(pcm_frame)
        chunk_byte_count = CHUNK_SAMPLES * 2
        last_chunk_at_ms: float | None = None

        while len(self._pcm_carry) >= chunk_byte_count:
            chunk = bytes(self._pcm_carry[:chunk_byte_count])
            del self._pcm_carry[:chunk_byte_count]
            self._last_probability = self._analyze_chunk(chunk)
            last_chunk_at_ms = self._monotonic_ms()
            self._has_voice = sum(self._voice_window) >= self.voice_votes
            if self._has_voice:
                self._speech_started = True
                self._last_voice_at_ms = last_chunk_at_ms

        speech_stopped = False
        if (
            last_chunk_at_ms is not None
            and self._speech_started
            and not self._has_voice
            and self._last_voice_at_ms is not None
        ):
            speech_stopped = last_chunk_at_ms - self._last_voice_at_ms >= self.min_silence_ms

        return VADDecision(
            speech_probability=self._last_probability,
            has_voice=self._has_voice,
            speech_stopped=speech_stopped,
        )

    def _analyze_chunk(self, chunk: bytes) -> float:
        audio_int16 = np.frombuffer(chunk, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        audio_input = np.concatenate(
            [self._context, audio_float32.reshape(1, -1)],
            axis=1,
        ).astype(np.float32)
        probability, self._state = self._runner.run(audio_input, self._state)
        self._context = audio_input[:, -CONTEXT_SAMPLES:]

        if probability >= self.threshold:
            self._last_is_voice = True
        elif probability <= self.threshold_low:
            self._last_is_voice = False
        self._voice_window.append(self._last_is_voice)
        return probability

    def reset(self) -> None:
        if self._closed:
            return
        self._pcm_carry = bytearray()
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)
        self._voice_window: deque[bool] = deque(maxlen=self.window_size)
        self._last_is_voice = False
        self._last_probability = 0.0
        self._has_voice = False
        self._speech_started = False
        self._last_voice_at_ms: float | None = None

    def close(self) -> None:
        if self._closed:
            return
        self.reset()
        self._closed = True


class SileroVADProvider:
    provider_name = "silero"

    def __init__(
        self,
        settings: Any,
        *,
        runner: SileroInferenceRunner | None = None,
        monotonic_ms: Callable[[], float] | None = None,
    ) -> None:
        self._runner = runner or OnnxSileroRunner()
        self._monotonic_ms = monotonic_ms or (lambda: time.monotonic() * 1000.0)
        self._threshold = float(getattr(settings, "vad_threshold", 0.5))
        self._threshold_low = float(getattr(settings, "vad_threshold_low", 0.2))
        self._min_silence_ms = int(getattr(settings, "vad_min_silence_ms", 1000))
        self._window_size = int(getattr(settings, "vad_window_size", 5))
        self._voice_votes = int(getattr(settings, "vad_voice_votes", 3))

    @property
    def execution_providers(self) -> list[str]:
        return list(getattr(self._runner, "execution_providers", []))

    def create_session(self, listen_mode: str = "auto") -> SileroVADSession:
        return SileroVADSession(
            runner=self._runner,
            monotonic_ms=self._monotonic_ms,
            listen_mode=listen_mode,
            threshold=self._threshold,
            threshold_low=self._threshold_low,
            min_silence_ms=self._min_silence_ms,
            window_size=self._window_size,
            voice_votes=self._voice_votes,
        )


def build_vad_provider(settings: Any) -> VADProvider:
    provider_name = str(getattr(settings, "vad_provider", "silero") or "silero").strip().lower()
    if provider_name == "silero":
        return SileroVADProvider(settings)
    raise VADProviderError(f"Unknown VAD provider '{provider_name}'")


def vad_provider_catalog(settings: Any) -> dict[str, Any]:
    return {
        "current_provider": str(getattr(settings, "vad_provider", "silero") or "silero"),
        "implemented": list(IMPLEMENTED_VAD_PROVIDERS),
        "planned": list(PLANNED_VAD_PROVIDERS),
    }
