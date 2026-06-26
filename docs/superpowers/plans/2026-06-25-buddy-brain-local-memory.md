# Buddy Brain Local Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local `buddy-brain` service that exposes an OpenAI-compatible chat API, calls DeepSeek through a configurable OpenAI-compatible client, and persists long-term child learning memory in SQLite.

**Architecture:** This plan creates the service that sits between `xiaozhi-server` and model providers. It keeps model access behind a provider interface, keeps memory in a focused SQLite repository, and exposes a FastAPI `/v1/chat/completions` endpoint compatible with XiaoZhi service configuration. XiaoZhi server and ESP32 routing are intentionally separate from this first executable unit.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, Pydantic v2, pydantic-settings, OpenAI Python SDK, SQLite, pytest, httpx.

## Global Constraints

- First demo runs in a local network and does not require public cloud deployment.
- Hardware is ESP32-S3 XiaoZhi-compatible; current speaker output is not a first-version acceptance condition.
- Memory database path is `data/buddy_memory.db`.
- Default model provider uses `OPENAI_BASE_URL=https://api.deepseek.com`.
- Default model name is `deepseek-v4-flash`.
- `OPENAI_API_KEY` is read only from environment or `.env`; secrets are not written to code, docs, git, or test fixtures.
- Local model migration keeps the same interface by changing `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `MODEL_NAME`.
- Buddy answers Chinese, English, and mixed input; it prefers simple English with short Chinese explanation when helpful.
- Buddy keeps replies short, asks at most one follow-up question, and corrects at most one clear English mistake per turn.
- XiaoZhi server memory is disabled for this demo; Buddy Brain is the only long-term memory owner.

---

## Scope Check

The approved design covers three independent work areas: Buddy Brain service, XiaoZhi server integration, and ESP32 OTA/WebSocket routing. This plan implements only Buddy Brain because it can be tested without hardware and becomes the stable LLM endpoint used by the other two areas.

After this plan passes, create a second plan for XiaoZhi server configuration and a third plan for device routing or firmware rebuild only if runtime OTA configuration fails.

## File Structure

- Create `pyproject.toml`: package metadata, runtime dependencies, dev dependencies, pytest config.
- Create `.gitignore`: excludes `.env`, virtual environments, SQLite runtime data, Python caches.
- Create `.env.example`: documents safe environment variable names without secrets.
- Create `buddy_brain/__init__.py`: package marker and version string.
- Create `buddy_brain/config.py`: environment-backed settings and default demo values.
- Create `buddy_brain/models.py`: OpenAI-compatible request/response models and memory profile types.
- Create `buddy_brain/repository.py`: SQLite schema, demo user bootstrap, conversation persistence, memory merge.
- Create `buddy_brain/prompting.py`: language detection and chat prompt construction.
- Create `buddy_brain/llm.py`: OpenAI-compatible model provider with injectable client for tests.
- Create `buddy_brain/memory.py`: LLM-based memory extraction and deterministic profile merge.
- Create `buddy_brain/app.py`: FastAPI app factory, `/health`, `/v1/chat/completions`, streaming response support.
- Create `tests/conftest.py`: isolated test settings, fake LLM provider, temporary database helpers.
- Create `tests/test_config.py`: verifies default settings and safe env behavior.
- Create `tests/test_repository.py`: verifies SQLite schema, profile persistence, episodes, memory events.
- Create `tests/test_prompting.py`: verifies bilingual prompt rules and recent-history injection.
- Create `tests/test_llm.py`: verifies provider calls OpenAI-compatible client without network.
- Create `tests/test_memory.py`: verifies memory extraction JSON parsing and merge behavior.
- Create `tests/test_app.py`: verifies health, non-stream chat, stream chat, database writes.
- Create `scripts/smoke_chat.ps1`: local manual smoke test using `curl.exe`.
- Create `README.md`: setup, run, test, and XiaoZhi integration handoff notes.

---

### Task 1: Python Service Scaffold And Settings

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `buddy_brain/__init__.py`
- Create: `buddy_brain/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: none
- Produces:
  - `buddy_brain.config.Settings`
  - `buddy_brain.config.get_settings() -> Settings`

