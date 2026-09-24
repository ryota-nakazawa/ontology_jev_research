import pytest

from typesafe_mario.progress import ProgressGuard


def test_wiggling_and_retreat_do_not_reset_stall():
    g = ProgressGuard(722)
    for i in range(12):
        g.observe(722 + (i % 3), (i + 1) * 8)
    assert g.stalled


def test_real_progress_resets_stall_and_recovery_is_bounded():
    g = ProgressGuard(722)
    for i in range(11): g.observe(723, (i + 1) * 8)
    g.observe(731, 96)
    assert not g.stalled
    assert g.can_recover
    g.begin_recovery()
    assert not g.can_recover


def test_long_macro_counts_elapsed_game_frames_not_wall_time():
    g = ProgressGuard(722)
    g.observe(722, 180)
    assert g.stalled


@pytest.mark.parametrize('height, reason, recovery_count, until_game_over', [
    (4, 'stalled_no_safe_recovery', 0, False), (3, 'skill_failure', 1, False),
    (4, 'environment_ended', 0, True), (3, 'environment_ended', 1, True),
])
def test_runner_stops_before_spending_100_decisions(tmp_path, monkeypatch, height,
                                                  reason, recovery_count, until_game_over):
    import json
    from dataclasses import replace

    from test_skills import wall_scene

    from typesafe_mario import skill_runner
    from typesafe_mario.actions import Action
    from typesafe_mario.policy import Decision
    s = wall_scene()
    rows = list(s.local_grid)
    if height == 4:
        rows[2] = '...PP......'
    s = replace(s, x=722, local_grid=tuple(rows))
    class Env:
        ram = None
        steps = 0
        def reset(self, **kw): return None, {}
        def step(self, action):
            self.steps += 1
            return None, 0, self.steps >= 1000, False, {}
        def close(self): pass
    class Parser:
        def __init__(self, **kw): pass
        def parse(self, *args, **kw): return s
    class Policy:
        calls = 0
        def choose(self, *args):
            self.calls += 1
            return Decision(Action.RIGHT, 1, {'right': 1}, 0)
    policy = Policy()
    monkeypatch.setattr(skill_runner, 'create_mario_env', lambda *a: Env())
    monkeypatch.setattr(skill_runner, 'MarioStateParser', Parser)
    path = skill_runner.run_skill_episode(policy=policy, env_id='test', seed=123,
        max_decisions=100, frames_per_decision=8, artifacts_dir=tmp_path, display='none', until_game_over=until_game_over)
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    assert policy.calls > 100 if until_game_over else policy.calls == 12
    assert rows[-1]['reason'] == reason
    assert sum(r['event'] == 'recovery_started' for r in rows) == recovery_count
    if recovery_count:
        assert any(r.get('decision_source') == 'progress_recovery' for r in rows)
    assert any(r['event'] == 'stall_detected' for r in rows)
