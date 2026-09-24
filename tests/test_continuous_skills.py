from dataclasses import replace

from test_contact import STANDING, snapshot
from test_skills import wall_scene

from typesafe_mario.actions import Action
from typesafe_mario.continuous_skills import SkillControl, catalog, response_valid
from typesafe_mario.state import EnemyObservation


def ground():
    return snapshot(x=100, y=79, dx=0, dy=0, grounded=True, airborne=False,
                    local_grid=STANDING, frames_since_previous=1, enemies=())


def pick(s, name):
    return next(c for c in catalog(s) if c.name == name)


def test_advance_yields_on_new_enemy_instead_of_holding_blindly():
    s = ground()
    c = SkillControl(pick(s, 'Advance'), s)
    assert c.next_action(s) == Action.RIGHT_RUN
    danger = replace(s, enemies=(EnemyObservation(0, 6, 'goomba', 40, 8),))
    assert c.next_action(danger) is None
    assert c.reason == 'hazard_requires_selection'


def test_jump_waits_for_landing_and_is_bounded():
    s = replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', 60, 8),))
    c = SkillControl(pick(s, 'JumpOverEnemy'), s)
    c.next_action(s)
    assert c.next_action(s) == Action.RIGHT_RUN_JUMP
    c.next_action(replace(s, grounded=False, y=130))
    assert c.status == 'running'
    assert c.next_action(replace(s, x=200, grounded=True)) is None
    assert c.status == 'success'


def test_old_or_inapplicable_response_is_rejected():
    s = ground()
    spec = pick(s, 'Advance')
    assert response_valid(spec, s, 0)
    assert not response_valid(spec, s, 46)
    assert not response_valid(spec, replace(s, dead=True), 1)
    assert not response_valid(pick(wall_scene(), 'ClearObstacle'), s, 1)


def test_all_offered_skills_have_a_controller_and_frame_budget():
    scenes = [ground(), wall_scene(), staircase_scene(), valley_scene(), summit_gap_scene(), replace(ground(), grounded=False),
              replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', -24, 8, 1),)),
              replace(ground(), local_grid=('...........', '...........', '.....##....', '..M..##....', '###########')),
              replace(ground(), local_grid=('...........', '...........', '..M#.......', '###########')),
              replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', 60, 8),)),
              replace(ground(), local_grid=('...........', '..M........',
                                           '...........', '###..######'))]
    assert {c.name for s in scenes for c in catalog(s)} == {
        'Advance', 'Survey', 'WaitForOpening', 'LandForward', 'ContinueJump',
        'ClimbThenCrossGap', 'EscapeValley', 'EvadeRearEnemy', 'JumpOverEnemy', 'CrossGap', 'ClimbStep', 'CrossStaircase', 'ApproachObstacle', 'ClearObstacle', 'RecoverObstacle',
    }
    for s in scenes:
        choices = catalog(s)
        assert len(choices) >= 2
        for spec in choices:
            c = SkillControl(spec, s)
            for _ in range(spec.max_frames + 2):
                a = c.next_action(s)
                assert a is None or a in {Action.NOOP, Action.RIGHT, Action.RIGHT_RUN,
                                         Action.RIGHT_JUMP, Action.RIGHT_RUN_JUMP, Action.LEFT, Action.JUMP}
            assert c.status != 'running'


def test_jev_receives_semantic_skills_not_eight_frame_actions():
    from types import SimpleNamespace

    from typesafe_mario.skill_policy import TypeSafeSkillPolicy
    class Client:
        def system_one(self, **request):
            self.request = request
            return SimpleNamespace(route='direct', answers={'skill': SimpleNamespace(
                choice='Advance', confidence=.8, probabilities={'Advance': .8, 'Survey': .2})})
    client = Client()
    policy = TypeSafeSkillPolicy(client=client)
    spec, decision = policy.choose_skill(ground(), catalog(ground()), [])
    assert spec.name == decision.skill_name == 'Advance'
    assert decision.route == 'direct'
    assert client.request['state']['world_knowledge']['version'] == 'mario-knowledge-v2'
    assert client.request['state']['knowledge_strategy_version'] == 'safe-upgrade-v1'
    assert 'right_run' not in client.request['questions']['skill'].criteria


import pytest


