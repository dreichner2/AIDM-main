# Backend Improvement Suggestions

Review date: 2026-06-03

This pass intentionally avoided large rewrites. The items below are the changes I would consider next if we decide to spend real engineering time on the backend.

## Highest-value rework candidates

1. Split `aidm_server/emergent_memory.py` into smaller modules.
   - Current size: roughly 1,500 lines.
   - Suggested boundaries: extraction prompts, heuristic extraction, patch validation, patch application, inventory helpers, and retrieval/context building.
   - Why: it owns too many responsibilities, making post-turn bugs hard to isolate and test. The current file mixes LLM calls, string heuristics, DB writes, ranking, and inventory mutation.

2. Move canon extraction off the critical gameplay response path.
   - Current behavior: after narration, `extract_canon_patch(...)` can make a second provider call before the turn fully persists.
   - Suggested direction: persist the DM response first, mark canon extraction as pending, and process extraction in a background worker or bounded follow-up step.
   - Why: the user-facing failure mode is bad: the DM can answer, then the save/canon step can stall or fail. This has been one of the most important runtime risks in local gameplay.

3. Refactor provider fallback logic in `aidm_server/llm.py`.
   - Current size: roughly 1,000 lines.
   - Suggested direction: share model normalization, fallback iteration, telemetry, and OpenAI-compatible chat behavior between NVIDIA/Kimi and DeepSeek. Keep Gemini separate only where the SDK behavior differs.
   - Why: the provider classes currently duplicate the same candidate model and fallback pattern, which makes future provider tuning riskier.

4. Centralize LLM provider catalog/defaults.
   - Current behavior: provider IDs, labels, default models, base URLs, and supported models are spread across `config.py`, `llm.py`, and `blueprints/system.py`.
   - Suggested direction: a single provider registry that powers config validation, runtime provider creation, and `/api/llm/config`.
   - Why: this reduces drift between UI-visible model choices and backend runtime behavior.

5. Split `aidm_server/turn_engine.py` by phase.
   - Current size: roughly 800 lines.
   - Suggested boundaries: turn validation, roll resolution, narration streaming, segment evaluation, persistence, and post-turn canon/projection.
   - Why: the transaction and socket-emission order is subtle. Smaller phase objects would make it easier to test failures at each boundary.

6. Put hard budgets and telemetry around context assembly.
   - Current behavior: `build_emergent_context(...)` loads and ranks all entities, facts, and threads in Python before slicing.
   - Suggested direction: add count/latency metrics, cap candidate pools, and eventually push more filtering into SQL or a small retrieval index.
   - Why: this is fine for small saves, but will get expensive as campaigns accumulate canon.

## Smaller follow-ups

- Add one common `require_json_body(request)` helper and use it across all write endpoints.
- Add tests for malformed provider canon JSON at the Socket.IO turn level, not only at the patch-validation unit level.
- Gate persistent provider changes from `/api/llm/config` carefully in production. Writing `.env.local` from an API route is convenient locally, but should remain clearly local/admin-only.
- Keep generated files out of release archives. This checkout contains ignored runtime artifacts such as `__pycache__`, logs, and local DB backups; they are ignored by `.gitignore`, but archives should be pruned before sharing.
