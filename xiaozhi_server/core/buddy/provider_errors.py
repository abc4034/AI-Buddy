from __future__ import annotations


class ASRProviderFailure(RuntimeError):
    """A provider failure that must remain distinct from valid ASR silence."""

    def __init__(self, public_code: str, *, provider_status_code: int | None = None) -> None:
        self.public_code = public_code
        self.provider_status_code = provider_status_code
        super().__init__(public_code)


class BuddyProviderFailure(RuntimeError):
    """A public Buddy Core failure code suitable for bounded diagnostics."""

    def __init__(self, public_code: str, message: str | None = None) -> None:
        self.public_code = public_code
        super().__init__(message or public_code)


class TTSProviderFailure(RuntimeError):
    """A public synthesis failure code suitable for bounded diagnostics."""

    def __init__(self, public_code: str = "tts_failed", message: str | None = None) -> None:
        self.public_code = public_code
        super().__init__(message or public_code)
