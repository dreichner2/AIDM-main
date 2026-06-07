from aidm_server.socket_state import SocketState


def test_socket_state_tracks_player_until_last_socket_leaves():
    state = SocketState()
    player = {'id': 7, 'character_name': 'Ember', 'name': 'Danny'}

    assert state.track_active_player(3, player, 'sid-a') is True
    assert state.track_active_player(3, player, 'sid-b') is False
    assert state.active_player_payloads(3) == [player]

    assert state.release_active_player(3, 7, 'sid-a') is False
    assert state.active_player_payloads(3) == [player]

    assert state.release_active_player(3, 7, 'sid-b') is True
    assert state.active_player_payloads(3) == []
