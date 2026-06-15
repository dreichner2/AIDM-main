from __future__ import annotations

from datetime import timedelta
import threading
import time

from aidm_server.database import db
from aidm_server.models import SessionTurnLock
from aidm_server.time_utils import utc_now
from aidm_server.turn_coordinator import (
    ConfiguredSessionTurnCoordinator,
    DatabaseSessionTurnCoordinator,
    SessionTurnCoordinator,
)
from tests.helpers import seed_world_campaign_player_session


def test_session_turn_coordinator_discards_idle_session_lock():
    coordinator = SessionTurnCoordinator()

    with coordinator.serialized(7):
        pass

    assert coordinator.lock_count() == 1
    assert coordinator.discard_session(7) is True
    assert coordinator.lock_count() == 0


def test_session_turn_coordinator_keeps_active_session_lock():
    coordinator = SessionTurnCoordinator()

    with coordinator.serialized(7):
        assert coordinator.discard_session(7) is False
        assert coordinator.lock_count() == 1

    assert coordinator.discard_session(7) is True


def test_session_turn_coordinator_prunes_idle_locks():
    now = 1000.0
    coordinator = SessionTurnCoordinator(max_idle_seconds=10.0, clock=lambda: now)

    with coordinator.serialized(1):
        pass
    assert coordinator.lock_count() == 1

    now = 1011.0
    with coordinator.serialized(2):
        pass

    assert coordinator.lock_count() == 1


def test_database_session_turn_coordinator_serializes_across_instances(app):
    ids = seed_world_campaign_player_session(app)
    session_id = ids['session_id']
    first = DatabaseSessionTurnCoordinator(poll_interval_seconds=0.01)
    second = DatabaseSessionTurnCoordinator(poll_interval_seconds=0.01)
    entered: list[float] = []

    def contender():
        with app.app_context():
            with second.serialized(session_id) as wait_ms:
                entered.append(wait_ms)

    with app.app_context():
        with first.serialized(session_id):
            thread = threading.Thread(target=contender)
            thread.start()
            time.sleep(0.05)
            assert entered == []

        thread.join(timeout=2)
        assert not thread.is_alive()
        assert entered and entered[0] >= 40
        assert first.lock_count() == 0


def test_database_session_turn_coordinator_reclaims_expired_lock(app):
    ids = seed_world_campaign_player_session(app)
    session_id = ids['session_id']
    now = utc_now()
    with app.app_context():
        db.session.add(
            SessionTurnLock(
                session_id=session_id,
                owner_token='stale-owner',
                acquired_at=now - timedelta(minutes=20),
                updated_at=now - timedelta(minutes=20),
                expires_at=now - timedelta(minutes=1),
            )
        )
        db.session.commit()

        coordinator = DatabaseSessionTurnCoordinator(lease_seconds=30, poll_interval_seconds=0.01)
        with coordinator.serialized(session_id):
            lock = db.session.get(SessionTurnLock, session_id)
            assert lock is not None
            assert lock.owner_token != 'stale-owner'


def test_configured_turn_coordinator_uses_database_store(app):
    ids = seed_world_campaign_player_session(app)
    session_id = ids['session_id']

    with app.app_context():
        app.config['AIDM_TURN_COORDINATOR_STORE'] = 'database'
        app.config['AIDM_TURN_COORDINATOR_LOCK_TTL_SECONDS'] = 30
        app.config['AIDM_TURN_COORDINATOR_POLL_INTERVAL_MS'] = 10
        coordinator = ConfiguredSessionTurnCoordinator()

        with coordinator.serialized(session_id):
            assert coordinator.lock_count() == 1

        assert coordinator.lock_count() == 0


def test_configured_turn_coordinator_allows_nested_same_session_lock(app):
    ids = seed_world_campaign_player_session(app)
    session_id = ids['session_id']

    with app.app_context():
        coordinator = ConfiguredSessionTurnCoordinator()

        with coordinator.serialized(session_id) as outer_wait_ms:
            with coordinator.serialized(session_id) as inner_wait_ms:
                assert outer_wait_ms >= 0
                assert inner_wait_ms == 0.0
                assert coordinator.lock_count() == 1

        assert coordinator.discard_session(session_id) is True
