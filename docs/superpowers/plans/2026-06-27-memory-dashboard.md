# Memory Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local Buddy Brain memory dashboard and make first-demo preference extraction more reliable.

**Architecture:** Reuse `BuddyRepository` as the only database boundary. Add plain FastAPI HTML routes in `buddy_brain.app`, repository helpers for dashboard/reset data, and a deterministic supplement in `buddy_brain.memory`.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, pytest, standard library `html` and `json`.

## Global Constraints

- No new runtime dependency.
- Dashboard is local demo tooling and uses the existing Buddy Brain server on port 8010.
- Buddy Brain remains the only long-term memory owner.

---

### Task 1: Dashboard And Reset Tests

**Files:**
- Modify: `tests/test_app.py`
- Modify: `tests/test_repository.py`

**Interfaces:**
- Produces expectations for `GET /memory`, `POST /memory/reset`, and `BuddyRepository.reset_demo_user()`.

- [x] Add failing tests for dashboard rendering and reset behavior.
- [x] Run targeted tests and confirm they fail because the routes/repository method do not exist.

### Task 2: Memory Extraction Fallback Tests

**Files:**
- Modify: `tests/test_memory.py`

**Interfaces:**
- Produces expectations for `MemoryService.update_from_episode()` to merge deterministic stable preferences with the LLM patch.

- [x] Add failing test for `{"content":"我喜欢读书。"}` when the LLM returns an empty patch.
- [x] Run targeted test and confirm it fails because fallback extraction does not exist.

### Task 3: Implement Repository, Dashboard, And Fallback

**Files:**
- Modify: `buddy_brain/repository.py`
- Modify: `buddy_brain/app.py`
- Modify: `buddy_brain/memory.py`

**Interfaces:**
- `BuddyRepository.reset_demo_user() -> Profile`
- `GET /memory`
- `POST /memory/reset`

- [x] Add repository reset helper.
- [x] Render local memory HTML using escaped database content.
- [x] Supplement LLM memory patches with deterministic preference extraction.
- [x] Run syntax and direct behavior verification.

Note: `xiaozhi-env` does not currently include `pytest`, so full pytest execution is pending environment setup. The implementation was verified with `py_compile`, a direct memory fallback script, a direct reset script, and a FastAPI `TestClient` dashboard script.
