"""Codex CLI runtime discovery helpers."""

from __future__ import annotations

import os
from pathlib import Path
import shutil


DEFAULT_CODEX_APP_EXECUTABLES: tuple[Path, ...] = (
    Path('/Applications/Codex.app/Contents/Resources/codex'),
    Path.home() / 'Applications/Codex.app/Contents/Resources/codex',
)


def resolve_codex_executable(executable: str | None = None) -> str | None:
    candidate = str(executable or '').strip() or 'codex'
    if os.path.sep in candidate:
        path = Path(candidate).expanduser()
        return str(path) if path.is_file() else None

    resolved = shutil.which(candidate)
    if resolved:
        return resolved

    if candidate == 'codex':
        for app_executable in DEFAULT_CODEX_APP_EXECUTABLES:
            if app_executable.is_file():
                return str(app_executable)

    return None


def codex_executable_configured(executable: str | None = None) -> bool:
    return resolve_codex_executable(executable) is not None
