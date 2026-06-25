from __future__ import annotations

from buddy_brain.models import Episode, Profile


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


def build_chat_messages(
    profile: Profile,
    history: list[Episode],
    user_text: str,
) -> list[dict[str, str]]:
    system_prompt = "\n".join(
        [
            "You are Buddy, a warm English companion tutor for a child.",
            "Answer Chinese, English, and mixed-language input naturally.",
            "Prefer simple English. Add one short Chinese explanation only when it helps.",
            "Keep every reply short enough for low-latency TTS.",
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
