# Playable Beta Release Checklist

## Preflight
- [ ] `.venv/bin/python scripts/deploy_bootstrap.py --check-only` passes.
- [ ] `.venv/bin/python -m pytest` passes.
- [ ] `.venv/bin/python scripts/smoke_beta_flow.py` passes in isolated fallback mode.
- [ ] If live/local validation is needed, `.venv/bin/python scripts/smoke_beta_flow.py --use-local-env` is run intentionally against the target database/provider.
- [ ] `GET /api/health` confirms expected flags.
- [ ] `flask db upgrade` applies cleanly.

## Frontend
- [ ] `cd aidm_frontend && npm ci` installs from lockfile.
- [ ] `cd aidm_frontend && npm run lint` passes.
- [ ] `cd aidm_frontend && npm run typecheck` passes.
- [ ] `cd aidm_frontend && npm run build` passes.
- [ ] `cd aidm_frontend && npm run bundle:budget` passes after build.
- [ ] `cd aidm_frontend && npm audit --omit=dev` has no unresolved production issues.

## Security
- [ ] `AIDM_AUTH_REQUIRED=true` in deployed environment.
- [ ] Strong token configured in `AIDM_API_AUTH_TOKENS`.
- [ ] CORS allowlists are explicit (no wildcard in production).

## Data Integrity
- [ ] Database backup taken before deployment.
- [ ] New tables exist: `dm_turns`, `session_states`, `story_entities`, `story_facts`, `story_threads`, `turn_canon_updates`, `turn_events`.
- [ ] Session log and state endpoints return consistent turn IDs.
- [ ] Migration chain verified (`upgrade/downgrade/upgrade` path).

## Runtime Quality
- [ ] Socket message stream includes `turn_id`, `requires_roll`, `rules_hint`, `context_version`.
- [ ] Segment trigger events emit reason/spec metadata.
- [ ] Improvised canon is persisted into emergent memory tables after a narrated turn.
- [ ] Session end recap is stored and retrievable.

## Observability
- [ ] `/api/metrics` reflects request/turn counters.
- [ ] External telemetry endpoint receives events when enabled.
- [ ] Rate-limit and auth errors are monitored.
- [ ] DM generation failures are monitored and below threshold.
