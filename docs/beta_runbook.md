# AI-DM Beta Runbook

## Startup
1. Set environment variables (`AIDM_ENV`, `AIDM_DATABASE_URI`, `AIDM_AUTH_REQUIRED`, `AIDM_API_AUTH_TOKENS`, and the selected provider key such as `GOOGLE_GENAI_API_KEY`, `AIDM_DEEPSEEK_API_KEY`, or `AIDM_NVIDIA_API_KEY`).
2. For production-like socket runtime, keep `AIDM_SOCKETIO_ASYNC_MODE=threading` unless you intentionally switch modes.
3. Install dependencies: `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`. The requirements file applies `requirements.constraints.txt` for repeatable direct dependency versions.
4. Apply migrations: `flask db upgrade` (or run bootstrap command below).
5. Bootstrap check/start command:
   - Check only: `.venv/bin/python scripts/deploy_bootstrap.py --check-only`
   - Start after checks: `.venv/bin/python scripts/deploy_bootstrap.py`
6. Verify health: `GET /api/health`.
7. For the canonical local UI, start `aidm_frontend` with `VITE_AIDM_API_BASE_URL` pointed at the backend.

## Optional TTS
1. Set `AIDM_DEEPGRAM_API_KEY`.
2. Optionally set `AIDM_DEEPGRAM_TTS_MODEL` (default: `aura-2-draco-en`).
3. Confirm `GET /api/tts/config` returns `configured: true`.
4. Toggle TTS in the React frontend. DM responses should be queued for speech; playback or provider failures should surface as visible frontend errors.

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
4. Treat `turn_events` as the audit trail. `dm_turns`, `session_log_entries`, `PlayerAction`, and `SessionState` are projections or convenience tables that should agree with the event spine.
5. If a future change rewrites projection logic, verify both the event rows and the projected session log/state before assuming the UI is wrong.

The per-session turn coordinator is intentionally single-process. It serializes turns inside one Flask process, prunes idle lock entries, and drops idle locks when a session is deleted. Multi-worker or distributed deployments still need a durable queue or database/advisory-lock strategy.

## Provider Switching
1. Changing provider/model mid-session can alter tone, continuity, latency, and rules behavior.
2. Prefer switching between sessions or immediately after a session recap when possible.
3. For beta debugging, record provider/model changes in notes or a system log so later turn quality can be tied back to runtime changes.
4. Persistent provider changes through `/api/llm/config` are local/test only; production-like environments should use environment variables and restart/redeploy.

## Incident Playbook
1. `error_code=unauthorized`: verify bearer token and socket auth token.
2. `error_code=rate_limited`: increase limits or reduce client burst rate.
3. `error_code=dm_generation_failed`: switch to fallback provider or verify provider key/model.
4. Segment not triggering: inspect segment `trigger_condition` JSON and session/campaign state.
5. Missing external telemetry: verify `AIDM_TELEMETRY_ENABLED`, endpoint URL, API key, timeout.
6. DM response visible but not saved: inspect `dm_turns.status`, the matching `turn_events` rows, backend logs after `dm_response_end`, and whether canon extraction/projection failed before `session_log_update`.
7. TTS icon on but silent: verify `/api/tts/config`, browser autoplay policy, visible frontend TTS errors, and direct `/api/tts/speak` behavior with a short sentence.
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
- `AIDM_TELEMETRY_ENABLED=true` (if external telemetry endpoint is available)

## Local-Only Boundaries
- `.env.local` writes from `/api/llm/config` are for local runtime switching.
- `AIDM_AUTH_REQUIRED=false`, wildcard CORS, SQLite, Flask admin, in-memory rate limiting, and module-global socket state are local/private deployment conveniences.
- Production bootstrap rejects wildcard CORS and requires auth.
- Bootstrap tightens `.env.local`, the local `instance` directory, and SQLite DB/backups when present.
