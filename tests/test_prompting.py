from buddy_brain.models import Episode, Profile
from buddy_brain.prompting import build_chat_messages, detect_language, sanitize_tts_text


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


def test_build_chat_messages_uses_configured_persona():
    messages = build_chat_messages(profile(), [], "hello", persona="calm")

    assert "calm, gentle, and patient" in messages[0]["content"]
    assert "cheerful" not in messages[0]["content"]


def test_build_chat_messages_defines_distinct_persona_behaviors():
    prompts = {
        name: build_chat_messages(profile(), [], "hello", persona=name)[0]["content"]
        for name in ("cheerful", "calm", "coach")
    }

    assert "celebrate effort" in prompts["cheerful"]
    assert "playful energy" in prompts["cheerful"]
    assert "slow down" in prompts["calm"]
    assert "reassure the child" in prompts["calm"]
    assert "one tiny challenge" in prompts["coach"]
    assert "invite the child to try again" in prompts["coach"]
    assert len(set(prompts.values())) == 3


def test_build_chat_messages_restricts_markdown_for_tts():
    messages = build_chat_messages(profile(), [], "hello")

    assert "Do not use Markdown formatting" in messages[0]["content"]
    assert "easy to speak aloud" in messages[0]["content"]


def test_sanitize_tts_text_removes_markdown_and_emoji():
    text = 'Wow! 🦖 Say: **Dinosaurs are cool.**\n- Try `I can draw.`'

    assert sanitize_tts_text(text) == "Wow! Say: Dinosaurs are cool. Try I can draw."
