# AI-DM (AI Dungeon Master)

Narrative-first backend for an AI-assisted D&D experience.

AI-DM provides:
- REST APIs for worlds, campaigns, players, sessions, maps, and story segments.
- Real-time play over Socket.IO (`join_session`, `send_message`, streamed DM output).
- Stateful session continuity (`dm_turns`, `session_states`, rolling summaries, memory snippets, emergent canon memory).
- D&D-lite fairness rails (roll detection, roll type/DC band suggestions, deferred outcomes) without constraining world creativity.
- Security and operations controls (auth, CORS allowlists, request limits, rate limiting, telemetry).

This README is aligned to the current codebase as of June 2026.

---

## Table of Contents
1. [Current Beta Status](#current-beta-status)
2. [Quick Start (Beginner Friendly)](#quick-start-beginner-friendly)
3. [Enable Gemini AI (Flash with 2.5 Fallback)](#enable-gemini-ai-flash-with-25-fallback)
4. [Enable NVIDIA Kimi (moonshotai/kimi-k2.5)](#enable-nvidia-kimi-moonshotaikimi-k25)
5. [Configuration Reference](#configuration-reference)
6. [One-Command Bootstrap](#one-command-bootstrap)
7. [REST API Reference](#rest-api-reference)
8. [Socket.IO Contract](#socketio-contract)
9. [Auth and Error Contracts](#auth-and-error-contracts)
10. [Telemetry and Metrics](#telemetry-and-metrics)
11. [Database and Migrations](#database-and-migrations)
12. [Testing](#testing)
13. [Troubleshooting](#troubleshooting)
14. [Project Structure](#project-structure)
15. [Known Gaps and Next Steps](#known-gaps-and-next-steps)
16. [License](#license)

---

## Current Beta Status

### Implemented
- Reliability baseline (lazy LLM provider, centralized config, structured errors, transactional `send_message`, safer defaults).
- Narrative state engine (`DmTurn`, `SessionState`, deterministic context builder, bounded history, fallback narration).
- Emergent canon memory (`story_entities`, `story_facts`, `story_threads`, `turn_canon_updates`) with projection back into session state.
- Append-only turn event spine (`turn_events`) with legacy session/player tables treated as projections.
- Canon validation and entity linking (alias-aware entity reuse, conflicting-fact rejection unless marked as a controlled change).
- Deterministic inventory consequences for explicit item gains/losses, persisted on players without constraining improvisation elsewhere.
- D&D-lite mechanics and segment activation (rules classifier for fairness, keyword/state/manual segment triggers as optional authored threads).
- Security/internet-readiness baseline (REST+socket token auth, CORS allowlists, request size limit, API+socket rate limits, structured correlation logging).
- Beta hardening essentials (pytest suite, migration chain tests, smoke flow script, release checklist/runbook docs).

### Partially Implemented / Pending
- External telemetry backend is optional and not pre-wired to a managed metrics stack.
- Closed-beta program execution (real users + ongoing telemetry review) is operational work, not fully automated in code.
- Some Python 3.14+ deprecation warnings may still appear in optional/legacy paths.

---

## Quick Start (Beginner Friendly)

### 1) Create a virtual environment and install deps
```bash
cd /Users/danny/Downloads/AIDM-main
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` applies `requirements.constraints.txt`, which pins the current direct dependency set for repeatable local installs.

### 2) Start backend immediately (no AI key required)
This runs migrations, validates config/endpoints, then starts the server.
```bash
./scripts/run_local_backend.sh
```

Default from this launcher:
- Port: `5050`
- Provider: deterministic fallback (if no `GOOGLE_GENAI_API_KEY` is set)

### 3) Verify backend health
```bash
curl http://127.0.0.1:5050/api/health
curl http://127.0.0.1:5050/api/campaigns
```

### 4) Connect the web client
The canonical local frontend is the React app in `aidm_frontend/`.

```bash
cd aidm_frontend
npm ci
VITE_AIDM_API_BASE_URL=http://127.0.0.1:5050 npm run dev -- --host 127.0.0.1
```

Open the printed Vite URL, usually:
```text
http://127.0.0.1:5173/
```

The hosted client can also connect to a local backend. Open
[aidm-client.vercel.app](https://aidm-client.vercel.app) and use:
```text
http://127.0.0.1:5050
```

If your browser blocks mixed/private-network requests from HTTPS client to local HTTP backend, keep:
```bash
AIDM_CORS_ALLOW_PRIVATE_NETWORK=true
```

---

## Enable Gemini AI (Flash with 2.5 Fallback)

Important: if your API key was shared publicly, rotate it before production use.

### 1) Configure env vars
```bash
export GOOGLE_GENAI_API_KEY=YOUR_KEY
export AIDM_LLM_PROVIDER=gemini
export AIDM_LLM_MODEL=models/gemini-3-flash-preview
export AIDM_LLM_FALLBACK_MODELS=models/gemini-2.5-flash
```

### 2) Optional model discovery and provider check
```bash
.venv/bin/python scripts/list_gemini_models.py
.venv/bin/python scripts/check_llm_provider.py
```

### 3) Start backend
```bash
./scripts/run_local_backend.sh
```

Runtime behavior:
- Tries `AIDM_LLM_MODEL` first.
- Falls back through `AIDM_LLM_FALLBACK_MODELS` in order.
- If all fail, returns deterministic continuity-safe narration.

---

## Enable NVIDIA Kimi (moonshotai/kimi-k2.5)

```bash
export AIDM_LLM_PROVIDER=nvidia
export AIDM_NVIDIA_API_KEY=YOUR_NVIDIA_KEY
export AIDM_LLM_MODEL=moonshotai/kimi-k2.5
export AIDM_NVIDIA_INVOKE_URL=https://integrate.api.nvidia.com/v1
# optional model fallback and tuning
export AIDM_LLM_FALLBACK_MODELS=meta/llama-3.1-70b-instruct
export AIDM_NVIDIA_THINKING=true
export AIDM_NVIDIA_MAX_TOKENS=16384
export AIDM_NVIDIA_TEMPERATURE=1.0 # thinking mode recommendation
export AIDM_NVIDIA_TOP_P=0.95
```

Then run:
```bash
./scripts/run_local_backend.sh
.venv/bin/python scripts/check_llm_provider.py
```

For persistent local-only Kimi setup, run this once:
```bash
./scripts/configure_local_kimi.sh
```

That writes an untracked `.env.local` file, pins `moonshotai/kimi-k2.5`, and leaves `AIDM_LLM_FALLBACK_MODELS` empty so Kimi is the only model used during local testing.

---

## Enable DeepSeek

```bash
export AIDM_LLM_PROVIDER=deepseek
export AIDM_DEEPSEEK_API_KEY=YOUR_DEEPSEEK_KEY
export AIDM_LLM_MODEL=deepseek-v4-pro
```

Then run:
```bash
./scripts/run_local_backend.sh
.venv/bin/python scripts/check_llm_provider.py
```

DeepSeek-compatible defaults live in `aidm_server/config.py` and
`aidm_server/llm.py`. Rotate any provider key that has been pasted into chat,
screenshots, docs, or issue text.

---

## Enable Deepgram TTS

DM narration TTS is optional. When configured, the React frontend TTS toggle
requests speech for DM responses from the backend and plays the returned audio.

```bash
export AIDM_DEEPGRAM_API_KEY=YOUR_DEEPGRAM_KEY
export AIDM_DEEPGRAM_TTS_MODEL=aura-2-draco-en
```

Then start backend and frontend normally. Check configuration with:
```bash
curl http://127.0.0.1:5050/api/tts/config
```

Notes:
- The frontend strips markdown/thought tags before speech.
- The backend streams MP3 audio from `/api/tts/speak`.
- If TTS is toggled on but silent, check `/api/tts/config`, browser autoplay
  policy, and visible frontend errors.
- Long narrator responses are chunked; first speech should begin before the
  full response is synthesized when browser streaming support is available.

---

## Configuration Reference

All runtime config is centralized in `aidm_server/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `AIDM_ENV` | `development` | Environment mode (`development`, `test`, `production`). |
| `AIDM_DEBUG` | `true` when not production | Flask debug mode. |
| `FLASK_SECRET_KEY` | random ephemeral key outside production; required in production | Flask session/app secret. |
| `AIDM_DATABASE_URI` | `sqlite:///instance/dnd_ai_dm.db` | SQLAlchemy DB URL. |
| `AIDM_AUTO_CREATE_SCHEMA` | `true` | Entry-point runtime may call `db.create_all()` before serving. Set `false` when relying strictly on migrations. |
| `AIDM_MAX_REQUEST_BYTES` | `1048576` | Max request body size (bytes). |
| `AIDM_CORS_ALLOWLIST` | `*` in debug, empty in production | Comma-separated allowed origins for REST `/api/*`. |
| `AIDM_SOCKET_CORS_ALLOWLIST` | mirrors `AIDM_CORS_ALLOWLIST` | Comma-separated allowed origins for Socket.IO. |
| `AIDM_CORS_ALLOW_PRIVATE_NETWORK` | `true` outside production | Allows private-network CORS preflight behavior. |
| `AIDM_SOCKETIO_ASYNC_MODE` | `threading` | Socket.IO async mode. |
| `AIDM_AUTH_REQUIRED` | `false` | Enforce bearer token auth for API/socket (except `/api/health`). |
| `AIDM_API_AUTH_TOKENS` | empty | Comma-separated valid bearer tokens. |
| `AIDM_RATE_LIMIT_WINDOW_SECONDS` | `30` | Fixed window size for API/socket limits. |
| `AIDM_RATE_LIMIT_MAX_API_REQUESTS` | `120` | Max API requests per key+window. |
| `AIDM_RATE_LIMIT_MAX_SOCKET_MESSAGES` | `40` | Max socket messages per sid/session+window. |
| `AIDM_RULES_ENGINE_ENABLED` | `true` | Enables rules classifier metadata. |
| `AIDM_SEGMENT_EVALUATOR_ENABLED` | `true` | Enables automatic segment trigger evaluation. |
| `AIDM_LLM_PROVIDER` | `gemini` | Provider selector (`gemini`, `nvidia`/`kimi`, or deterministic fallback). |
| `AIDM_LLM_MODEL` | `models/gemini-3-flash-preview` | Primary model name. |
| `AIDM_LLM_FALLBACK_MODELS` | empty | Comma-separated model fallbacks. |
| `AIDM_LLM_RATE_LIMIT_THRESHOLD` | `2` | Consecutive `429` count before model cooldown begins. |
| `AIDM_LLM_RATE_LIMIT_COOLDOWN_SECONDS` | `120` | Seconds to skip a rate-limited model before retrying it. |
| `GOOGLE_GENAI_API_KEY` | unset | Gemini API key. |
| `AIDM_DEEPSEEK_API_KEY` | unset | DeepSeek API key. |
| `AIDM_DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek/OpenAI-compatible base URL. |
| `AIDM_NVIDIA_API_KEY` | unset | NVIDIA API key (used when `AIDM_LLM_PROVIDER=nvidia`). |
| `AIDM_NVIDIA_INVOKE_URL` | `https://integrate.api.nvidia.com/v1` | NVIDIA base URL (auto-normalized to `/chat/completions`). |
| `AIDM_NVIDIA_THINKING` | `true` | Official Kimi thinking control (`thinking.type=enabled|disabled`). |
| `AIDM_NVIDIA_MAX_TOKENS` | `16384` | Max completion tokens for NVIDIA provider. |
| `AIDM_NVIDIA_TEMPERATURE` | `1.0` thinking / `0.6` instant | Sampling temperature for NVIDIA provider. |
| `AIDM_NVIDIA_TOP_P` | `0.95` | Top-p sampling for NVIDIA provider. |
| `AIDM_NVIDIA_TIMEOUT_SECONDS` | `60` | Request timeout for NVIDIA provider calls. |
| `AIDM_DEEPGRAM_API_KEY` | unset | Deepgram API key for optional TTS. |
| `AIDM_DEEPGRAM_TTS_MODEL` | `aura-2-draco-en` | Deepgram speech model used by `/api/tts/speak`. |
| `AIDM_TELEMETRY_ENABLED` | `false` | Enables outbound telemetry events. |
| `AIDM_TELEMETRY_ENDPOINT` | empty | External telemetry ingest endpoint. |
| `AIDM_TELEMETRY_API_KEY` | unset | Bearer token for telemetry endpoint. |
| `AIDM_TELEMETRY_TIMEOUT_SECONDS` | `2` | External telemetry request timeout. |
| `HOST` | `0.0.0.0` | Bootstrap server host. |
| `PORT` | `5000` (bootstrap), `5050` via `run_local_backend.sh` | Server port. |

---

## One-Command Bootstrap

`deploy_bootstrap` runs preflight checks before server start:
1. `flask db upgrade`
2. `/api/health` and `/api/metrics` sanity checks
3. Socket auth behavior checks
4. Rate-limit/auth config validation
5. Local `.env.local` and SQLite permission hardening
6. Production CORS and network exposure guardrails

### Check-only
```bash
.venv/bin/python scripts/deploy_bootstrap.py --check-only
```

### Start server after checks
```bash
.venv/bin/python scripts/deploy_bootstrap.py --port 5050
```

### Recommended local launcher
```bash
./scripts/run_local_backend.sh
```

---

## REST API Reference

Base path: `/api`

### Worlds
- `POST /api/worlds`
- `GET /api/worlds/<world_id>`

### Campaigns
- `POST /api/campaigns`
- `GET /api/campaigns`
- `GET /api/campaigns/<campaign_id>`

### Players
- `GET /api/players/campaigns/<campaign_id>/players`
- `POST /api/players/campaigns/<campaign_id>/players`
- `GET /api/players/<player_id>`

### Sessions
- `POST /api/sessions/start`
- `POST /api/sessions/<session_id>/end`
- `GET /api/sessions/campaigns/<campaign_id>/sessions`
- `GET /api/sessions/<session_id>/log`
  - Query param: `limit` (1..500, default 200)
- `GET /api/sessions/<session_id>/state`
- `PATCH /api/sessions/<session_id>`
  - Payload: `{ "name": "New session name" }`
- `DELETE /api/sessions/<session_id>`

Session delete is currently a hard delete for the session transcript/projections.
Session-owned rows are removed, and canon rows that reference deleted turns are
kept but have turn/session references nulled where needed. Use this as a local
cleanup feature until product-level archive/restore semantics are added.

### Maps
- `POST /api/maps`
- `GET /api/maps?world_id=<id>&campaign_id=<id>`
- `GET /api/maps/<map_id>`
- `PUT/PATCH /api/maps/<map_id>`

### Segments
- `POST /api/segments`
- `GET /api/segments?campaign_id=<id>`
- `GET /api/segments/<segment_id>`
- `PUT/PATCH /api/segments/<segment_id>`
- `DELETE /api/segments/<segment_id>`

### System and Beta
- `GET /api/health`
- `GET /api/metrics`
- `GET /api/beta/summary`
- `POST /api/feedback/coherence`

#### Coherence feedback payload
```json
{
  "session_id": 1,
  "turn_id": 42,
  "coherence_score": 4,
  "notes": "Strong continuity across turns."
}
```

---

## Socket.IO Contract

### Client -> Server events
- `connect` (optional auth payload)
- `join_session`
  - `{ "session_id": <int>, "player_id": <int> }`
- `leave_session`
  - `{ "session_id": <int>, "player_id": <int> }`
- `send_message`
  - Required: `session_id`, `campaign_id`, `world_id`, `player_id`, `message`
  - Optional auth token fields: `token` or `auth_token`

### Server -> Client events
- `active_players`
- `player_joined`
- `player_left`
- `new_message`
- `segment_triggered`
- `roll_required` (emitted when a pending deferred check must be resolved before a new action)
- `dm_response_start`
- `dm_chunk`
- `dm_response_end`
- `session_log_update`
- `error`

### DM metadata fields (additive, backward compatible)
`dm_response_start`, `dm_chunk`, `dm_response_end` include:
- `turn_id`
- `requires_roll`
- `rules_hint`
  - `roll_type`, `dc_hint`, `reason`, `confidence`, `roll_value`, `outcome_deferred`
- `context_version`

### Roll gating behavior
- If a prior turn is still unresolved (`outcome_deferred=true`), new non-roll actions are rejected.
- Server emits:
  - `roll_required` event with `pending_turn_id`, `rule_type`, `dc_hint`, and a roll prompt.
  - `error` envelope with `error_code=roll_required`.
- Client should submit a roll result (for example, `I roll a d20: 14`) before continuing new actions.

---

## Auth and Error Contracts

### REST auth
- When `AIDM_AUTH_REQUIRED=true`, send:
```http
Authorization: Bearer <token>
```
- `GET /api/health` remains open for liveness checks.

### Socket auth
If auth is required, token can be supplied by:
1. Socket auth payload (`{ "token": "..." }`)
2. `Authorization: Bearer ...` header

Do not put auth tokens in socket event payloads or query strings.

### Error envelope
HTTP and socket errors share this shape:
```json
{
  "error": "Human readable message",
  "error_code": "machine_code",
  "details": {}
}
```

### Correlation IDs
- Supply `X-Request-ID` to REST calls to control correlation ID.
- Response echoes `X-Request-ID`.
- Logs include correlation/session/turn IDs.

---

## Telemetry and Metrics

### Local metrics endpoint
`GET /api/metrics` returns:
- in-memory counters
- timing aggregates
- beta summary block

### Beta summary endpoint
`GET /api/beta/summary` includes:
- `turn_latency_ms_avg`
- `ai_failure_rate`
- `session_completion_rate`
- `coherence_feedback_avg`
- `coherence_feedback_count`

### Optional external telemetry delivery
```bash
export AIDM_TELEMETRY_ENABLED=true
export AIDM_TELEMETRY_ENDPOINT=https://your-endpoint.example/ingest
export AIDM_TELEMETRY_API_KEY=your_token
export AIDM_TELEMETRY_TIMEOUT_SECONDS=2
```

---

## Database and Migrations

### Migration chain
- `0001_initial_core`
- `0002_beta_runtime`
- `0003_turn_confidence_feedback`
- `0004_emergent_memory_runtime`
- `0005_turn_event_spine`

### Run migrations manually
```bash
export FLASK_APP=aidm_server.main:create_app
flask db upgrade
```

### Notes
- `AIDM_AUTO_CREATE_SCHEMA=true` still supports local bootstrap convenience through the explicit runtime entrypoint.
- For stricter environments, set `AIDM_AUTO_CREATE_SCHEMA=false` and rely on migrations only.

---

## Testing

### Run full test suite
```bash
.venv/bin/python -m pytest -q
```

### Run migration tests only
```bash
.venv/bin/python -m pytest -q tests/test_migrations.py
```

### Run smoke flow (campaign -> session -> message -> recap)
```bash
.venv/bin/python scripts/smoke_beta_flow.py
```

By default, the smoke flow uses an isolated in-memory database and deterministic
fallback provider. Use `--use-local-env` only when you intentionally want to run
against `.env.local`, the configured database, and the configured provider.

---

## Production And Local-Only Boundaries

Local development conveniences should not be treated as production defaults:

- `.env.local` writes from `/api/llm/config` are for local runtime switching.
- Wildcard CORS is local/debug only; production bootstrap rejects wildcard CORS.
- `AIDM_AUTH_REQUIRED=false` is local/private-network only.
- SQLite and local DB backups are developer data, not a shared deployment store.
- Flask admin is a local/admin surface and should be deliberately gated.
- In-memory rate limiting and module-global socket state are single-process only.
- `scripts/smoke_beta_flow.py` defaults to isolated fallback mode to avoid
  local DB pollution and provider spend.

Bootstrap tightens `.env.local` to `0600`, `aidm_server/instance` to `0700`,
and local SQLite database/backups to `0600` when those files are present.

### Release docs
- `docs/release_checklist.md`
- `docs/beta_runbook.md`

---

## Troubleshooting

### `AxiosError: Network Error` from hosted web client
Usually means browser could not reach backend at all (not an API 4xx/5xx response).

Checklist:
1. Backend running and healthy:
   ```bash
   curl http://127.0.0.1:5050/api/health
   ```
2. Use reachable URL in client (not `localhost` from another machine).
3. If HTTPS client -> local HTTP backend, keep:
   ```bash
   AIDM_CORS_ALLOW_PRIVATE_NETWORK=true
   ```
4. For local development, set permissive CORS:
   ```bash
   AIDM_CORS_ALLOWLIST=*
   AIDM_SOCKET_CORS_ALLOWLIST=*
   ```
5. If exposing over internet, tunnel or host backend (for example ngrok/cloudflared) and use that public URL.

### Auth failures
- REST returns `401 unauthorized` when token missing/invalid and auth is required.
- Socket connect/join/send emits `error` with `error_code=unauthorized` when token is missing/invalid.

### AI provider issues
- If Gemini key/model is invalid, backend still runs.
- AI responses fall back to deterministic narration instead of crashing the app.

---

## Project Structure

```text
AIDM-main/
├── aidm_server/
│   ├── blueprints/            # REST + Socket handlers
│   ├── auth.py                # REST/socket token validation
│   ├── config.py              # Centralized env configuration
│   ├── contracts.py           # Provider and segment runtime contracts
│   ├── deploy_bootstrap.py    # Preflight + startup pipeline
│   ├── llm.py                 # Provider abstraction + Gemini/fallback
│   ├── logging_context.py     # Correlation/session/turn log context
│   ├── models.py              # SQLAlchemy models
│   ├── rate_limiter.py        # Fixed-window limiter
│   ├── rules.py               # D&D-lite rules hints
│   ├── segment_triggers.py    # Segment trigger evaluator
│   └── telemetry.py           # Metrics/events + optional outbound delivery
├── docs/
│   ├── beta_runbook.md
│   └── release_checklist.md
├── migrations/
│   └── versions/
├── scripts/
│   ├── run_local_backend.sh
│   ├── deploy_bootstrap.py
│   ├── check_llm_provider.py
│   ├── list_gemini_models.py
│   └── smoke_beta_flow.py
└── tests/
```

---

## Known Gaps and Next Steps

Still open from the long-range vision:
- Full external telemetry/observability stack integration (Prometheus/Grafana or managed equivalent) is not bundled.
- Closed-beta execution and post-beta prioritization remain ongoing product operations.
- Canon extraction still blends provider-assisted parsing with deterministic heuristics; deeper semantic contradiction policies can be added in a later pass.
- Potential Python 3.14 deprecation cleanup (where applicable) can be finished in a dedicated maintenance pass.

---

## License

MIT License.