@pytest.mark.parametrize('interactive', [False, True])
@pytest.mark.parametrize('delay, failure, unlimited', [
    (3, False, False), (50, False, False), (3, True, False), (3, False, True),
])
def test_loop_advances_during_request_and_rejects_stale_results(tmp_path, monkeypatch, delay, failure, unlimited, interactive):
    import json

    from typesafe_mario import continuous_runner as runner
    from typesafe_mario.policy import Decision
    s = ground()
    class Env:
        ram = None
        steps = 0
        def reset(self, **kw): return None, {}
        def step(self, action):
            self.steps += 1
            return None, 0, self.steps >= 55, False, {}
        def close(self): pass
    env = Env()
    class Parser:
        def __init__(self, **kw): pass
        def parse(self, *args, **kw): return s
    class Future:
        def __init__(self): self.start = env.steps
        def done(self): return env.steps - self.start >= delay
        def result(self):
            if failure: raise RuntimeError('secret-must-not-be-logged')
            return pick(s, 'Survey' if unlimited else 'Advance'), Decision(Action.RIGHT_RUN, 1, {}, 0, skill_name='Advance')
        def cancel(self): pass
    class Executor:
        def __init__(self, **kw): pass
        def submit(self, *args): return Future()
        def shutdown(self, **kw): pass
    class Policy:
        def choose_skill(self, *args): pass
        def close(self): pass
    monkeypatch.setattr(runner, 'create_mario_env', lambda *a: env)
    monkeypatch.setattr(runner, 'MarioStateParser', Parser)
    monkeypatch.setattr(runner, 'ThreadPoolExecutor', Executor)
    class Dashboard:
        def draw(self, *args, **kw):
            return (runner.DashboardCommand.RESTART if kw['run_ended'] and env.steps >= 55
                    else runner.DashboardCommand.QUIT if kw['run_ended']
                    else runner.DashboardCommand.CONTINUE)
        def close(self): pass
    monkeypatch.setattr(runner, 'LiveDashboard', Dashboard)
    control = {} if interactive else None
    path = runner.run_continuous_episode(policy=Policy(), env_id='test', seed=1,
        max_decisions=1 if unlimited else 10, artifacts_dir=tmp_path, display='dashboard' if interactive else 'none', fps=0,
        session_control=control,
        until_game_over=unlimited)
    if interactive:
        assert control['restart'] is (not failure)
    text = path.read_text()
    rows = [json.loads(l) for l in text.splitlines()]
    assert any(r['event'] == 'controller_frame' and r['pending_request'] == 0 for r in rows)
    assert 'secret-must-not-be-logged' not in text
    assert path.with_suffix('.summary.json').exists()
    if unlimited:
        assert sum(r['event'] == 'request' for r in rows) > 1
    if failure:
        assert rows[-1]['reason'] == 'request_error'
    elif delay > 45:
        assert any(r['event'] == 'response_rejected' and r['reason'] == 'expired' for r in rows)
        assert not any(r['event'] == 'skill_started' and r['source'] == 'jev' for r in rows)
    else:
        assert any(r['event'] == 'skill_started' for r in rows)
        assert rows[-1]['total_frames'] == 55


def test_waiting_skill_yields_when_an_enemy_arrives():
    s = ground()
    c = SkillControl(pick(s, 'WaitForOpening'), s)
    danger = replace(s, enemies=(EnemyObservation(0, 6, 'goomba', 24, 8),))
    assert c.next_action(danger) is None
    assert c.reason == 'enemy_requires_selection'


def test_handoff_holds_jump_through_delayed_takeoff_and_until_landing():
    from typesafe_mario.continuous_skills import AwaitDecision
    s = replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', 48, 8),))
    handoff = AwaitDecision()
    assert handoff.next_action(s) == Action.RIGHT_RUN_JUMP
    # The emulator can still report grounded for the first frame after A.
    assert handoff.next_action(replace(s, previous_action='right_run_jump')) == Action.RIGHT_RUN_JUMP
    assert handoff.committed
    assert handoff.next_action(replace(s, grounded=False, y=100, dy=4)) == Action.RIGHT_RUN_JUMP
    handoff.next_action(replace(s, x=200, grounded=True, enemies=()))
    assert not handoff.committed


def test_enemy_below_platform_does_not_remove_all_progress_skills():
    s = replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', 16, 56),))
    assert 'Advance' in {c.name for c in catalog(s)}


def test_gap_controller_runs_up_before_jumping_and_releases_prior_jump():
    s = replace(ground(), local_grid=('...........', '..M........', '...........', '#####..####'))
    spec = pick(s, 'CrossGap')
    c = SkillControl(spec, s)
    assert c.next_action(s) == Action.RIGHT_RUN
    assert c.next_action(s) == Action.RIGHT_RUN  # standing still is not a takeoff trigger
    takeoff = replace(s, x=spec.parameters['takeoff_x'], dx=3, previous_action='right_run')
    assert c.next_action(takeoff) == Action.RIGHT_RUN_JUMP
    assert c.next_action(takeoff) == Action.RIGHT_RUN_JUMP  # delayed airborne observation


