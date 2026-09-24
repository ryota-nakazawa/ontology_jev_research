from dataclasses import replace

from test_continuous_skills import ground

from typesafe_mario.actions import Action
from typesafe_mario.landing import LandingSafety
from typesafe_mario.state import EnemyObservation


def test_dismount_begins_before_dropping_towards_enemy():
    s = replace(ground(), local_grid=('...........', '..M........', '...........',
                                     '###........', '###........', '###########'),
                enemies=(EnemyObservation(0, 6, 'goomba', 45, 40, -2),))
    guard = LandingSafety()
    guard.filter(s, Action.RIGHT)
    assert guard.active
    assert guard.filter(s, Action.RIGHT) == Action.RIGHT_RUN_JUMP


def test_pit_does_not_trigger_unplanned_dismount():
    s = replace(ground(), local_grid=('...........', '..M........', '...........', '###..######'),
                enemies=(EnemyObservation(0, 6, 'goomba', 45, 40, -2),))
    guard = LandingSafety()
    assert guard.filter(s, Action.RIGHT) == Action.RIGHT
    assert not guard.active


def test_landing_prediction_includes_second_and_rear_enemies():
    from typesafe_mario.landing import landing_risks
    s = replace(ground(), grounded=False, dx=2, dy=-2,
                local_grid=('...........', '..M........', '...........', '...........', '###########'),
                enemies=(EnemyObservation(0, 6, 'goomba', -20, 24, 1),
                         EnemyObservation(1, 6, 'goomba', 30, 24, -2)))
    result = landing_risks(s, Action.RIGHT)
    assert {e['slot'] for e in result['enemies']} == {0, 1}


def test_air_adjustment_requires_known_landing_surface():
    from typesafe_mario.landing import same_landing_surface
    s = replace(ground(), grounded=False,
                local_grid=('...........', '..M........', '...........', '...........', '###..######'))
    assert not same_landing_surface(s, 32)


def test_no_air_adjustment_while_rising_or_without_geometry():
    guard = LandingSafety()
    assert guard.filter(replace(ground(), grounded=False, dy=4), Action.RIGHT_JUMP) == Action.RIGHT_JUMP
    assert guard.filter(replace(ground(), grounded=False, local_grid=()), Action.RIGHT) == Action.RIGHT
