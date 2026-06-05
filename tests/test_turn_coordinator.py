from __future__ import annotations

from aidm_server.turn_coordinator import SessionTurnCoordinator


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
