from __future__ import annotations

from pathlib import Path
import sqlite3
import stat

import pytest

from scripts import backup_restore_drill


def _create_sqlite_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE worlds (world_id INTEGER PRIMARY KEY, name TEXT NOT NULL)')
        conn.execute('INSERT INTO worlds (name) VALUES (?)', ('Drill World',))
        conn.commit()


def test_backup_restore_drill_creates_verified_restored_copy(tmp_path: Path):
    source_path = tmp_path / 'aidm.db'
    output_dir = tmp_path / 'drill-output'
    _create_sqlite_db(source_path)

    result = backup_restore_drill.run_backup_restore_drill(
        database_uri=f'sqlite:///{source_path}',
        output_dir=output_dir,
    )

    assert result.source_path == source_path.resolve()
    assert result.backup_path.exists()
    assert result.restored_path.exists()
    assert result.integrity_check == 'ok'
    assert result.table_count == 1
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(result.backup_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(result.restored_path.stat().st_mode) == 0o600

    with sqlite3.connect(result.restored_path) as conn:
        row = conn.execute('SELECT name FROM worlds').fetchone()
    assert row == ('Drill World',)


def test_backup_restore_drill_rejects_in_memory_database():
    with pytest.raises(backup_restore_drill.BackupRestoreDrillError, match='file-backed SQLite'):
        backup_restore_drill.sqlite_path_from_database_uri('sqlite:///:memory:')


def test_backup_restore_drill_rejects_non_sqlite_database():
    with pytest.raises(backup_restore_drill.BackupRestoreDrillError, match='file-backed SQLite'):
        backup_restore_drill.sqlite_path_from_database_uri('postgresql://aidm.example/db')


def test_backup_restore_drill_requires_application_tables_by_default(tmp_path: Path):
    source_path = tmp_path / 'empty.db'
    source_path.touch()

    with pytest.raises(backup_restore_drill.BackupRestoreDrillError, match='no application tables'):
        backup_restore_drill.run_backup_restore_drill(
            database_uri=f'sqlite:///{source_path}',
            output_dir=tmp_path / 'drill-output',
        )


def test_backup_restore_drill_cli_reports_success(tmp_path: Path, capsys):
    source_path = tmp_path / 'aidm.db'
    _create_sqlite_db(source_path)

    returncode = backup_restore_drill.main(
        [
            '--database-uri',
            f'sqlite:///{source_path}',
            '--output-dir',
            str(tmp_path / 'drill-output'),
        ]
    )

    captured = capsys.readouterr()
    assert returncode == 0
    assert '[backup-restore-drill] Backup/restore drill passed.' in captured.out
