# Playable Beta Release Checklist

## Preflight
- [ ] `make closed-beta-rc` passes, or each equivalent gate below is recorded separately.
- [ ] `.venv/bin/python scripts/deploy_bootstrap.py --check-only` passes.
- [ ] `.venv/bin/python -m pytest` passes.
- [ ] `.venv/bin/python scripts/smoke_beta_flow.py` passes in isolated fallback mode.
- [ ] `.venv/bin/python scripts/scenario_regression.py` passes and records provider/model for each scenario.
- [ ] If live/local validation is needed, `.venv/bin/python scripts/smoke_beta_flow.py --use-local-env` is run intentionally against the target database/provider.
- [ ] `GET /api/health` confirms expected flags.
- [ ] `flask db upgrade` applies cleanly.
- [ ] GitHub Actions `AIDM CI` passes backend tests, frontend checks, bundle budget, and browser smoke.
- [ ] GitHub Actions `Closed Beta RC` passes before tagging an RC build.
- [ ] `make deployment-readiness DEPLOYMENT_READINESS_ARGS="--env-file <target-env> --target-url <target-url> --auth-token <token>"` passes for the hosted/staging target, with documented flags for same-origin CORS, bearer-token auth exceptions, or Socket.IO staging proof when applicable.

## Frontend
- [ ] `cd aidm_frontend && npm ci` installs from lockfile.
- [ ] `cd aidm_frontend && npm test` passes typecheck, lint, and unit tests.
- [ ] `cd aidm_frontend && npm run lint` passes.
- [ ] `cd aidm_frontend && npm run typecheck` passes.
- [ ] `cd aidm_frontend && npm run build` passes.
- [ ] `cd aidm_frontend && npm run bundle:budget` passes after build.
- [ ] `cd aidm_frontend && npm audit --omit=dev` has no unresolved production issues.
- [ ] Modal accessibility regressions cover focus placement, Escape close, focus trapping, focus return, dialog descriptions, and danger confirmation cancellation.

## Security
- [ ] `AIDM_AUTH_REQUIRED=true` in deployed environment.
- [ ] Strong token configured in `AIDM_API_AUTH_TOKENS`.
- [ ] CORS allowlists are explicit (no wildcard in production).
- [ ] Hosted same-origin deployments either enable HTTP-only account cookies or document why bearer/session storage remains acceptable.
- [ ] If cookie auth is enabled, `AIDM_ACCOUNT_COOKIE_SECURE=true`; if cookie-only browser auth is required, `AIDM_ACCOUNT_TOKEN_RESPONSE_ENABLED=false`.
- [ ] Cookie-only auth smoke proves unsafe REST requests include `X-AIDM-CSRF-Token` from the companion `aidm_csrf_token` cookie.
- [ ] Security headers are enabled, including `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, and `Permissions-Policy`.

## Data Integrity
- [ ] Database backup taken before deployment.
- [ ] `make backup-restore-drill BACKUP_RESTORE_DRILL_ARGS="--database-uri sqlite:////absolute/path/to/dnd_ai_dm.db"` creates a backup and verifies a restored copy for local/private SQLite beta databases. Hosted database restore drills are documented with the provider-specific runbook.
- [ ] New tables exist: `dm_turns`, `session_states`, `story_entities`, `story_facts`, `story_threads`, `turn_canon_updates`, `turn_events`, `session_state_mutation_audits`, and `operator_action_audits`.
- [ ] Session log and state endpoints return consistent turn IDs.
- [ ] Session export/import smoke restores a JSON export into a new active session without duplicating projected log entries.
- [ ] Bad-turn reports attach to the exact `turn_id`, provider, and model, and `/api/beta/incidents` plus the operator inspector Ops tab show failed turns, failed canon jobs, and tester reports for workspace admins.
- [ ] `/api/beta/audits` returns recent session-state mutation diffs and operator actions for workspace admins, including combat/equipment/campaign-pack progress, bestiary authoring, import, archive, restore, and delete activity.
- [ ] Migration chain verified (`upgrade/downgrade/upgrade` path).

## Runtime Quality
- [ ] Socket message stream includes `turn_id`, `requires_roll`, `rules_hint`, `context_version`.
- [ ] Typed `action_intent` metadata persists for roll/ability/item actions.
- [ ] `turn_status` events progress through narration, save, canon, and failure states.
- [ ] `AIDM_SOCKETIO_WORKER_MODEL` is explicitly set to `single`, `sticky`, or `message_queue`.
- [ ] Multi-worker deployments set `AIDM_TURN_COORDINATOR_STORE=database`, have migration `0011_session_turn_locks` applied, and prove sticky-session affinity or Socket.IO message-queue delivery in staging.
- [ ] Sticky or message-queue Socket.IO deployments provide `--socketio-staging-proof` to the deployment-readiness gate.
- [ ] Campaign-pack progress service calls are serialized through the reentrant session turn coordinator, including nested calls from active turn processing.
- [ ] Safe-mode banner is visible when the active provider is the deterministic fallback.
- [ ] Segment trigger events emit reason/spec metadata.
- [ ] Improvised canon is persisted into emergent memory tables after a narrated turn.
- [ ] Scenario quality regressions cover opening narration, impossible actions, combat roll prompts, item use, checkpoint triggers, NPC continuity, and canon recall.
- [ ] Session end recap is stored and retrievable.

## Observability
- [ ] `AIDM_OBSERVABILITY_PROVIDER` and `AIDM_ALERT_OWNER` are set in production.
- [ ] `/api/metrics` reflects request/turn counters.
- [ ] `/api/metrics/prometheus` returns Prometheus text output with API counters and beta gauges.
- [ ] Deployment readiness live checks pass for `/api/health`, `/api/metrics`, `/api/metrics/prometheus`, and required security headers.
- [ ] `make observability-check` validates the bundled Prometheus/Grafana files; on Docker-capable release machines, `make observability-check OBSERVABILITY_CHECK_ARGS="--check-docker-compose --require-docker"` also validates `docker compose config`.
- [ ] External telemetry endpoint receives events when enabled.
- [ ] Rate-limit and auth errors are monitored.
- [ ] DM generation failures are monitored and below threshold.
- [ ] TTS `/api/tts/stream` returns chunk headers and records mid-stream chunk failures in telemetry.

## Packaging
- [ ] `make clean` removes cache/runtime/build artifacts before packaging.
- [ ] `make clean-deps` removes local dependency folders when preparing a source-only handoff or commit.
- [ ] `make source-archive` creates a shareable source archive under `tmp/release/`.
- [ ] Release archive does not include `.venv`, `aidm_frontend/node_modules`, `aidm_frontend/dist`, local SQLite data, logs, or `.env.local`.
