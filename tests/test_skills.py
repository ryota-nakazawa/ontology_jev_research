from dataclasses import replace

from test_contact import snapshot

from typesafe_mario.actions import Action
from typesafe_mario.skills import ClearObstacle, clear_obstacle_candidate


def wall_scene():
    rows = ['...........'] * 3 + ['...PP......'] * 3 + ['###########'] * 7
    rows[4] = '..MPP......'
    return snapshot(x=594, y=79, dx=0, dy=0, grounded=True, airborne=False,
                    local_grid=tuple(rows), frames_since_previous=1)


def test_skill_requires_known_ground_and_rear_support():
    s = wall_scene()
    assert clear_obstacle_candidate(s) is not None
    assert clear_obstacle_candidate(replace(s, grounded=False)) is None
    assert clear_obstacle_candidate(replace(s, local_grid=())) is None
    rows = list(s.local_grid)
    rows[6] = '..#########'
    assert clear_obstacle_candidate(replace(s, local_grid=tuple(rows))) is None


def test_success_requires_observed_landing_not_just_crossing_x():
    s = wall_scene()
    plan = clear_obstacle_candidate(s)
    control = ClearObstacle(plan, s)
    control.phase = 'jump'
    flying = replace(s, x=plan.landing_min_x + 2, grounded=False, y=130)
    control.next_action(flying)
    assert control.status != 'success'
    control.airborne_seen = True
    control.next_action(replace(flying, grounded=True, y=79))
    assert control.status == 'success'


def test_death_and_timeout_have_explicit_results():
    s = wall_scene()
    c = ClearObstacle(clear_obstacle_candidate(s), s)
    assert c.next_action(replace(s, dead=True)) is None
    assert c.reason == 'death'
    c = ClearObstacle(clear_obstacle_candidate(s), s)
    for _ in range(181):
        a = c.next_action(s)
        assert a is None or a in set(Action) - {Action.BACK_UP_AND_JUMP}
    assert c.status == 'failure'
    assert c.reason == 'timeout'


def test_four_tile_wall_is_not_claimed_as_validated():
    s = wall_scene()
    rows = list(s.local_grid)
    rows[2] = '...PP......'
    assert clear_obstacle_candidate(replace(s, local_grid=tuple(rows))) is None


def test_monitored_skill_cannot_be_expanded_to_a_blind_script():
    import pytest

    from typesafe_mario.actions import expand
    with pytest.raises(ValueError):
        expand(Action.CLEAR_OBSTACLE, 8)


def test_enemy_approach_aborts_instead_of_silently_finishing():
    from typesafe_mario.state import EnemyObservation
    s = wall_scene()
    c = ClearObstacle(clear_obstacle_candidate(s), s)
    danger = replace(s, enemies=(EnemyObservation(0, 6, 'goomba', 16, 8),))
    assert c.next_action(danger) is None
    assert c.reason == 'enemy_entered_corridor'


def test_unvalidated_fast_approach_is_not_offered():
    assert clear_obstacle_candidate(replace(wall_scene(), dx=3)) is None


def test_skill_is_only_offered_to_jev_when_preconditions_hold():
    from types import SimpleNamespace

    from typesafe_mario.policy import TypeSafePolicy
    class Client:
        def __init__(self):
            self.requests = []
        def system_one(self, **request):
            self.requests.append(request)
            return SimpleNamespace(answers={
                'next_action': SimpleNamespace(choice='right', confidence=1, probabilities={'right': 1}),
                'jump_needed': SimpleNamespace(noul=0),
                'danger': SimpleNamespace(score=0),
            })
    client = Client()
    policy = TypeSafePolicy(client=client)
    policy.choose(wall_scene(), tuple(Action))
    assert client.requests[-1]['state']['available_skills'][0]['skill'] == 'ClearObstacle'
    assert 'clear_obstacle' in client.requests[-1]['questions']['next_action'].criteria
    policy.choose(replace(wall_scene(), grounded=False), tuple(Action))
    assert client.requests[-1]['state']['available_skills'] == []
    assert 'clear_obstacle' not in client.requests[-1]['questions']['next_action'].criteria


def test_one_pixel_wall_correction_does_not_prevent_takeoff():
    s = replace(wall_scene(), x=435)
    c = ClearObstacle(clear_obstacle_candidate(s), s)
    c.next_action(s)
    at_wall = replace(s, x=434, dx=0)
    actions = [c.next_action(at_wall) for _ in range(4)]
    assert Action.RIGHT_RUN_JUMP in actions


def test_takeoff_tolerance_does_not_allow_far_or_airborne_start():
    s = wall_scene()
    for changed in (replace(s, x=s.x - 8), replace(s, grounded=False)):
        c = ClearObstacle(clear_obstacle_candidate(s), s)
        for _ in range(4):
            assert c.next_action(changed) is not Action.RIGHT_RUN_JUMP
