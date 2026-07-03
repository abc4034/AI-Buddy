from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from buddy_brain.config import DeviceProfileConfig
from buddy_brain.models import Episode, MemoryPatch, Profile


DEFAULT_PROFILE = Profile(
    user_id="demo-mia",
    name="Mia",
    age_group="primary school",
    english_level="beginner",
    interests=["animals", "drawing", "games"],
    language_preference="English first, Chinese explanation when needed",
    learning_goals=["speak simple English sentences", "build confidence"],
    notes=[],
)


class BuddyRepository:
    def __init__(
        self,
        database_path: Path,
        demo_user_id: str = "demo-mia",
        demo_device_id: str = "esp32-fc012ccf1754",
        device_profiles: dict[str, DeviceProfileConfig] | None = None,
    ):
        self.database_path = Path(database_path)
        self.demo_user_id = demo_user_id
        self.demo_device_id = demo_device_id
        self.device_profiles = device_profiles or {}

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    client_id TEXT,
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS profile (
                    user_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    age_group TEXT NOT NULL,
                    english_level TEXT NOT NULL,
                    interests_json TEXT NOT NULL,
                    language_preference TEXT NOT NULL,
                    learning_goals_json TEXT NOT NULL,
                    notes_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    started_at INTEGER NOT NULL,
                    ended_at INTEGER,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    detected_language TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS memory_events (
                    event_id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    applied_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                """
            )

    def ensure_demo_user(self) -> Profile:
        return self.ensure_profile_for_device(
            self.demo_device_id,
            client_id=self.demo_device_id,
            user_id=self.demo_user_id,
        )

    def ensure_profile_for_device(
        self,
        device_id: str,
        client_id: str | None = None,
        user_id: str | None = None,
    ) -> Profile:
        clean_device_id = device_id.strip() or self.demo_device_id
        now = int(time.time())
        existing = self._device_row(clean_device_id)
        if existing is not None:
            next_client_id = client_id or existing["client_id"] or clean_device_id
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE devices
                    SET client_id = ?, last_seen_at = ?
                    WHERE device_id = ?
                    """,
                    (next_client_id, now, clean_device_id),
                )
            self._apply_configured_profile(clean_device_id, existing["user_id"], now)
            return self.get_profile(existing["user_id"])

        resolved_user_id = user_id or _user_id_for_device(clean_device_id)
        profile = self._default_profile_for_device(clean_device_id, resolved_user_id)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (user_id, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (profile.user_id, profile.name, now, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO profile (
                    user_id, name, age_group, english_level, interests_json,
                    language_preference, learning_goals_json, notes_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.user_id,
                    profile.name,
                    profile.age_group,
                    profile.english_level,
                    json.dumps(profile.interests, ensure_ascii=False),
                    profile.language_preference,
                    json.dumps(profile.learning_goals, ensure_ascii=False),
                    json.dumps(profile.notes, ensure_ascii=False),
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO devices (
                    device_id, client_id, user_id, created_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    client_id = excluded.client_id,
                    user_id = excluded.user_id,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    clean_device_id,
                    client_id or clean_device_id,
                    profile.user_id,
                    now,
                    now,
                ),
            )
        return self.get_profile(profile.user_id)

    def get_profile(self, user_id: str) -> Profile:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM profile WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(f"profile not found for user_id={user_id}")
        return Profile(
            user_id=row["user_id"],
            name=row["name"],
            age_group=row["age_group"],
            english_level=row["english_level"],
            interests=json.loads(row["interests_json"]),
            language_preference=row["language_preference"],
            learning_goals=json.loads(row["learning_goals_json"]),
            notes=json.loads(row["notes_json"]),
        )

    def add_episode(
        self,
        user_id: str,
        session_id: str,
        user_text: str,
        assistant_text: str,
        detected_language: str,
    ) -> Episode:
        episode = Episode(
            episode_id=f"episode-{uuid.uuid4().hex}",
            session_id=session_id,
            user_id=user_id,
            user_text=user_text,
            assistant_text=assistant_text,
            detected_language=detected_language,
            created_at=int(time.time()),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episodes (
                    episode_id, session_id, user_id, user_text,
                    assistant_text, detected_language, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.episode_id,
                    episode.session_id,
                    episode.user_id,
                    episode.user_text,
                    episode.assistant_text,
                    episode.detected_language,
                    episode.created_at,
                ),
            )
        return episode

    def recent_episodes(self, user_id: str, limit: int) -> list[Episode]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM episodes
                WHERE user_id = ?
                ORDER BY created_at DESC, episode_id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [
            Episode(
                episode_id=row["episode_id"],
                session_id=row["session_id"],
                user_id=row["user_id"],
                user_text=row["user_text"],
                assistant_text=row["assistant_text"],
                detected_language=row["detected_language"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def apply_memory_patch(self, user_id: str, episode_id: str, patch: MemoryPatch) -> Profile:
        current = self.get_profile(user_id)
        interests = _merge_unique(current.interests, patch.interests_add)
        goals = _merge_unique(current.learning_goals, patch.learning_goals_add)
        notes = _merge_unique(current.notes, patch.notes_add)
        english_level = patch.english_level or current.english_level
        now = int(time.time())
        payload = patch.model_dump()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE profile
                SET english_level = ?, interests_json = ?, learning_goals_json = ?,
                    notes_json = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (
                    english_level,
                    json.dumps(interests, ensure_ascii=False),
                    json.dumps(goals, ensure_ascii=False),
                    json.dumps(notes, ensure_ascii=False),
                    now,
                    user_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_events (
                    event_id, episode_id, user_id, event_type,
                    payload_json, created_at, applied_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"event-{uuid.uuid4().hex}",
                    episode_id,
                    user_id,
                    "profile_patch",
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_profile(user_id)

    def memory_events(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_events
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def reset_demo_user(self) -> Profile:
        return self.reset_device_memory(self.demo_device_id)

    def reset_device_memory(self, device_id: str) -> Profile:
        profile = self.ensure_profile_for_device(device_id)
        user_id = profile.user_id
        now = int(time.time())
        default_profile = self._default_profile_for_device(device_id, user_id)
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_events WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM episodes WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM profile WHERE user_id = ?", (user_id,))
            conn.execute(
                """
                INSERT OR IGNORE INTO users (user_id, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (default_profile.user_id, default_profile.name, now, now),
            )
            conn.execute(
                """
                UPDATE users
                SET display_name = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (default_profile.name, now, default_profile.user_id),
            )
            conn.execute(
                """
                INSERT INTO profile (
                    user_id, name, age_group, english_level, interests_json,
                    language_preference, learning_goals_json, notes_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    default_profile.user_id,
                    default_profile.name,
                    default_profile.age_group,
                    default_profile.english_level,
                    json.dumps(default_profile.interests, ensure_ascii=False),
                    default_profile.language_preference,
                    json.dumps(default_profile.learning_goals, ensure_ascii=False),
                    json.dumps(default_profile.notes, ensure_ascii=False),
                    now,
                ),
            )
        return self.get_profile(user_id)

    def get_device(self, device_id: str) -> dict[str, Any]:
        row = self._device_row(device_id)
        if row is None:
            raise KeyError(f"device not found for device_id={device_id}")
        return dict(row)

    def list_devices(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.device_id, d.client_id, d.user_id, d.created_at, d.last_seen_at,
                       p.name AS profile_name
                FROM devices d
                LEFT JOIN profile p ON p.user_id = d.user_id
                ORDER BY d.last_seen_at DESC, d.device_id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def device_persona(self, device_id: str) -> str | None:
        config = self.device_profiles.get(device_id)
        if config and config.persona:
            return config.persona
        return None

    def _device_row(self, device_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()

    def _default_profile_for_device(self, device_id: str, user_id: str) -> Profile:
        config = self.device_profiles.get(device_id)
        if config is None:
            return DEFAULT_PROFILE.model_copy(update={"user_id": user_id})
        return DEFAULT_PROFILE.model_copy(
            update={
                "user_id": user_id,
                "name": config.child_name,
                "age_group": config.age_group,
                "english_level": config.english_level,
            }
        )

    def _apply_configured_profile(self, device_id: str, user_id: str, timestamp: int) -> None:
        config = self.device_profiles.get(device_id)
        if config is None:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET display_name = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (config.child_name, timestamp, user_id),
            )
            conn.execute(
                """
                UPDATE profile
                SET name = ?, age_group = ?, english_level = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (config.child_name, config.age_group, config.english_level, timestamp, user_id),
            )


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    values = list(existing)
    seen = {value.casefold() for value in values}
    for value in incoming:
        clean = value.strip()
        if clean and clean.casefold() not in seen:
            values.append(clean)
            seen.add(clean.casefold())
    return values


def _user_id_for_device(device_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", device_id.casefold()).strip("-")
    return f"device-{slug or 'unknown'}"
