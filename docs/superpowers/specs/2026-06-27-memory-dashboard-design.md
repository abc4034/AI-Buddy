# Memory Dashboard Design

**Goal:** Add a local-only memory dashboard for Buddy Brain and improve first-demo memory extraction for obvious stable learning preferences.

**Scope:** This change only touches the Buddy Brain service. It does not modify XiaoZhi firmware, XiaoZhi Server, ASR, TTS, or hardware wiring.

**Dashboard:** `GET /memory` returns a simple HTML page with the demo user's profile, recent episodes, and recent memory events from `data/buddy_memory.db`. `POST /memory/reset` clears demo conversation and memory data, then recreates the default demo profile. The page is intentionally plain HTML with no frontend framework or new runtime dependency.

**Memory Extraction:** The existing LLM-based memory extractor remains the primary extractor. A deterministic fallback supplements it for obvious stable preferences such as liking reading/books or dinosaurs, including XiaoZhi payloads where the user text is a JSON string containing `content`.

**Verification:** Tests cover dashboard rendering, reset behavior, and deterministic extraction of reading preference when the LLM returns an empty patch.
