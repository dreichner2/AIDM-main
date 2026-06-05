from __future__ import annotations

from aidm_server.env_loader import load_runtime_env
from aidm_server.main import build_runtime


load_runtime_env()
app, socketio = build_runtime()