- [ ] **Step 1: Write the failing settings tests**

Create `tests/test_config.py`:

```python
from pathlib import Path

from buddy_brain.config import Settings


def test_default_settings_are_safe_for_local_demo():
    settings = Settings()

    assert settings.openai_base_url == "https://api.deepseek.com"
    assert settings.model_name == "deepseek-v4-flash"
    assert settings.database_path == Path("data/buddy_memory.db")
    assert settings.openai_api_key == ""
    assert settings.demo_user_id == "demo-mia"
    assert settings.recent_episode_limit == 8


def test_settings_accept_local_model_override(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "not-needed")
    monkeypatch.setenv("MODEL_NAME", "local-qwen")

    settings = Settings()

    assert settings.openai_base_url == "http://127.0.0.1:8001/v1"
    assert settings.openai_api_key == "not-needed"
    assert settings.model_name == "local-qwen"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'buddy_brain'`.

- [ ] **Step 3: Add package scaffold and dependency metadata**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "ai-buddy-brain"
version = "0.1.0"
description = "Local Buddy Brain service for XiaoZhi-compatible English companion education demo"
requires-python = ">=3.10"
dependencies = [
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "pydantic>=2.7,<3",
  "pydantic-settings>=2.3,<3",
  "openai>=1.40,<2",
]

