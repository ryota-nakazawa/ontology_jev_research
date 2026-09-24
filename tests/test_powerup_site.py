from dataclasses import replace

from test_continuous_skills import ground

from typesafe_mario.continuous_skills import SkillControl, catalog
from typesafe_mario.powerup_site import SITE, eligible, observe_site
from typesafe_mario.state import EnemyObservation, MarioStateParser


def scene():
    return replace(ground(), x=332, powerup_sites=(dict(SITE, observation='unused'),))


def test_registered_location_requires_live_unused_evidence():
    ram = bytearray(0x800)
    ram[0x500+208+7*16+5] = 0xC1
    assert observe_site(ram, 320, 1, 1, 1)[0]['observation'] == 'unused'
    assert observe_site(ram, 40, 1, 1, 1)[0]['observation'] == 'unobserved'
    assert not observe_site(ram, 320, 1, 2, 1)
    ram[0x500+208+7*16+5] = 0xC4
    assert observe_site(ram, 320, 1, 1, 1)[0]['observation'] == 'used'
    assert MarioStateParser._tile_symbol(0xC1) == '?'
    assert MarioStateParser._tile_symbol(0xC4) == 'U'


def test_visit_is_optional_and_requires_safety():
    s = scene()
    assert eligible(s)
    assert {'Advance', 'VisitOpeningPowerup'} <= {c.name for c in catalog(s)}
    assert not eligible(replace(s, status='tall'))
    assert not eligible(replace(s, powerup_sites=()))
    assert not eligible(replace(s, enemies=(EnemyObservation(0, 6, 'goomba', 20, 8),)))


def test_visit_aborts_on_new_enemy_and_confirms_upgrade():
    s = scene()
    spec = next(c for c in catalog(s) if c.name == 'VisitOpeningPowerup')
    c = SkillControl(spec, s)
    assert c.next_action(replace(s, enemies=(EnemyObservation(0, 6, 'goomba', 20, 8),))) is None
    assert c.status == 'aborted'
    c = SkillControl(spec, s)
    assert c.next_action(replace(s, status='tall')) is None
    assert c.reason == 'powerup_status_confirmed'


def test_visit_does_not_repeat_forever_without_item():
    s = scene()
    c = SkillControl(next(c for c in catalog(s) if c.name == 'VisitOpeningPowerup'), s)
    for _ in range(482):
        c.next_action(s)
    assert c.status == 'failure'
    assert c.reason == 'powerup_attempt_timeout'