def test_gap_response_must_refer_to_same_edges():
    s = replace(ground(), local_grid=('...........', '..M........', '...........', '#####..####'))
    spec = pick(s, 'CrossGap')
    assert response_valid(spec, s, 20)
    assert not response_valid(spec, replace(s, x=s.x+16), 20)


def test_one_tile_step_has_climbing_candidate_and_requires_higher_landing():
    s = replace(ground(), local_grid=('...........', '...........', '..M#.......', '###########'))
    spec = pick(s, 'ClimbStep')
    c = SkillControl(spec, s)
    assert c.next_action(s) == Action.RIGHT_RUN
    assert c.next_action(s) == Action.RIGHT_RUN_JUMP
    c.next_action(replace(s, grounded=False, y=110))
    c.next_action(replace(s, grounded=True, x=spec.parameters['target_x'], y=79))
    assert c.status == 'failure'


def staircase_scene():
    return replace(ground(), x=2147, y=95, local_grid=(
        '...........', '...........', '...........', '.....#..#..',
        '..M.##..##.', '...###..###', '..####..###', '###########',
        '###########', '...........'))


def test_staircase_offers_continuous_traversal_instead_of_isolated_step():
    names = {c.name for c in catalog(staircase_scene())}
    assert 'CrossStaircase' in names
    assert 'ClimbStep' not in names


def test_staircase_landing_starts_next_jump_without_a_new_jev_request():
    s = staircase_scene()
    c = SkillControl(pick(s, 'CrossStaircase'), s)
    c.next_action(s)
    c.next_action(replace(s, grounded=False, x=2180, y=160))
    top = replace(s, grounded=True, x=2192, y=143, dx=2, previous_action='right_run')
    assert c.next_action(top) == Action.RIGHT_RUN
    assert c.status == 'running'
    assert c.next_action(top) == Action.RIGHT_RUN_JUMP


def test_staircase_requires_visible_far_summit():
    from typesafe_mario.continuous_skills import staircase_plan
    s = staircase_scene()
    rows = tuple(row[:8] + '...' for row in s.local_grid)
    assert staircase_plan(replace(s, local_grid=rows)) is None


def test_staircase_does_not_cross_when_climb_lands_short_of_summit():
    s = staircase_scene()
    c = SkillControl(pick(s, 'CrossStaircase'), s)
    c.next_action(s)
    c.next_action(replace(s, grounded=False, x=2160, y=120))
    assert c.next_action(replace(s, grounded=True, x=2170, y=111)) is None
    assert c.reason == 'summit_not_reached'


def test_staircase_ignores_distant_enemies_behind_but_not_nearby_enemies():
    from typesafe_mario.continuous_skills import staircase_plan
    s = staircase_scene()
    assert staircase_plan(replace(s, enemies=(EnemyObservation(0, 6, 'goomba', -134, 24),)))
    assert staircase_plan(replace(s, enemies=(EnemyObservation(0, 6, 'goomba', 30, 24),))) is None


def test_obstacle_outside_jump_range_has_an_approach_skill():
    s = replace(ground(), local_grid=('...........', '...........', '.....##....',
                                     '..M..##....', '###########'))
    spec = pick(s, 'ApproachObstacle')
    c = SkillControl(spec, s)
    assert c.next_action(s) == Action.RIGHT
    near = replace(s, x=spec.parameters['obstacle_left'] - 14, dx=0)
    assert c.next_action(near) is None
    assert c.status == 'success'


def test_obstacle_approach_aborts_when_ground_support_is_lost():
    s = replace(ground(), local_grid=('...........', '...........', '.....##....',
                                     '..M..##....', '###########'))
    c = SkillControl(pick(s, 'ApproachObstacle'), s)
    assert c.next_action(replace(s, grounded=False)) is None
    assert c.reason == 'approach_corridor_changed'


def test_rear_closing_enemy_interrupts_wait_and_runs_on_clear_ground():
    from typesafe_mario.continuous_skills import AwaitDecision
    s = replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', -32, 8, 1),))
    assert 'EvadeRearEnemy' in {c.name for c in catalog(s)}
    c = SkillControl(pick(s, 'Survey'), s)
    assert c.next_action(s) is None
    assert c.reason == 'rear_enemy_requires_selection'
    handoff = AwaitDecision()
    assert handoff.next_action(s) == Action.RIGHT_RUN
    assert handoff.committed


