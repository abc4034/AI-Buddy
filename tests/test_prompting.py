from buddy_brain.models import Episode, Profile
from buddy_brain.prompting import build_chat_messages, detect_language


def profile() -> Profile:
    return Profile(
        user_id="demo-mia",
        name="Mia",
        age_group="primary school",
        english_level="beginner",
        interests=["animals", "drawing"],
        language_preference="English first, Chinese explanation when needed",
        learning_goals=["speak simple English sentences"],
        notes=["likes dolphins"],
    )


def test_detect_language_handles_english_chinese_and_mixed():
    assert detect_language("hello buddy") == "en"
    assert detect_language("你好") == "zh"
    assert detect_language("你好 buddy") == "mixed"
    assert detect_language("123") == "unknown"


def test_build_chat_messages_includes_rules_profile_history_and_latest_user_text():
    history = [
        Episode(
            episode_id="episode-1",
            session_id="session-1",
            user_id="demo-mia",
            user_text="I like dolphins.",
            assistant_text="Dolphins are smart.",
            detected_language="en",
            created_at=1,
        )
    ]

    messages = build_chat_messages(profile(), history, "我想学动物英文")

    assert messages[0]["role"] == "system"
    assert "at most one follow-up question" in messages[0]["content"]
    assert "Mia" in messages[0]["content"]
    assert "likes dolphins" in messages[0]["content"]
    assert messages[-3]["content"] == "I like dolphins."
    assert messages[-2]["content"] == "Dolphins are smart."
    assert messages[-1]["content"] == "我想学动物英文"