[project.optional-dependencies]
dev = [
  "pytest>=8,<9",
  "pytest-asyncio>=0.23,<1",
  "httpx>=0.27,<1",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

Create `.gitignore`:

```gitignore
.env
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
data/
```

Create `.env.example`:

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=
MODEL_NAME=deepseek-v4-flash
DATABASE_PATH=data/buddy_memory.db
```

Create `buddy_brain/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `buddy_brain/config.py`:

```python
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Buddy Brain"
    host: str = "0.0.0.0"
    port: int = 8010
    database_path: Path = Path("data/buddy_memory.db")
    openai_base_url: str = "https://api.deepseek.com"
    openai_api_key: str = Field(default="", repr=False)
    model_name: str = "deepseek-v4-flash"
    memory_model_name: str | None = None
    demo_user_id: str = "demo-mia"
    demo_device_id: str = "esp32-fc012ccf1754"
    recent_episode_limit: int = 8
    request_timeout_seconds: float = 60.0

    @property
    def effective_memory_model(self) -> str:
        return self.memory_model_name or self.model_name


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Install package and run tests**

Run:

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

Run:

```powershell
git add pyproject.toml .gitignore .env.example buddy_brain/__init__.py buddy_brain/config.py tests/test_config.py
git commit -m "feat: scaffold buddy brain service"
```

---

### Task 2: SQLite Repository And Demo User

**Files:**
- Create: `buddy_brain/models.py`
- Create: `buddy_brain/repository.py`
- Create: `tests/test_repository.py`

**Interfaces:**
- Consumes:
  - `Settings.database_path`
  - `Settings.demo_user_id`
  - `Settings.demo_device_id`
- Produces:
  - `buddy_brain.models.Profile`
  - `buddy_brain.models.Episode`
  - `buddy_brain.models.MemoryPatch`
  - `buddy_brain.repository.BuddyRepository`
  - `BuddyRepository.init_schema() -> None`
  - `BuddyRepository.ensure_demo_user() -> Profile`
  - `BuddyRepository.add_episode(user_id: str, session_id: str, user_text: str, assistant_text: str, detected_language: str) -> Episode`
  - `BuddyRepository.recent_episodes(user_id: str, limit: int) -> list[Episode]`
  - `BuddyRepository.apply_memory_patch(user_id: str, episode_id: str, patch: MemoryPatch) -> Profile`

- [ ] **Step 1: Write failing repository tests**

Create `tests/test_repository.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_repository.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'buddy_brain.models'`.

- [ ] **Step 3: Add data models and SQLite repository**

Create `buddy_brain/models.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class OpenAIMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[OpenAIMessage]
    stream: bool = False
    user: str | None = None
    temperature: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Profile(BaseModel):
    user_id: str
    name: str
    age_group: str
    english_level: str
    interests: list[str]
    language_preference: str
    learning_goals: list[str]
    notes: list[str] = Field(default_factory=list)


class Episode(BaseModel):
    episode_id: str
    session_id: str
    user_id: str
    user_text: str
    assistant_text: str
    detected_language: str
    created_at: int


class MemoryPatch(BaseModel):
    interests_add: list[str] = Field(default_factory=list)
    learning_goals_add: list[str] = Field(default_factory=list)
    notes_add: list[str] = Field(default_factory=list)
    english_level: str | None = None
```

Create `buddy_brain/repository.py`:

```python
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

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
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

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
        now = int(time.time())
        profile = DEFAULT_PROFILE
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


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    values = list(existing)
    seen = {value.casefold() for value in values}
    for value in incoming:
        clean = value.strip()
        if clean and clean.casefold() not in seen:
            values.append(clean)
            seen.add(clean.casefold())
    return values
```

- [ ] **Step 4: Run repository tests**

Run:

```powershell
python -m pytest tests/test_repository.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

Run:

```powershell
git add buddy_brain/models.py buddy_brain/repository.py tests/test_repository.py
git commit -m "feat: add buddy memory repository"
```

---

### Task 3: Prompt Builder And Language Detection

**Files:**
- Create: `buddy_brain/prompting.py`
- Create: `tests/test_prompting.py`

**Interfaces:**
- Consumes:
  - `Profile`
  - `Episode`
- Produces:
  - `detect_language(text: str) -> str`
  - `build_chat_messages(profile: Profile, history: list[Episode], user_text: str) -> list[dict[str, str]]`

- [ ] **Step 1: Write failing prompt tests**

Create `tests/test_prompting.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_prompting.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'buddy_brain.prompting'`.

- [ ] **Step 3: Add prompt builder**

Create `buddy_brain/prompting.py`:

```python
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
```

- [ ] **Step 4: Run prompt tests**

Run:

```powershell
python -m pytest tests/test_prompting.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

Run:

```powershell
git add buddy_brain/prompting.py tests/test_prompting.py
git commit -m "feat: build buddy bilingual prompts"
```

---

### Task 4: OpenAI-Compatible LLM Provider

**Files:**
- Create: `buddy_brain/llm.py`
- Create: `tests/test_llm.py`

**Interfaces:**
- Consumes:
  - `Settings.openai_base_url`
  - `Settings.openai_api_key`
  - `Settings.model_name`
  - prompt messages from `build_chat_messages`
- Produces:
  - `class LLMProvider`
  - `class OpenAICompatibleProvider`
  - `OpenAICompatibleProvider.complete(messages: list[dict[str, str]], model: str | None = None, temperature: float | None = None) -> str`
  - `OpenAICompatibleProvider.stream(messages: list[dict[str, str]], model: str | None = None, temperature: float | None = None) -> AsyncIterator[str]`

- [ ] **Step 1: Write failing provider tests**

Create `tests/test_llm.py`:

```python
from types import SimpleNamespace

import pytest

from buddy_brain.config import Settings
from buddy_brain.llm import OpenAICompatibleProvider


class FakeCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            async def chunks():
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hi"))])
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=" there"))])
            return chunks()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hi there"))]
        )


class FakeClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.mark.asyncio
async def test_provider_sends_openai_compatible_chat_request():
    client = FakeClient()
    settings = Settings(openai_api_key="test-key")
    provider = OpenAICompatibleProvider(settings=settings, client=client)

    result = await provider.complete(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.2,
    )

    assert result == "Hi there"
    assert client.completions.calls[0]["model"] == "deepseek-v4-flash"
    assert client.completions.calls[0]["messages"] == [{"role": "user", "content": "hello"}]
    assert client.completions.calls[0]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_provider_stream_yields_text_deltas():
    client = FakeClient()
    settings = Settings(openai_api_key="test-key")
    provider = OpenAICompatibleProvider(settings=settings, client=client)

    chunks = [
        chunk
        async for chunk in provider.stream(messages=[{"role": "user", "content": "hello"}])
    ]

    assert chunks == ["Hi", " there"]
    assert client.completions.calls[0]["stream"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_llm.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'buddy_brain.llm'`.

- [ ] **Step 3: Add LLM provider**

Create `buddy_brain/llm.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from openai import AsyncOpenAI

from buddy_brain.config import Settings


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        ...

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        ...


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        self.settings = settings
        self.client = client or AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.request_timeout_seconds,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=model or self.settings.model_name,
            messages=messages,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        return content or ""

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=model or self.settings.model_name,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
```

- [ ] **Step 4: Run provider tests**

Run:

```powershell
python -m pytest tests/test_llm.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

Run:

```powershell
git add buddy_brain/llm.py tests/test_llm.py
git commit -m "feat: add openai compatible llm provider"
```

---

### Task 5: Memory Extraction And Merge Service

**Files:**
- Create: `buddy_brain/memory.py`
- Create: `tests/test_memory.py`

**Interfaces:**
- Consumes:
  - `LLMProvider.complete(...)`
  - `BuddyRepository.apply_memory_patch(...)`
  - `Settings.effective_memory_model`
- Produces:
  - `parse_memory_patch(raw_text: str) -> MemoryPatch`
  - `class MemoryService`
  - `MemoryService.update_from_episode(user_id: str, episode_id: str, user_text: str, assistant_text: str) -> Profile`

- [ ] **Step 1: Write failing memory tests**

Create `tests/test_memory.py`:

```python
import pytest

from buddy_brain.config import Settings
from buddy_brain.memory import MemoryService, parse_memory_patch
from buddy_brain.repository import BuddyRepository


class FakeMemoryLLM:
    async def complete(self, messages, model=None, temperature=None):
        return '{"interests_add":["space"],"learning_goals_add":[],"notes_add":["likes planets"],"english_level":null}'


def test_parse_memory_patch_accepts_json_inside_markdown_fence():
    patch = parse_memory_patch(
        '```json\n{"interests_add":["cats"],"notes_add":["likes cats"]}\n```'
    )

    assert patch.interests_add == ["cats"]
    assert patch.notes_add == ["likes cats"]


def test_parse_memory_patch_returns_empty_patch_for_non_json():
    patch = parse_memory_patch("no durable memory")

    assert patch.interests_add == []
    assert patch.notes_add == []


@pytest.mark.asyncio
async def test_memory_service_updates_repository_profile(tmp_path):
    repo = BuddyRepository(tmp_path / "memory.db")
    repo.init_schema()
    profile = repo.ensure_demo_user()
    episode = repo.add_episode(
        user_id=profile.user_id,
        session_id="session-1",
        user_text="I like planets.",
        assistant_text="Planets are in space.",
        detected_language="en",
    )
    service = MemoryService(
        settings=Settings(database_path=tmp_path / "memory.db"),
        repository=repo,
        provider=FakeMemoryLLM(),
    )

    updated = await service.update_from_episode(
        user_id=profile.user_id,
        episode_id=episode.episode_id,
        user_text=episode.user_text,
        assistant_text=episode.assistant_text,
    )

    assert "space" in updated.interests
    assert "likes planets" in updated.notes
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_memory.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'buddy_brain.memory'`.

- [ ] **Step 3: Add memory extraction service**

Create `buddy_brain/memory.py`:

```python
from __future__ import annotations

import json

from buddy_brain.config import Settings
from buddy_brain.llm import LLMProvider
from buddy_brain.models import MemoryPatch, Profile
from buddy_brain.repository import BuddyRepository


def parse_memory_patch(raw_text: str) -> MemoryPatch:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(line for line in lines[1:] if line.strip() != "```").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return MemoryPatch()
    return MemoryPatch(**payload)


class MemoryService:
    def __init__(
        self,
        settings: Settings,
        repository: BuddyRepository,
        provider: LLMProvider,
    ):
        self.settings = settings
        self.repository = repository
        self.provider = provider

    async def update_from_episode(
        self,
        user_id: str,
        episode_id: str,
        user_text: str,
        assistant_text: str,
    ) -> Profile:
        profile = self.repository.get_profile(user_id)
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract only stable, child-safe learning memory from the conversation. "
                    "Return compact JSON with keys interests_add, learning_goals_add, notes_add, english_level. "
                    "Use empty arrays and null when there is no durable update."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Existing profile:\n{profile.model_dump_json()}\n\n"
                    f"Child said: {user_text}\n"
                    f"Buddy answered: {assistant_text}"
                ),
            },
        ]
        raw = await self.provider.complete(
            messages=messages,
            model=self.settings.effective_memory_model,
            temperature=0,
        )
        patch = parse_memory_patch(raw)
        return self.repository.apply_memory_patch(user_id, episode_id, patch)