def test_rear_receding_enemy_does_not_trigger_evasion():
    s = replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', -32, 8, -1),))
    assert 'EvadeRearEnemy' not in {c.name for c in catalog(s)}


def test_rear_evasion_does_not_run_into_a_gap_and_holds_jump():
    from typesafe_mario.continuous_skills import AwaitDecision
    s = replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', -24, 8, 1),),
                local_grid=('...........', '..M........', '...........', '###..######'))
    handoff = AwaitDecision()
    assert handoff.next_action(s) == Action.JUMP
    assert handoff.next_action(replace(s, previous_action='jump')) == Action.JUMP


def test_rear_enemy_on_different_height_is_not_an_immediate_threat():
    s = replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', -24, 56, 1),))
    assert 'EvadeRearEnemy' not in {c.name for c in catalog(s)}


def test_rear_response_is_rejected_after_target_has_receded():
    s = replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', -24, 8, 1),))
    spec = pick(s, 'EvadeRearEnemy')
    assert not response_valid(spec, replace(s, enemies=()), 5)


def test_rear_evasion_can_move_onto_a_low_obstacle_after_gaining_height():
    from typesafe_mario.continuous_skills import AwaitDecision
    s = replace(ground(), enemies=(EnemyObservation(0, 6, 'goomba', -24, 8, 1),),
                local_grid=('...........', '...##......', '..M##......', '###########'))
    handoff = AwaitDecision()
    assert handoff.next_action(s) == Action.JUMP
    assert handoff.next_action(replace(s, grounded=False, y=s.y+45)) == Action.RIGHT_JUMP


def valley_scene():
    return replace(ground(), x=2226, y=79, local_grid=(
        '...........', '...........', '#..#.......', '#..##......', '#.M###.....',
        '#..####....', '###########', '###########', '...........'))


def test_valley_escape_requires_observed_rear_floor():
    s = valley_scene()
    spec = pick(s, 'EscapeValley')
    c = SkillControl(spec, s)
    assert c.next_action(s) == Action.LEFT
    assert c.next_action(replace(s, x=spec.parameters['retreat_x'], dx=-1)) == Action.RIGHT_RUN
    assert c.next_action(replace(s, x=spec.parameters['takeoff_x'], dx=2)) == Action.RIGHT_RUN_JUMP
    missing = tuple(row[:1]+'.'+row[2:] for row in s.local_grid)
    assert 'EscapeValley' not in {c.name for c in catalog(replace(s, local_grid=missing))}


def test_approach_can_reach_step_with_a_distant_gap_beyond_it():
    s = replace(ground(), local_grid=('...........', '..M..#.....', '...........', '#########.#'))
    # Use a supported one-tile step, with a hole beyond the obstacle.
    s = replace(s, local_grid=('...........', '...........', '..M..#.....', '#########.#'))
    assert 'ApproachObstacle' in {c.name for c in catalog(s)}


def summit_gap_scene():
    return replace(ground(), x=2402, y=127, local_grid=(
        '...........', '..M........', '...........', '...##..####', '#####..####'))


def test_summit_before_pit_uses_a_composite_skill():
    s = summit_gap_scene()
    names = {c.name for c in catalog(s)}
    assert 'ClimbThenCrossGap' in names
    assert not {'ClimbStep', 'CrossGap'} & names
    control = SkillControl(pick(s, 'ClimbThenCrossGap'), s)
    assert control.next_action(s) == Action.NOOP
    assert control.next_action(s) == Action.JUMP
    control.next_action(replace(s, grounded=False, y=170))
    top = replace(s, x=2424, y=143)
    assert control.next_action(top) == Action.RIGHT_RUN
    assert control.status == 'running'
    assert control.climb_gap_phase == 'cross'


def test_climb_gap_does_not_continue_after_missing_the_summit():
    s = summit_gap_scene()
    control = SkillControl(pick(s, 'ClimbThenCrossGap'), s)
    control.next_action(s)
    control.next_action(replace(s, grounded=False, y=170))
    assert control.next_action(replace(s, x=2410, y=127)) is None
    assert control.status == 'failure'


def test_four_tile_gap_has_runup_option_instead_of_only_waiting():
    s = replace(ground(), status='tall', local_grid=(
        '...........', '..M........', '...........', '######..###'))
    assert s.navigation_features()['gap_distance_tiles'] == 4
    spec = pick(s, 'CrossGap')
    assert SkillControl(spec, s).next_action(s) == Action.RIGHT_RUN
