# AIDM Architecture

This document is the current high-level map. It is intentionally shorter than
the archived review notes and should stay focused on where behavior lives.

## Runtime

- `aidm_server/main.py` builds the Flask app, middleware stack, auth/workspace
  context, CORS, rate limiter, telemetry, schema guardrails, and Socket.IO
  runtime.
- `aidm_server/config.py` owns environment parsing. Production rejects an
  ephemeral `FLASK_SECRET_KEY` and rejects `AIDM_AUTO_CREATE_SCHEMA=true`.
- `aidm_server/deploy_bootstrap.py` is a preflight runner. It runs migrations,
  validates config and endpoints, checks Socket.IO auth behavior, hardens local
  file permissions, and may serve local/test runs. Production must use
  `--check-only` and then a production Socket.IO server.

## Auth And Workspaces

- Account sessions use bearer account tokens stored as hashes server-side.
- Workspace access can come from configured workspace tokens or saved account
  workspace membership.
- Existing accounts with no password hash are legacy accounts. They cannot log
  in by username alone; they need a valid saved account token or an explicit
  legacy claim that sets a password immediately.
- Player visibility flows through workspace and account helpers rather than
  route-local ad hoc filters.

## Gameplay State

- Player turns enter through Socket.IO contracts, then flow through turn
  coordination, persistence, DM generation, state extraction/validation,
  application, and canon queueing.
- `aidm_server/game_state/` owns structured state changes, validation, action
  extraction, and application.
- `aidm_server/turn_events.py` is the durable event spine for user-visible and
  system-visible session events.
- `aidm_server/canon_jobs.py` owns queued/running/terminal canon extraction
  work and projection refresh.

## REST Boundaries

- GET endpoints should be read-only. Legacy repair behavior belongs in explicit
  POST endpoints, CLI tools, migrations, or local-only startup repair.
- Player starting inventory/spell repair is exposed as:
  `POST /api/players/<player_id>/repair-starting-loadout`.
- Session start idempotency accepts `client_session_id` or `idempotency_key`
  up to 80 supported characters and rejects longer values rather than
  truncating.

## Frontend

- `aidm_frontend/src/App.tsx` still orchestrates broad runtime state and some
  dialogs. Continue extracting dialog components until App is mostly shell,
  selected campaign/session/player state, socket lifecycle, and layout.
- API DTO types are generated from `aidm_server/api_type_contract.py` into
  `aidm_frontend/src/apiContract.generated.ts`. CI verifies this file is fresh.
- CSS is split by surface under `aidm_frontend/src/styles/`; responsive changes
  should preserve desktop behavior unless the task explicitly targets desktop.

## Data Integrity

- Session archive/restore/delete behavior already has a service module in
  `aidm_server/services/session_lifecycle.py`.
- Campaign and player lifecycle behavior should follow that service-layer
  pattern before more route-level deletion logic is added.
- Destructive flows need tests that verify archive preservation, restore scope,
  force-delete cleanup, and turn-history readability after player deletion.
