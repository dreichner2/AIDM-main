# Production Readiness

Use this as the closed-beta deployment checklist. Local launcher behavior is
useful for development, but it is not the production boundary.

## Required Configuration

Use `.env.production.example` as the placeholder template for deployment
secret/env managers.

- `AIDM_ENV=production`
- `FLASK_SECRET_KEY=<strong explicit secret>`
- `AIDM_AUTH_REQUIRED=true`
- `AIDM_API_AUTH_TOKENS` or `AIDM_API_AUTH_TOKEN_WORKSPACES` configured
- `AIDM_AUTO_CREATE_SCHEMA=false`
- `AIDM_RATE_LIMIT_STORE=database`
- `AIDM_TURN_COORDINATOR_STORE=database`
- `AIDM_SOCKETIO_WORKER_MODEL=single`, `sticky`, or `message_queue`
- `AIDM_SOCKETIO_MESSAGE_QUEUE=<queue-url>` when the worker model is
  `message_queue`
- `AIDM_OBSERVABILITY_PROVIDER=<provider-name>`
- `AIDM_ALERT_OWNER=<team-or-person>`
- `AIDM_SECURITY_HEADERS_ENABLED=true`
- Explicit REST and Socket.IO CORS allowlists, unless same-origin deployment
  intentionally leaves them empty
- For hosted cookie-only account auth:
  `AIDM_ACCOUNT_COOKIE_AUTH_ENABLED=true`,
  `AIDM_ACCOUNT_COOKIE_SECURE=true`, and
  `AIDM_ACCOUNT_TOKEN_RESPONSE_ENABLED=false`

## Startup

1. Install runtime dependencies from `requirements.runtime.txt` with
   `requirements.constraints.txt`.
2. Apply migrations.
3. Run `python scripts/deploy_bootstrap.py --check-only`.
4. Run deployment readiness against the target environment and, when available,
   the deployed target URL:
   `make deployment-readiness DEPLOYMENT_READINESS_ARGS="--env-file /path/to/env --target-url https://aidm.example.com --auth-token <token>"`.
   Add `--same-origin-deployment`, `--auth-storage-exception`, or
   `--socketio-staging-proof` only when those deployment choices are
   intentionally documented.
5. Start AIDM with a production Socket.IO-capable server. Do not use
   `deploy_bootstrap.py` as the production server process.

## CI Gates

- Secret scan: `python scripts/scan_secrets.py`
- Python dependency audit: `python -m pip_audit -r requirements.runtime.txt`
- Python correctness lint: `python -m ruff check --select E9,F63,F7,F82 aidm_server tests scripts`
- Backend tests: `python -m pytest`
- Backup/restore drill for local/private SQLite beta data:
  `python scripts/backup_restore_drill.py --database-uri sqlite:////absolute/path/to/dnd_ai_dm.db`
- API type drift: `python scripts/generate_api_types.py` plus a clean
  `git diff --exit-code aidm_frontend/src/apiContract.generated.ts`
- Frontend tests, build, bundle budget, and browser smoke
- Observability bundle:
  `python scripts/check_observability_bundle.py`, plus
  `python scripts/check_observability_bundle.py --check-docker-compose --require-docker`
  on machines that should prove Docker Compose config
- Deployment readiness:
  `python scripts/deployment_readiness_check.py --env-file /path/to/env`

## Beta SLOs

Track these before inviting a wider group:

- DM response p95 latency
- AI provider failure rate
- Canon job failure rate
- Turn persistence failure rate
- Socket unauthorized and rate-limited event counts
- Average coherence feedback score
- Bad-turn report count by provider/model

Alert thresholds are owned by `AIDM_ALERT_OWNER` in the chosen
`AIDM_OBSERVABILITY_PROVIDER`. The local Prometheus/Grafana bundle under
`observability/` is useful for development and smoke testing; hosted beta
deployments should configure the managed destination named in production env.

## Operational Notes

- SQLite, disabled auth, wildcard CORS, in-memory rate limiting, in-memory turn
  coordination, local `.env.local` writes, and module-global Socket.IO state are
  local/private deployment conveniences.
- For multiple backend workers, use database-backed turn coordination and rate
  limiting, then choose `AIDM_SOCKETIO_WORKER_MODEL=sticky` with load balancer
  affinity or `message_queue` with `AIDM_SOCKETIO_MESSAGE_QUEUE`, and prove that
  model with a staging smoke test.
- Session storage is acceptable for local/private beta. Hosted same-origin
  deployments can use the server-issued `HttpOnly` account cookie mode,
  suppress raw account tokens in JSON responses, and rely on the companion
  `aidm_csrf_token` double-submit header for unsafe REST requests.