```

- [ ] **Step 4: Run memory tests**

Run:

```powershell
python -m pytest tests/test_memory.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

Run:

```powershell
git add buddy_brain/memory.py tests/test_memory.py
git commit -m "feat: extract and merge buddy memory"
```

---

### Task 6: FastAPI OpenAI-Compatible Chat Endpoint

**Files:**
- Create: `buddy_brain/app.py`
- Create: `tests/conftest.py`
- Create: `tests/test_app.py`

**Interfaces:**
- Consumes:
  - `Settings`
  - `BuddyRepository`
  - `OpenAICompatibleProvider`
  - `MemoryService`
  - `build_chat_messages(...)`
  - `detect_language(...)`
- Produces:
  - `create_app(settings: Settings | None = None, repository: BuddyRepository | None = None, provider: LLMProvider | None = None) -> FastAPI`
  - module-level `app`
  - `GET /health`
  - `POST /v1/chat/completions`

- [ ] **Step 1: Write failing API tests**

Create `tests/conftest.py`:

```python
from collections.abc import AsyncIterator

import pytest

from buddy_brain.config import Settings
from buddy_brain.repository import BuddyRepository


class FakeChatProvider:
    async def complete(self, messages, model=None, temperature=None):
        if messages[0]["content"].startswith("Extract only stable"):
            return '{"interests_add":["dinosaurs"],"learning_goals_add":[],"notes_add":["likes dinosaurs"],"english_level":null}'
        return "Sure! Dinosaurs are big animals. 恐龙是很大的动物。"

    async def stream(self, messages, model=None, temperature=None) -> AsyncIterator[str]:
        for chunk in ["Sure! ", "Dinosaurs ", "are big."]:
            yield chunk


@pytest.fixture
def test_settings(tmp_path):
    return Settings(
        database_path=tmp_path / "buddy_memory.db",
        openai_api_key="test-key",
    )


@pytest.fixture
def test_repository(test_settings):
    repo = BuddyRepository(test_settings.database_path)
    repo.init_schema()
    repo.ensure_demo_user()
    return repo
```

Create `tests/test_app.py`:

```python
from fastapi.testclient import TestClient

from buddy_brain.app import create_app
from buddy_brain.repository import BuddyRepository
from tests.conftest import FakeChatProvider


def test_health_endpoint(test_settings, test_repository):
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["model"] == "deepseek-v4-flash"


def test_chat_completion_writes_episode_and_memory(test_settings, test_repository):
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "我喜欢恐龙，dinosaur 怎么说？"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"].startswith("Sure!")

    repo = BuddyRepository(test_settings.database_path)
    profile = repo.get_profile("demo-mia")
    episodes = repo.recent_episodes("demo-mia", limit=5)
    assert episodes[0].user_text == "我喜欢恐龙，dinosaur 怎么说？"
    assert "dinosaurs" in profile.interests


def test_chat_completion_stream_returns_sse_and_writes_episode(test_settings, test_repository):
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Tell me about dinosaurs"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "data:" in body
    assert "[DONE]" in body
    episodes = test_repository.recent_episodes("demo-mia", limit=5)
    assert episodes[0].assistant_text == "Sure! Dinosaurs are big."
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_app.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'buddy_brain.app'`.

