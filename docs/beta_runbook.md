# AI-DM Beta Runbook

## Startup
1. Set environment variables (`AIDM_ENV`, `AIDM_DATABASE_URI`, `AIDM_AUTH_REQUIRED`, `AIDM_API_AUTH_TOKENS`, and the selected provider key such as `GOOGLE_GENAI_API_KEY`, `AIDM_DEEPSEEK_API_KEY`, or `AIDM_NVIDIA_API_KEY`).
2. For production-like socket runtime, keep `AIDM_SOCKETIO_ASYNC_MODE=threading` unless you intentionally switch modes.
3. Install dependencies: `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt` for local development, or use `requirements.runtime.txt` for a minimal runtime without pytest/admin/migration UI tooling. Both paths apply `requirements.constraints.txt` for repeatable direct dependency versions.
4. Apply migrations: `flask db upgrade` (or run bootstrap command below).
5. Bootstrap check/start command:
   - Check only: `.venv/bin/python scripts/deploy_bootstrap.py --check-only`
   - Start after checks: `.venv/bin/python scripts/deploy_bootstrap.py`
6. Verify health: `GET /api/health`.
7. For the canonical local UI, start `aidm_frontend` with `VITE_AIDM_API_BASE_URL` pointed at the backend.

## Optional TTS
1. Set `AIDM_DEEPGRAM_API_KEY`.
2. Optionally set `AIDM_DEEPGRAM_TTS_MODEL` (default: `aura-2-draco-en`).
3. Tune `AIDM_DEEPGRAM_TTS_CONNECT_TIMEOUT_SECONDS` and `AIDM_DEEPGRAM_TTS_READ_TIMEOUT_SECONDS` only when provider/network timing needs local adjustment.
4. Confirm `GET /api/tts/config` returns `configured: true` and reports the expected model plus connect/read timeouts.
5. Toggle TTS in the React frontend. DM responses should be queued for speech; playback or provider failures should surface as visible frontend errors.
6. For direct checks, prefer `POST /api/tts/stream`; `/api/tts/speak` remains a compatible alias. Inspect `X-AIDM-TTS-Chunk-Count` and `X-AIDM-TTS-First-Chunk-Chars` on long responses.

## Operational Checks
1. Confirm `/api/health` returns `status: ok`.
2. Confirm `/api/metrics` exposes counters/timings.
3. Confirm session creation and state retrieval (`/api/sessions/<id>/state`).
4. Confirm socket `send_message` emits `dm_response_start`, `dm_chunk`, `dm_response_end`.
5. Confirm `turn_id` appears in logs (`/api/sessions/<id>/log`).
6. Confirm improvised entities/threads are being written to `story_entities` / `story_threads` for active sessions.

## Turn Lifecycle
1. The socket receives `send_message` and records the player action in `dm_turns` plus the `turn_events` event spine.
2. Narration streams through `dm_response_start`, one or more `dm_chunk` events, and `dm_response_end`.
3. After visible narration finishes, post-turn work persists `dm_output`, records the `dm_response` event, extracts/validates canon, applies canon tables, refreshes `SessionState`, and emits `session_log_update`.
4. Watch `turn_status` events for `received`, `narrating`, `response_complete`, `saving`, `saved`, `canon_pending`, `canon_applied`, and `failed`. A canon failure should not erase a saved visible DM response.
5. Treat `turn_events` as the audit trail. `dm_turns`, `session_log_entries`, `PlayerAction`, and `SessionState` are projections or convenience tables that should agree with the event spine.
6. If a future change rewrites projection logic, verify both the event rows and the projected session log/state before assuming the UI is wrong.

The per-session turn coordinator defaults to an in-memory store for local single-process play. For multi-worker deployments, set `AIDM_TURN_COORDINATOR_STORE=database` so workers share `session_turn_locks`; tune `AIDM_TURN_COORDINATOR_LOCK_TTL_SECONDS` high enough for the longest expected provider turn, and keep `AIDM_TURN_COORDINATOR_POLL_INTERVAL_MS` low enough that queued players are not left waiting after a lock releases.

