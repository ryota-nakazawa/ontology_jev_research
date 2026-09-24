from dataclasses import replace

import test_state
from test_continuous_skills import ground

from typesafe_mario.continuous_skills import SkillControl, catalog
from typesafe_mario.state import EnemyObservation, MarioStateParser


def test_flag_is_observed_but_not_a_threat():
    ram = bytearray(0x800)
    ram[0xF] = 1
    ram[0x16] = 0x31
    ram[0x87] = 140
    ram[0xCF] = 80
    s = MarioStateParser().parse(test_state.MarioStateParserTests().base_info(), ram)
    assert not s.enemies
    assert s.world_objects[0].kind == 'flagpole'
    assert s.to_state()['world_knowledge']['observed_objects'][0]['role'] == 'goal'


def test_powerup_special_slot_decodes_type_without_inventing_unseen_items():
    ram = bytearray(0x800)
    ram[0x14] = 1
    ram[0x1B] = 0x2E
    ram[0x8C] = 124
    ram[0xD4] = 80
    ram[0x39] = 0
    parser = MarioStateParser()
    s = parser.parse(test_state.MarioStateParserTests().base_info(), ram)
    assert s.world_objects[0].kind == 'mushroom'
    assert not s.enemies
    ram[0x14] = 0
    assert not parser.parse(test_state.MarioStateParserTests().base_info(), ram).world_objects


def item_scene():
    return replace(ground(), world_objects=(EnemyObservation(5, 0x2E, 'mushroom', 24, 8),))


def test_collect_requires_observed_item_and_clear_route():
    assert 'CollectPowerup' not in {c.name for c in catalog(ground())}
    s = item_scene()
    assert 'CollectPowerup' in {c.name for c in catalog(s)}
    enemy = EnemyObservation(0, 6, 'goomba', 60, 8)
    assert 'CollectPowerup' not in {c.name for c in catalog(replace(s, enemies=(enemy,)))}
    assert 'CollectPowerup' not in {c.name for c in catalog(replace(s, local_grid=()))}


def test_collection_success_requires_status_change_not_disappearance():
    s = item_scene()
    spec = next(c for c in catalog(s) if c.name == 'CollectPowerup')
    c = SkillControl(spec, s)
    assert c.next_action(s) is not None
    assert c.next_action(replace(s, world_objects=())) is None
    assert c.reason == 'item_lost_unconfirmed'
    c = SkillControl(spec, s)
    assert c.next_action(replace(s, status='tall', world_objects=())) is None
    assert c.status == 'success'


def test_unknown_actor_is_kept_as_potential_hazard():
    ram = bytearray(0x800)
    ram[0xF], ram[0x16], ram[0x87], ram[0xCF] = 1, 0x70, 140, 80
    s = MarioStateParser().parse(test_state.MarioStateParserTests().base_info(), ram)
    assert len(s.enemies) == 1
    assert s.to_state()['world_knowledge']['observed_objects'][0]['role'] == 'unknown'


def test_collection_yields_to_new_enemy_and_rejects_changed_target():
    from typesafe_mario.continuous_skills import response_valid
    s = item_scene()
    spec = next(c for c in catalog(s) if c.name == 'CollectPowerup')
    c = SkillControl(spec, s)
    unsafe = replace(s, enemies=(EnemyObservation(0, 6, 'goomba', 32, 8),))
    assert c.next_action(unsafe) is None
    assert c.reason == 'collection_route_changed'
    different = replace(s, world_objects=(replace(s.world_objects[0], slot=4),))
    assert not response_valid(spec, different, 0)


def test_item_is_not_collected_over_gap_or_down_step():
    s = item_scene()
    rows = list(s.local_grid)
    rows[-1] = rows[-1][:4] + '.' + rows[-1][5:]
    assert 'CollectPowerup' not in {c.name for c in catalog(replace(s, local_grid=tuple(rows)))}


def test_rule_metadata_does_not_claim_article_is_verified():
    from typesafe_mario.knowledge import RULES, describe
    rule = next(r for r in RULES if r['id'] == 'shell_reflects')
    assert not rule['control_enabled']
    assert rule['source'].startswith('https://note.com/')
    assert not describe(ground())['observed_objects']
