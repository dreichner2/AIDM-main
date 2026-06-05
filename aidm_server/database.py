from __future__ import annotations

import os
import logging
import pathlib
import stat

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from aidm_server.logging_context import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


convention = {
    'ix': 'ix_%(column_0_label)s',
    'uq': 'uq_%(table_name)s_%(column_0_name)s',
    'ck': 'ck_%(table_name)s_%(constraint_name)s',
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
    'pk': 'pk_%(table_name)s',
}

metadata = MetaData(naming_convention=convention)
db = SQLAlchemy(metadata=metadata)
migrate = Migrate()


def _resolve_sqlite_uri(database_uri: str, root_path: str) -> str:
    if not database_uri.startswith('sqlite:///'):
        return database_uri

    relative_path = database_uri.replace('sqlite:///', '', 1)
    if relative_path == ':memory:' or relative_path.startswith(':memory:?'):
        return database_uri
    if os.path.isabs(relative_path):
        os.makedirs(os.path.dirname(relative_path), exist_ok=True)
        return database_uri

    absolute_path = os.path.join(root_path, relative_path)
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    return f'sqlite:///{absolute_path}'


def sqlite_database_path(database_uri: str, root_path: str | os.PathLike | None = None) -> pathlib.Path | None:
    try:
        url = make_url(database_uri)
    except Exception:
        return None

    if not url.drivername.startswith('sqlite'):
        return None
    if not url.database or url.database == ':memory:':
        return None

    path = pathlib.Path(url.database)
    if not path.is_absolute() and root_path is not None:
        path = pathlib.Path(root_path) / path
    return path


def _chmod_private(path: pathlib.Path, mode: int) -> bool:
    if not path.exists():
        return False
    current_mode = stat.S_IMODE(path.stat().st_mode)
    if current_mode != mode:
        path.chmod(mode)
        return True
    return False


def harden_sqlite_permissions(database_uri: str, root_path: str | os.PathLike | None = None) -> list[str]:
    database_path = sqlite_database_path(database_uri, root_path)
    if database_path is None:
        return []

    changed: list[str] = []
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.parent.name == 'instance' and _chmod_private(database_path.parent, 0o700):
        changed.append(str(database_path.parent))

    sqlite_files = {database_path}
    if database_path.parent.name == 'instance':
        for pattern in ('*.db', '*.sqlite', '*.sqlite3'):
            sqlite_files.update(database_path.parent.glob(pattern))

    for sqlite_file in sorted(sqlite_files):
        if sqlite_file.is_file() and _chmod_private(sqlite_file, 0o600):
            changed.append(str(sqlite_file))

    return changed


def init_db(app):
    """Initialize database and migrations for the Flask app."""
    try:
        configured_uri = app.config.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///instance/dnd_ai_dm.db')
        database_uri = _resolve_sqlite_uri(configured_uri, app.root_path)
        harden_sqlite_permissions(database_uri)

        app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'poolclass': NullPool,
            'connect_args': {
                'check_same_thread': False,
                'timeout': 30,
            },
        }
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

        db.init_app(app)
        migrate.init_app(app, db, render_as_batch=True)

        logger.info('Database initialized: %s', database_uri)
    except Exception as exc:
        logger.error('Error initializing database: %s', str(exc))
        raise


def ensure_schema(app):
    with app.app_context():
        db.create_all()
        harden_sqlite_permissions(app.config.get('SQLALCHEMY_DATABASE_URI', ''), app.root_path)


def get_engine():
    return db.engine


def get_session():
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db.engine)
    return session_factory()
