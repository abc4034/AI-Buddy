from buddy_brain.models import MemoryPatch
from buddy_brain.repository import BuddyRepository


def test_repository_bootstraps_demo_user_and_profile(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = BuddyRepository(db_path)
    repo.init_schema()

    profile = repo.ensure_demo_user()

    assert profile.user_id == "demo-mia"
    assert profile.name == "Mia"
    assert profile.english_level == "beginner"
    assert "animals" in profile.interests


def test_repository_bootstraps_configured_demo_user_and_device(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = BuddyRepository(
        db_path,
        demo_user_id="demo-zoe",
        demo_device_id="esp32-custom-device",
    )
    repo.init_schema()

    profile = repo.ensure_demo_user()
    device = repo.get_device("esp32-custom-device")

    assert profile.user_id == "demo-zoe"
    assert profile.name == "Mia"
    assert profile.english_level == "beginner"
    assert device["device_id"] == "esp32-custom-device"
    assert device["user_id"] == "demo-zoe"


def test_repository_persists_episodes_across_instances(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = BuddyRepository(db_path)
    repo.init_schema()
    profile = repo.ensure_demo_user()

    episode = repo.add_episode(
        user_id=profile.user_id,
        session_id="session-1",
        user_text="I like cats",
        assistant_text="Cats are cute!",
        detected_language="en",
    )

    repo2 = BuddyRepository(db_path)
    repo2.init_schema()
    recent = repo2.recent_episodes(profile.user_id, limit=5)

    assert episode.episode_id == recent[0].episode_id
    assert recent[0].user_text == "I like cats"
    assert recent[0].assistant_text == "Cats are cute!"


def test_repository_merges_memory_patch_and_records_event(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = BuddyRepository(db_path)
    repo.init_schema()
    profile = repo.ensure_demo_user()
    episode = repo.add_episode(
        user_id=profile.user_id,
        session_id="session-1",
        user_text="My favorite animal is dolphin.",
        assistant_text="Dolphins are smart animals.",
        detected_language="en",
    )

    updated = repo.apply_memory_patch(
        user_id=profile.user_id,
        episode_id=episode.episode_id,
        patch=MemoryPatch(interests_add=["dolphins"], notes_add=["likes dolphins"]),
    )

    events = repo.memory_events(profile.user_id)
    assert "dolphins" in updated.interests
    assert "likes dolphins" in updated.notes
    assert events[0]["event_type"] == "profile_patch"
