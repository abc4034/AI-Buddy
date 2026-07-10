from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


IMPLEMENTED_VAD_PROVIDERS: tuple[str, ...] = ()
PLANNED_VAD_PROVIDERS = ("silero",)


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


class VADProviderNotImplemented:
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def create_session(self, listen_mode: str = "auto") -> VADSession:
        raise VADProviderError(f"VAD provider '{self.provider_name}' is planned but not implemented")


def build_vad_provider(settings: Any) -> VADProvider:
    provider_name = str(getattr(settings, "vad_provider", "silero") or "silero").strip().lower()
    if provider_name in PLANNED_VAD_PROVIDERS:
        return VADProviderNotImplemented(provider_name)
    raise VADProviderError(f"Unknown VAD provider '{provider_name}'")


def vad_provider_catalog(settings: Any) -> dict[str, Any]:
    return {
        "current_provider": str(getattr(settings, "vad_provider", "silero") or "silero"),
        "implemented": list(IMPLEMENTED_VAD_PROVIDERS),
        "planned": list(PLANNED_VAD_PROVIDERS),
    }
