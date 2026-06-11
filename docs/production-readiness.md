# Production Readiness

Use this as the closed-beta deployment checklist. Local launcher behavior is
useful for development, but it is not the production boundary.

## Required Configuration

- `AIDM_ENV=production`
- `FLASK_SECRET_KEY=<strong explicit secret>`
- `AIDM_AUTH_REQUIRED=true`
- `AIDM_API_AUTH_TOKENS` or `AIDM_API_AUTH_TOKEN_WORKSPACES` configured
- `AIDM_AUTO_CREATE_SCHEMA=false`
- `AIDM_RATE_LIMIT_STORE=database`
- `AIDM_TURN_COORDINATOR_STORE=database`
- Explicit REST and Socket.IO CORS allowlists, unless same-origin deployment
  intentionally leaves them empty

## Startup

1. Install runtime dependencies from `requirements.runtime.txt` with
   `requirements.constraints.txt`.
2. Apply migrations.
3. Run `python scripts/deploy_bootstrap.py --check-only`.
4. Start AIDM with a production Socket.IO-capable server. Do not use
   `deploy_bootstrap.py` as the production server process.

## CI Gates

- Secret scan: `python scripts/scan_secrets.py`
- Python dependency audit: `python -m pip_audit -r requirements.runtime.txt`
- Python correctness lint: `python -m ruff check --select E9,F63,F7,F82 aidm_server tests scripts`
- Backend tests: `python -m pytest`
- API type drift: `python scripts/generate_api_types.py` plus a clean
  `git diff --exit-code aidm_frontend/src/apiContract.generated.ts`
- Frontend tests, build, bundle budget, and browser smoke

## Beta SLOs

Track these before inviting a wider group:

- DM response p95 latency
- AI provider failure rate
- Canon job failure rate
- Turn persistence failure rate
- Socket unauthorized and rate-limited event counts
- Average coherence feedback score

Alert thresholds should be owned by the chosen hosting/observability platform.
The local Prometheus/Grafana bundle under `observability/` is useful for
development and smoke testing, but hosted alert routing is still a deployment
decision.

## Operational Notes

- SQLite, disabled auth, wildcard CORS, in-memory rate limiting, in-memory turn
  coordination, local `.env.local` writes, and module-global Socket.IO state are
  local/private deployment conveniences.
- For multiple backend workers, use database-backed turn coordination and rate
  limiting, then prove the actual worker model with a staging smoke test.
- Keep account auth threat-model notes current. Session storage is acceptable
  for local/private beta, but hosted production should evaluate secure
  HTTP-only cookies.