- [ ] **Step 3: Add FastAPI app**

Create `buddy_brain/app.py`:

```python
from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from buddy_brain.config import Settings, get_settings
from buddy_brain.llm import LLMProvider, OpenAICompatibleProvider
from buddy_brain.memory import MemoryService
from buddy_brain.models import ChatCompletionRequest
from buddy_brain.prompting import build_chat_messages, detect_language
from buddy_brain.repository import BuddyRepository


def create_app(
    settings: Settings | None = None,
    repository: BuddyRepository | None = None,
    provider: LLMProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    repository = repository or BuddyRepository(settings.database_path)
    provider = provider or OpenAICompatibleProvider(settings)
    memory_service = MemoryService(settings=settings, repository=repository, provider=provider)

    api = FastAPI(title=settings.app_name)

    @api.on_event("startup")
    async def startup() -> None:
        repository.init_schema()
        repository.ensure_demo_user()

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "model": settings.model_name,
            "database": str(settings.database_path),
        }

    @api.post("/v1/chat/completions")
    async def chat_completions(
        request: ChatCompletionRequest,
        background_tasks: BackgroundTasks,
    ):
        user_text = _latest_user_text(request)
        profile = repository.ensure_demo_user()
        history = repository.recent_episodes(profile.user_id, settings.recent_episode_limit)
        detected_language = detect_language(user_text)
        messages = build_chat_messages(profile, history, user_text)
        model = request.model or settings.model_name
        session_id = request.metadata.get("session_id") or f"session-{uuid.uuid4().hex}"

        if request.stream:
            return StreamingResponse(
                _stream_response(
                    provider=provider,
                    memory_service=memory_service,
                    repository=repository,
                    user_id=profile.user_id,
                    session_id=session_id,
                    user_text=user_text,
                    detected_language=detected_language,
                    messages=messages,
                    model=model,
                    temperature=request.temperature,
                ),
                media_type="text/event-stream",
            )

        assistant_text = await provider.complete(
            messages=messages,
            model=model,
            temperature=request.temperature,
        )
        episode = repository.add_episode(
            user_id=profile.user_id,
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text,
            detected_language=detected_language,
        )
        background_tasks.add_task(
            memory_service.update_from_episode,
            profile.user_id,
            episode.episode_id,
            user_text,
            assistant_text,
        )
        return _chat_completion_payload(model=model, assistant_text=assistant_text)

    return api


def _latest_user_text(request: ChatCompletionRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    raise HTTPException(status_code=400, detail="messages must include a non-empty user message")


def _chat_completion_payload(model: str, assistant_text: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": assistant_text},
                "finish_reason": "stop",
            }
        ],
    }


async def _stream_response(
    provider: LLMProvider,
    memory_service: MemoryService,
    repository: BuddyRepository,
    user_id: str,
    session_id: str,
    user_text: str,
    detected_language: str,
    messages: list[dict[str, str]],
    model: str,
    temperature: float | None,
) -> AsyncIterator[str]:
    chunks: list[str] = []
    async for delta in provider.stream(messages=messages, model=model, temperature=temperature):
        chunks.append(delta)
        payload = {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    assistant_text = "".join(chunks)
    episode = repository.add_episode(
        user_id=user_id,
        session_id=session_id,
        user_text=user_text,
        assistant_text=assistant_text,
        detected_language=detected_language,
    )
    await memory_service.update_from_episode(user_id, episode.episode_id, user_text, assistant_text)
    yield "data: [DONE]\n\n"


app = create_app()
```

- [ ] **Step 4: Run API tests**

Run:

