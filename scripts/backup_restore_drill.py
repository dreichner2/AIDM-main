from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Iterable

from sqlalchemy.engine import make_url


REPO_ROOT = Path(__file__).resolve().parents[1]


class BackupRestoreDrillError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupRestoreDrillResult:
    source_path: Path
    backup_path: Path
    restored_path: Path
    integrity_check: str
    table_count: int


def _default_database_uri() -> str:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from aidm_server.config import default_sqlite_uri

    return default_sqlite_uri()


def _load_runtime_env() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from aidm_server.env_loader import load_runtime_env

    load_runtime_env(REPO_ROOT)


def resolve_database_uri(database_uri: str | None) -> str:
    return str(database_uri or os.getenv('AIDM_DATABASE_URI') or _default_database_uri()).strip()


def sqlite_path_from_database_uri(database_uri: str, *, base_dir: Path = REPO_ROOT) -> Path:
    try:
        url = make_url(database_uri)
    except Exception as exc:
        raise BackupRestoreDrillError(f'Invalid database URI: {exc}') from exc

    if not url.drivername.startswith('sqlite'):
        raise BackupRestoreDrillError('Backup/restore drill currently supports file-backed SQLite databases only.')

    database = str(url.database or '').strip()
    if not database or database == ':memory:':
        raise BackupRestoreDrillError('Backup/restore drill requires a file-backed SQLite database, not :memory:.')

    path = Path(database).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)


def _verify_sqlite_database(path: Path, *, require_tables: bool) -> tuple[str, int]:
    try:
        with _connect_readonly(path) as conn:
            integrity_check = str(conn.execute('PRAGMA integrity_check').fetchone()[0])
            table_count = int(
                conn.execute(
                    """
                    SELECT count(*)
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name NOT LIKE 'sqlite_%'
                    """
                ).fetchone()[0]
            )
    except sqlite3.Error as exc:
        raise BackupRestoreDrillError(f'Could not verify SQLite database {path}: {exc}') from exc

    if integrity_check.lower() != 'ok':
        raise BackupRestoreDrillError(f'SQLite integrity_check failed for {path}: {integrity_check}')
    if require_tables and table_count < 1:
        raise BackupRestoreDrillError(f'SQLite database {path} has no application tables to restore-check.')
    return integrity_check, table_count


def run_backup_restore_drill(
    *,
    database_uri: str | None = None,
    output_dir: Path | None = None,
    require_tables: bool = True,
) -> BackupRestoreDrillResult:
    resolved_uri = resolve_database_uri(database_uri)
    source_path = sqlite_path_from_database_uri(resolved_uri)
    if not source_path.exists():
        raise BackupRestoreDrillError(f'SQLite database does not exist: {source_path}')
    if not source_path.is_file():
        raise BackupRestoreDrillError(f'SQLite database path is not a file: {source_path}')

    _verify_sqlite_database(source_path, require_tables=require_tables)

    drill_dir = (output_dir or (REPO_ROOT / 'tmp' / 'backup_restore_drills')).expanduser().resolve()
    drill_dir.mkdir(parents=True, exist_ok=True)
    drill_dir.chmod(0o700)

    timestamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    backup_path = drill_dir / f'{source_path.stem}.backup-{timestamp}{source_path.suffix or ".db"}'
    restored_path = drill_dir / f'{source_path.stem}.restore-drill-{timestamp}{source_path.suffix or ".db"}'

    try:
        with _connect_readonly(source_path) as source_conn, sqlite3.connect(backup_path) as backup_conn:
            source_conn.backup(backup_conn)
            backup_conn.commit()
    except sqlite3.Error as exc:
        raise BackupRestoreDrillError(f'Could not create SQLite backup from {source_path}: {exc}') from exc

    shutil.copy2(backup_path, restored_path)
    backup_path.chmod(0o600)
    restored_path.chmod(0o600)

    integrity_check, table_count = _verify_sqlite_database(restored_path, require_tables=require_tables)
    return BackupRestoreDrillResult(
        source_path=source_path,
        backup_path=backup_path,
        restored_path=restored_path,
        integrity_check=integrity_check,
        table_count=table_count,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Run a non-destructive SQLite backup/restore drill.')
    parser.add_argument(
        '--database-uri',
        help='Database URI to drill. Defaults to AIDM_DATABASE_URI or the local ~/.aidm SQLite default.',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=REPO_ROOT / 'tmp' / 'backup_restore_drills',
        help='Directory for the backup and restored verification copy.',
    )
    parser.add_argument(
        '--allow-empty-schema',
        action='store_true',
        help='Allow a database with zero application tables. Intended only for low-level script tests.',
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.database_uri:
        _load_runtime_env()
    try:
        result = run_backup_restore_drill(
            database_uri=args.database_uri,
            output_dir=args.output_dir,
            require_tables=not args.allow_empty_schema,
        )
    except BackupRestoreDrillError as exc:
        print(f'[backup-restore-drill][error] {exc}')
        return 1

    print('[backup-restore-drill] Backup/restore drill passed.')
    print(f'[backup-restore-drill] Source: {result.source_path}')
    print(f'[backup-restore-drill] Backup: {result.backup_path}')
    print(f'[backup-restore-drill] Restored copy: {result.restored_path}')
    print(f'[backup-restore-drill] integrity_check={result.integrity_check} tables={result.table_count}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