## Provider Switching
1. Changing provider/model mid-session can alter tone, continuity, latency, and rules behavior.
2. Prefer switching between sessions or immediately after a session recap when possible.
3. For beta debugging, record provider/model changes in notes or a system log so later turn quality can be tied back to runtime changes.
4. Persistent provider changes through `/api/llm/config` are local/test only; production-like environments should use environment variables and restart/redeploy.
5. OpenAI-compatible providers reuse HTTP sessions and support phase timeout tuning through `AIDM_DEEPSEEK_CONNECT_TIMEOUT_SECONDS`, `AIDM_DEEPSEEK_READ_TIMEOUT_SECONDS`, `AIDM_NVIDIA_CONNECT_TIMEOUT_SECONDS`, and `AIDM_NVIDIA_READ_TIMEOUT_SECONDS`.
6. Gemini and OpenAI-compatible providers skip cooled-down models after repeated 429/rate-limit responses; tune with `AIDM_LLM_RATE_LIMIT_THRESHOLD` and `AIDM_LLM_RATE_LIMIT_COOLDOWN_SECONDS`.
7. Runtime provider mutation is owned by `aidm_server.blueprints.runtime_config`; the generic system blueprint should stay read-only health/metrics plus operational utilities.

## Incident Playbook
1. `error_code=unauthorized`: verify bearer token or socket connect auth payload; tokens are not accepted in event payloads or query strings.
2. `error_code=rate_limited`: increase limits or reduce client burst rate.
3. `error_code=dm_generation_failed`: switch to fallback provider or verify provider key/model.
4. Segment not triggering: inspect segment `trigger_condition` JSON and session/campaign state.
5. Missing external telemetry: verify `AIDM_TELEMETRY_ENABLED`, endpoint URL, API key, timeout.
6. DM response visible but not saved: inspect `dm_turns.status`, the matching `turn_events` rows, backend logs after `dm_response_end`, and whether canon extraction/projection failed before `session_log_update`.
7. TTS icon on but silent: verify `/api/tts/config`, browser autoplay policy, visible frontend TTS errors, and direct `/api/tts/stream` behavior with a short sentence.
8. Frontend connected to wrong backend: restart Vite with `VITE_AIDM_API_BASE_URL=http://127.0.0.1:5050`, then verify the backend URL displayed in the top bar.
9. Created campaign has no players/sessions: create or select a player for the campaign, then start a session; the campaign workspace endpoint should show `player_count` and `session_count`.

## Safe Flags for Closed Beta
- `AIDM_AUTH_REQUIRED=true`
- `AIDM_RULES_ENGINE_ENABLED=true`
- `AIDM_SEGMENT_EVALUATOR_ENABLED=true`
- `AIDM_SOCKETIO_ASYNC_MODE=threading`
- `AIDM_RATE_LIMIT_WINDOW_SECONDS=30`
- `AIDM_RATE_LIMIT_MAX_API_REQUESTS=120`
- `AIDM_RATE_LIMIT_MAX_SOCKET_MESSAGES=40`
- `AIDM_RATE_LIMIT_STORE=memory` for local runs, or `database` when multiple workers must share one limit window.
- `AIDM_TELEMETRY_ENABLED=true` (if external telemetry endpoint is available)

## Local-Only Boundaries
- `.env.local` writes from `/api/llm/config` are for local runtime switching.
- `AIDM_AUTH_REQUIRED=false`, wildcard CORS, SQLite, Flask admin, in-memory rate limiting, the in-memory turn coordinator, and module-global socket state are local/private deployment conveniences.
- SQLite databases/backups are developer runtime data. Local defaults use `~/.aidm/`; keep real DBs and backups outside `aidm_server/instance/` before packaging or sharing.
- Structured JSON-like fields intentionally remain JSON text while SQLite is supported; see `docs/json_storage_policy.md` before changing these columns to native JSON.
- Browser QA screenshots and traces should be written under ignored paths such as `tmp/verification_artifacts/` and cleaned with `scripts/cleanup_artifacts.sh`.
- Production bootstrap rejects wildcard CORS and requires auth.
- Bootstrap tightens `.env.local`, local SQLite data directories such as `~/.aidm` or `instance`, and SQLite DB/backups when present.