```powershell
python -m pytest tests/test_app.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

Run:

```powershell
git add buddy_brain/app.py tests/conftest.py tests/test_app.py
git commit -m "feat: expose buddy brain chat api"
```

---

### Task 7: Smoke Script And Operator Documentation

**Files:**
- Create: `scripts/smoke_chat.ps1`
- Create: `README.md`

**Interfaces:**
- Consumes:
  - `uvicorn buddy_brain.app:app`
  - `POST /v1/chat/completions`
- Produces:
  - repeatable local smoke test
  - setup notes for Windows host and Ubuntu VM
  - XiaoZhi server handoff values

- [ ] **Step 1: Write smoke script**

Create `scripts/smoke_chat.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$body = @{
  model = "deepseek-v4-flash"
  stream = $false
  messages = @(
    @{
      role = "user"
      content = "你好 Buddy, I like dinosaurs. Can you teach me one English sentence?"
    }
  )
} | ConvertTo-Json -Depth 5

curl.exe -s `
  -H "Content-Type: application/json" `
  -d $body `
  http://127.0.0.1:8010/v1/chat/completions
```

- [ ] **Step 2: Write README**

Create `README.md`:

````markdown
# AI Buddy

Local Buddy Brain service for an ESP32-S3 XiaoZhi-compatible English companion education demo.

## First Demo Scope

- Runs locally on Windows or Ubuntu 22.
- Exposes an OpenAI-compatible `/v1/chat/completions` endpoint.
- Uses DeepSeek through an OpenAI-compatible client by default.
- Stores long-term child learning memory in `data/buddy_memory.db`.
- Keeps local model deployment available by changing environment variables.
- Does not require speaker output on the current hardware.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY` from your local environment. Do not commit `.env`.

## Run

```powershell
uvicorn buddy_brain.app:app --host 0.0.0.0 --port 8010
```

## Test

```powershell
python -m pytest -v
```

## Smoke Test

Start the server, then run:

```powershell
.\scripts\smoke_chat.ps1
```

Expected response contains a `choices[0].message.content` value from Buddy.

## Local Model Switch

Use the same API surface and change environment values:

```dotenv
OPENAI_BASE_URL=http://127.0.0.1:8001/v1
OPENAI_API_KEY=
MODEL_NAME=local-model-name
```

## XiaoZhi Server Handoff

Point the XiaoZhi server LLM provider at:

```text
base_url: http://<host-lan-ip>:8010/v1
api_key: not-needed-by-buddy-brain
model: deepseek-v4-flash
```

Keep XiaoZhi server memory disabled for this demo. Buddy Brain owns profile and memory persistence.
````

- [ ] **Step 3: Run full test suite**

Run:

```powershell
python -m pytest -v
```

Expected: 15 passed.

- [ ] **Step 4: Run local smoke test with server**

In terminal A:

```powershell
$env:OPENAI_API_KEY = "<set in local shell only>"
uvicorn buddy_brain.app:app --host 0.0.0.0 --port 8010
```

In terminal B:

```powershell
.\scripts\smoke_chat.ps1
```

Expected: JSON response with `object` equal to `chat.completion` and a short bilingual Buddy answer in `choices[0].message.content`.

- [ ] **Step 5: Commit**

Run:

```powershell
git add scripts/smoke_chat.ps1 README.md
git commit -m "docs: add buddy brain runbook"
```

---

## Final Verification

- [ ] Run:

```powershell
python -m pytest -v
```

Expected: 15 passed.

- [ ] Run:

```powershell
git status --short --branch
```

Expected: clean working tree on the implementation branch.

- [ ] Start the service:

```powershell
uvicorn buddy_brain.app:app --host 0.0.0.0 --port 8010
```

Expected: Uvicorn reports it is running on `http://0.0.0.0:8010`.

- [ ] In a second terminal, run:

```powershell
.\scripts\smoke_chat.ps1
```

Expected: response JSON contains a Buddy answer and `data/buddy_memory.db` exists.

## Handoff After This Plan

When this service passes local tests and smoke test, create the next plan for XiaoZhi server integration:

- clone or install the selected `xiaozhi-server`
- configure its OpenAI-compatible LLM provider to `http://<host-lan-ip>:8010/v1`
- keep XiaoZhi memory disabled
- choose the simplest ASR and TTS settings that already work on the current machine
- verify XiaoZhi server logs show Buddy Brain responses before changing ESP32 OTA routing
