# JSON Storage Policy

## Current Decision

AIDM keeps structured payload columns as JSON-encoded `Text` while SQLite remains a supported local/runtime database. This applies to fields such as player `stats`, `inventory`, `character_sheet`, map `map_data`, `metadata_json`, turn `rules_hint`, and session `state_snapshot`.

This is intentional rather than accidental schema debt: SQLite is the default local store, source archives should remain easy to run without a managed database, and the app already normalizes structured writes through validation helpers plus `safe_json_dumps` / `safe_json_loads`.

## Rules

- Write routes must validate structured payload shape before persisting.
- Reads must tolerate malformed legacy JSON and return safe defaults.
- New structured fields should use explicit DTO/validation helpers rather than ad hoc `json.loads`.
- Do not migrate an existing JSON-text column to native `db.JSON` unless the deployment target is known to support the same behavior across local, test, and production databases.

## Native JSON Migration Trigger

Revisit native SQLAlchemy JSON columns when AIDM has a primary production database target such as Postgres and SQLite is only a test/development adapter. At that point, prefer a migration that:

- Adds native JSON columns beside the existing text columns.
- Backfills by parsing existing text values through the same safe JSON helpers.
- Updates write/read code behind DTO helpers first.
- Removes old text columns only after export/import, session replay, and frontend DTO tests pass against both old and new data.
