from __future__ import annotations

import re
import unicodedata

from buddy_brain.models import Episode, Profile


PERSONA_INSTRUCTIONS = {
    "cheerful": (
        "Use a cheerful, playful, and encouraging personality. "
        "celebrate effort with playful energy and a tiny spark of fun."
    ),
    "calm": (
        "Use a calm, gentle, and patient personality. "
        "slow down, reassure the child, and make the next step feel easy."
    ),
    "coach": (
        "Use a focused, coach-like personality. "
        "Give one tiny challenge, then invite the child to try again."
    ),
}


def detect_language(text: str) -> str:
    has_cjk = any("\u4e00" <= char <= "\u9fff" for char in text)
    has_latin = any(char.isascii() and char.isalpha() for char in text)
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    if has_latin:
        return "en"
    return "unknown"


def sanitize_tts_text(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"```(?:\w+)?\s*([\s\S]*?)```", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*+]\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*\d+[.)]\s+", "", cleaned)
    cleaned = cleaned.replace("*", "").replace("_", "").replace("`", "")
    cleaned = "".join(char for char in cleaned if not _is_unfriendly_tts_symbol(char))
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\s*\n\s*", " ", cleaned)
    return cleaned.strip()


def _is_unfriendly_tts_symbol(char: str) -> bool:
    if unicodedata.category(char) == "So" and ord(char) >= 0x2600:
        return True
    return char in ("\ufe0f", "\u200d")


def build_chat_messages(
    profile: Profile,
    history: list[Episode],
    user_text: str,
    persona: str = "cheerful",
) -> list[dict[str, str]]:
    persona_instruction = PERSONA_INSTRUCTIONS.get(
        persona.casefold(),
        PERSONA_INSTRUCTIONS["cheerful"],
    )
    system_prompt = "\n".join(
        [
            "You are Buddy, a warm English companion tutor for a child.",
            persona_instruction,
            "Answer Chinese, English, and mixed-language input naturally.",
            "Prefer simple English. Add one short Chinese explanation only when it helps.",
            "Keep every reply short enough for low-latency TTS.",
            "Use short sentences that are easy to speak aloud.",
            "Do not use Markdown formatting, bullets, tables, code blocks, or bold text.",
            "Ask at most one follow-up question.",
            "Correct at most one clear English mistake per turn.",
            "Introduce at most one useful new English word per turn.",
            "Avoid long grammar lectures.",
            "",
            f"Child name: {profile.name}",
            f"Age group: {profile.age_group}",
            f"English level: {profile.english_level}",
            f"Interests: {', '.join(profile.interests)}",
            f"Language preference: {profile.language_preference}",
            f"Learning goals: {', '.join(profile.learning_goals)}",
            f"Stable notes: {', '.join(profile.notes) if profile.notes else 'none'}",
        ]
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for episode in reversed(history):
        messages.append({"role": "user", "content": episode.user_text})
        messages.append({"role": "assistant", "content": episode.assistant_text})
    messages.append({"role": "user", "content": user_text})
    return messages
