# AIDM Roadmap

AIDM is now in beta-hardening territory: the core gameplay, campaign, player,
session, world, map, Socket.IO, state pipeline, canon memory, and metrics
surfaces exist. The highest-return work is reducing security, runtime, and
maintenance risk before expanding gameplay scope.

Archived review material lives in:

- `docs/archive/improvements_suggestions_legacy.md`
- `docs/archive/organized_improvement_suggestions_legacy.md`

## Done

- Backend app factory, central config, request IDs, CORS scoping, auth context,
  rate limiting, migration/bootstrap checks, and production schema guardrails.
- Backend-owned DTO contracts with generated frontend TypeScript types.
- Session event spine, turn persistence, turn status events, state application,
  canon job queue, and projection repair tooling.
- Frontend TypeScript strictness, split CSS files, extracted hooks/components,
  browser smoke tests, bundle budget checks, and generated API contract usage.
- Account login hardening for passwordless legacy accounts: existing accounts
  now require a valid saved account token, a stored password match, or an
  explicit legacy claim that sets a password immediately.
- Read-only player detail fetches: starting inventory/spell repair now lives
  behind an explicit repair endpoint instead of writing during `GET`.
- Session start idempotency validation rejects overlong client keys instead of
  truncating them.
- Deploy bootstrap refuses production server startup through Werkzeug and
  requires database-backed rate limiting and turn coordination in production.

## Beta Hardening

- Keep account recovery explicit. If a legacy account has no password and the
  saved account token is gone, use the legacy claim path only when identity
  details match and a password is being set.
- Keep mutating repair behavior behind explicit commands or POST endpoints.
  Avoid hidden writes in diagnostics, browser refreshes, and smoke tests.
- Keep CI drift checks active: generated API types, backend tests, frontend
  tests/build, browser smoke, bundle budget, secret scan, Python audit, and
  focused Ruff correctness lint.
- Run production bootstrap in `--check-only` mode before deployment, then start
  the app with a real Socket.IO-capable production server.

## Still Open

- Extract the remaining dialog layer out of `aidm_frontend/src/App.tsx`:
  campaign archive/restore, session archive/restore, campaign chooser, player
  edit/delete, world manager, and create-campaign dialogs.
- Move campaign/player/session hard-delete and archive orchestration into
  service-layer lifecycle modules with focused data-integrity tests.
- Add modal accessibility regression checks for focus placement, Escape close,
  focus trapping, danger confirmation, and horizontal overflow.
- Choose the hosted observability provider and alert owner for closed beta.
- Decide the production Socket.IO worker model, including sticky sessions or a
  shared message queue if multiple workers are used.
- Move hosted account auth toward secure HTTP-only cookies when the deployment
  threat model requires it.

## Not Now

- Do not replace the backend-owned TypeScript contract with OpenAPI yet. The
  current contract generator is low-friction; the immediate win is drift
  checking and response tests.
- Do not add more gameplay surface before the security/runtime/docs hardening
  items above are boring.
