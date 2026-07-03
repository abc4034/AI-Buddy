from buddy_brain.config import DeviceProfileConfig
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


def test_repository_creates_distinct_profile_for_new_device(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = BuddyRepository(db_path)
    repo.init_schema()
    repo.ensure_demo_user()

    profile = repo.ensure_profile_for_device("esp32-child-a", client_id="client-a")
    device = repo.get_device("esp32-child-a")

    assert profile.user_id == "device-esp32-child-a"
    assert profile.name == "Mia"
    assert device["device_id"] == "esp32-child-a"
    assert device["client_id"] == "client-a"
    assert device["user_id"] == "device-esp32-child-a"


def test_repository_uses_configured_profile_for_known_device(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = BuddyRepository(
        db_path,
        device_profiles={
            "esp32-luna": DeviceProfileConfig(
                child_name="Luna",
                age_group="kindergarten",
                english_level="starter",
                persona="coach",
            )
        },
    )
    repo.init_schema()

    profile = repo.ensure_profile_for_device("esp32-luna")

    assert profile.user_id == "device-esp32-luna"
    assert profile.name == "Luna"
    assert profile.age_group == "kindergarten"
    assert profile.english_level == "starter"


def test_repository_applies_configured_profile_to_existing_device(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = BuddyRepository(db_path)
    repo.init_schema()
    original = repo.ensure_profile_for_device("esp32-luna")
    assert original.name == "Mia"

    configured_repo = BuddyRepository(
        db_path,
        device_profiles={
            "esp32-luna": DeviceProfileConfig(
                child_name="Luna",
                age_group="kindergarten",
                english_level="starter",
                persona="coach",
            )
        },
    )
    configured_repo.init_schema()

    profile = configured_repo.ensure_profile_for_device("esp32-luna")

    assert profile.user_id == original.user_id
    assert profile.name == "Luna"
    assert profile.age_group == "kindergarten"
    assert profile.english_level == "starter"


def test_repository_reset_device_memory_keeps_other_devices(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = BuddyRepository(db_path)
    repo.init_schema()
    profile_a = repo.ensure_profile_for_device("esp32-child-a")
    profile_b = repo.ensure_profile_for_device("esp32-child-b")
    episode_a = repo.add_episode(
        user_id=profile_a.user_id,
        session_id="session-a",
        user_text="I like cats",
        assistant_text="Cats are cute!",
        detected_language="en",
    )
    episode_b = repo.add_episode(
        user_id=profile_b.user_id,
        session_id="session-b",
        user_text="I like trains",
        assistant_text="Trains are fast!",
        detected_language="en",
    )
    repo.apply_memory_patch(
        user_id=profile_a.user_id,
        episode_id=episode_a.episode_id,
        patch=MemoryPatch(interests_add=["cats"]),
    )
    repo.apply_memory_patch(
        user_id=profile_b.user_id,
        episode_id=episode_b.episode_id,
        patch=MemoryPatch(interests_add=["trains"]),
    )

    reset_profile = repo.reset_device_memory("esp32-child-a")

    assert reset_profile.user_id == profile_a.user_id
    assert "cats" not in reset_profile.interests
    assert repo.recent_episodes(profile_a.user_id, limit=5) == []
    assert repo.memory_events(profile_a.user_id) == []
    assert repo.recent_episodes(profile_b.user_id, limit=5)[0].user_text == "I like trains"
    assert "trains" in repo.get_profile(profile_b.user_id).interests


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


def test_repository_resets_demo_user_data(tmp_path):
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
    repo.apply_memory_patch(
        user_id=profile.user_id,
        episode_id=episode.episode_id,
        patch=MemoryPatch(interests_add=["cats"], notes_add=["likes cats"]),
    )

    reset_profile = repo.reset_demo_user()

    assert reset_profile.user_id == "demo-mia"
    assert "cats" not in reset_profile.interests
    assert repo.recent_episodes("demo-mia", limit=5) == []
    assert repo.memory_events("demo-mia") == []
