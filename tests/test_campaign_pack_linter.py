from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from aidm_server.creatures.schemas import normalize_creature_definition
from aidm_server.services.campaign_pack_linter import lint_campaign_pack_file, lint_campaign_pack_manifest


TEST_REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = TEST_REPO_ROOT / 'docs' / 'examples'


def _valid_pack() -> dict:
    return {
        'packId': 'lint_pack',
        'title': 'Lint Pack',
        'locations': [{'id': 'start', 'name': 'Start'}],
        'startingState': {'locationId': 'start'},
        'checkpoints': [
            {
                'id': 'cp_start',
                'title': 'Start',
                'terminal': True,
                'playerTitle': 'Start',
            }
        ],
    }


def test_campaign_pack_linter_reports_hidden_record_visible_at_start(app):
    pack = {
        **_valid_pack(),
        'clues': [
            {
                'id': 'clue_secret',
                'title': 'Secret Clue',
                'visibleAtStart': True,
                'hiddenToPlayers': True,
            }
        ],
    }

    with app.app_context():
        result = lint_campaign_pack_manifest(pack, workspace_id='owner')

    assert result['ok'] is False
    assert any(issue['code'] == 'hidden_record_visible_at_start' for issue in result['issues'])


def test_campaign_pack_linter_reports_graph_and_dependency_warnings(app):
    pack = {
        **_valid_pack(),
        'checkpoints': [
            {'id': 'cp_start', 'title': 'Start', 'next_checkpoint_ids': ['cp_end'], 'encounter_ids': ['enc_bandits']},
            {'id': 'cp_end', 'title': 'End', 'terminal': True},
            {'id': 'cp_orphan', 'title': 'Orphan', 'terminal': True},
        ],
        'encounters': [
            {'id': 'enc_bandits', 'title': 'Bandit Toll', 'checkpointIds': ['cp_start'], 'enemyIds': ['enemy_bandit']},
            {'id': 'enc_unlinked', 'title': 'Unplaced Trouble', 'enemyGroups': [{'enemyId': 'enemy_bandit', 'count': 2}]},
        ],
        'npcs': [{'id': 'npc_guide', 'name': 'Guide', 'visibleAtStart': True}],
        'lore': [{'id': 'lore_secret', 'title': 'Secret Lore', 'visibility': 'hidden'}],
        'dependencies': [{'packId': 'shared_rules', 'versionRange': '^1'}],
    }

    with app.app_context():
        result = lint_campaign_pack_manifest(pack, workspace_id='owner')

    assert result['ok'] is True
    assert result['graph']['reachable'] == ['cp_end', 'cp_start']
    assert any(issue['code'] == 'unreachable_checkpoint' for issue in result['issues'])
    assert any(issue['code'] == 'pack_dependencies_require_library_resolution' for issue in result['issues'])
    report = result['authoring_report']
    assert report['starting']['locationId'] == 'start'
    assert report['checkpoints']['total'] == 3
    assert report['checkpoints']['reachable'] == 2
    assert report['checkpoints']['unreachableIds'] == ['cp_orphan']
    assert report['checkpoints']['items'][0]['encounterIds'] == ['enc_bandits']
    assert report['encounters']['total'] == 2
    assert report['encounters']['linkedToCheckpoint'] == 1
    assert report['encounters']['unlinkedIds'] == ['enc_unlinked']
    assert report['visibility']['visibleAtStart']['npcs'] == ['npc_guide']
    assert report['visibility']['hiddenToPlayers']['lore'] == ['lore_secret']


def test_campaign_pack_linter_cli_prints_json(tmp_path, app):
    pack_path = tmp_path / 'lint-pack.json'
    pack_path.write_text(json.dumps(_valid_pack()), encoding='utf-8')

    result = subprocess.run(
        [
            sys.executable,
            'scripts/aidm_pack.py',
            'lint',
            str(pack_path),
            '--json',
        ],
        check=False,
        cwd=str(TEST_REPO_ROOT),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload['ok'] is True
    assert payload['summary']['packId'] == 'lint_pack'


def test_campaign_pack_report_cli_prints_authoring_report_json(tmp_path, app):
    pack_path = tmp_path / 'lint-pack.json'
    pack_path.write_text(json.dumps(_valid_pack()), encoding='utf-8')

    result = subprocess.run(
        [
            sys.executable,
            'scripts/aidm_pack.py',
            'report',
            str(pack_path),
            '--json',
        ],
        check=False,
        cwd=str(TEST_REPO_ROOT),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload['starting']['locationId'] == 'start'
    assert payload['checkpoints']['reachable'] == 1
    assert payload['collections'][0] == {
        'collection': 'locations',
        'count': 1,
        'visibleAtStartCount': 0,
        'hiddenToPlayersCount': 0,
        'visibleAtStartIds': [],
        'hiddenToPlayersIds': [],
    }


def test_example_campaign_packs_lint_and_have_reachable_checkpoints(app):
    example_paths = sorted(EXAMPLES_DIR.glob('*.json'))
    assert example_paths

    results = {}
    with app.app_context():
        for pack_path in example_paths:
            results[pack_path.name] = lint_campaign_pack_file(pack_path, workspace_id='owner')

    blocking_issues = {
        name: result['issues']
        for name, result in results.items()
        if not result['ok']
    }
    assert blocking_issues == {}

    unreachable = {}
    for name, result in results.items():
        graph = result['graph']
        missing = sorted(set(graph['nodes']) - set(graph['reachable']))
        if missing:
            unreachable[name] = missing
    assert unreachable == {}


def test_road_of_unremembered_kings_example_has_clean_authoring_surface(app):
    pack_path = EXAMPLES_DIR / 'the_road_of_unremembered_kings_campaign.json'
    pack = json.loads(pack_path.read_text(encoding='utf-8'))

    with app.app_context():
        result = lint_campaign_pack_file(pack_path, workspace_id='owner')

    assert result['ok'] is True
    assert result['issues'] == []
    assert result['summary']['packId'] == 'original_fantasy.road_of_unremembered_kings'
    assert result['summary']['counts']['checkpoints'] == 7
    assert result['summary']['counts']['encounters'] == 6
    assert result['preview']['preview']['starting_location_id'] == 'loc_lantern_post_inn'
    assert result['preview']['preview']['starting_quest_id'] == 'quest_road_unremembered_kings'

    opening_encounter = next(encounter for encounter in pack['encounters'] if encounter['id'] == 'enc_empty_caravan_pressure')
    assert opening_encounter['enemyGroups'] == [
        {
            'enemyId': 'enemy_ashmarked_cutthroats',
            'count': 2,
            'role': 'opening_theft_cell',
        }
    ]

    enemies = pack['enemies']
    assert len(enemies) == 6
    for enemy in enemies:
        normalized = normalize_creature_definition(enemy, source='campaign_pack')
        assert normalized['stats']['maxHp'] > 10
        assert normalized['stats']['armorClass'] > 11
        assert len(normalized['abilities']) >= 3
        assert normalized['abilities'][0]['name'] != 'Strike'
        assert normalized['behavior']['tactics'] != ['Use the strongest available attack against the best target.']
        assert normalized['balance']['reviewed'] is True

    cinder_scribe = next(enemy for enemy in enemies if enemy['id'] == 'enemy_cinder_scribe')
    normalized_scribe = normalize_creature_definition(cinder_scribe, source='campaign_pack')
    assert normalized_scribe['challengeTier'] == 'boss'
    assert normalized_scribe['behavior']['primaryGoal'] == 'complete_ritual'
