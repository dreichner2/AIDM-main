from __future__ import annotations

import os

if os.getenv('AIDM_SOCKETIO_ASYNC_MODE', '').strip().lower() == 'eventlet':
    import eventlet

    eventlet.monkey_patch()

from aidm_server.env_loader import load_runtime_env
from aidm_server.main import build_runtime


load_runtime_env()
app, socketio = build_runtime()
