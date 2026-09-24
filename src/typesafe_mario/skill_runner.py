"""Paused-decision experiment runner with observed, per-frame skill execution.

Separate logs keep legacy decision-only JSONL readers compatible.
"""
import hashlib
import json
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

from .actions import ACTION_TO_INDEX, JUMP_ACTIONS, JUMP_RELEASE_ACTION, Action, expand
from .dashboard import DashboardCommand, LiveDashboard
from .policy import Decision
from .progress import ProgressGuard
from .runner import _unwrap_ram, create_mario_env
from .skills import SKILL_VERSION, ClearObstacle, clear_obstacle_candidate
from .state import MarioStateParser


def run_skill_episode(*, policy, env_id, seed, max_decisions, frames_per_decision,
                      artifacts_dir, display='dashboard', until_game_over=False):
    env = create_mario_env(env_id, 'human' if display == 'game' else 'rgb_array')
    dashboard = LiveDashboard() if display == 'dashboard' else None
    parser = MarioStateParser(decision_horizon_frames=frames_per_decision)
    output = Path(artifacts_dir) / 'skills'
    output.mkdir(parents=True, exist_ok=True)
    path = output / (datetime.now(UTC).strftime('run-%Y%m%dT%H%M%S.%fZ') + '.jsonl')
    frame, info = env.reset(seed=seed)
    s = parser.parse(info, _unwrap_ram(env))
    total_reward = 0
    best = s.x
    progress = ProgressGuard(s.x)
    frame_index = 0
    stopped = False
    terminated = truncated = False
    end_reason = 'decision_limit'
    stall_reported = False
    try:
        with path.open('w') as log:
            def record(event, **data):
                log.write(json.dumps({'event': event, 'frame': frame_index, **data}) + '\n')
                log.flush()

            record('run_start', seed=seed, env_id=env_id, mode='paused_with_feedback',
                   skill_version=SKILL_VERSION,
                   max_decisions=None if until_game_over else max_decisions,
                   until_game_over=until_game_over,
                   frames_per_decision=frames_per_decision,
                   source_hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in Path(__file__).parent.glob('*.py')})
            for index in (count() if until_game_over else range(max_decisions)):
                if s.dead or s.clear or stopped or terminated or truncated:
                    break
                if dashboard:
                    command = dashboard.draw(frame, s, None, decision_index=index,
                                             episode_reward=total_reward, waiting=True,
                                             run_ended=False)
                    if command in {DashboardCommand.QUIT, DashboardCommand.RESTART}:
                        end_reason = 'user_stop'
                        break
                decision_source = 'jev'
                decision = None
                if not progress.stalled:
                    stall_reported = False
                if progress.stalled:
                    if not stall_reported:
                        record('stall_detected', index=index, **progress.details(), state=s.to_state())
                        stall_reported = True
                    recovery = clear_obstacle_candidate(s) if progress.can_recover else None
                    if recovery is None:
                        if not until_game_over:
                            end_reason = ('stalled_no_safe_recovery' if progress.can_recover
                                          else 'stalled_recovery_exhausted')
                            break
                    else:
                        progress.begin_recovery()
                        decision_source = 'progress_recovery'
                        record('recovery_started', index=index, skill=recovery.to_state())
                        decision = Decision(Action.CLEAR_OBSTACLE, None, {}, 0, skill_plan=recovery)
                if decision is None:
                    decision = policy.choose(s, tuple(Action))
                plan = decision.skill_plan
                record('decision', index=index, decision_source=decision_source, state=s.to_state(), action=decision.action.value,
                       probabilities=dict(decision.probabilities), latency_ms=decision.latency_ms,
                       route=decision.route,
                       skill=plan.to_state() if plan else None,
                       selection_reason=None)  # Jev returns scores, not a textual rationale.
                control = None
                script = []
                if decision.action is Action.CLEAR_OBSTACLE:
                    current = clear_obstacle_candidate(s)
                    if plan is None or current != plan:
                        record('skill_result', index=index, status='rejected',
                               reason='preconditions_changed', state=s.to_state())
                        progress.observe(best, frame_index)
                        continue
                    control = ClearObstacle(plan, s)
                else:
                    script = list(expand(decision.action, frames_per_decision))
                    if decision.action in JUMP_ACTIONS and s.grounded:
                        script[0] = JUMP_RELEASE_ACTION[decision.action]
                while True:
                    step = control.next_action(s) if control else (script.pop(0) if script else None)
                    if step is None:
                        break
                    before = s.to_state()
                    frame, reward, terminated, truncated, info = env.step(ACTION_TO_INDEX[step])
                    frame_index += 1
                    total_reward += float(reward)
                    s = parser.parse(info, _unwrap_ram(env), previous_action=step.value,
                                     previous_reward=float(reward),
                                     previous_latency_ms=decision.latency_ms,
                                     previous_response_delay_frames=0)
                    best = max(best, s.x)
                    record('controller_frame', index=index, input=step.value,
                           phase=control.phase if control else 'primitive',
                           before=before['player'], after=s.to_state()['player'],
                           reward=float(reward), terminated=terminated, truncated=truncated)
                    if dashboard:
                        command = dashboard.draw(frame, s, decision, decision_index=index,
                                                 episode_reward=total_reward, waiting=False,
                                                 run_ended=terminated or truncated)
                        if command in {DashboardCommand.QUIT, DashboardCommand.RESTART}:
                            stopped = True
                            end_reason = 'user_stop'
                    if terminated or truncated or stopped:
                        if control:
                            control.finish('failure' if terminated else 'aborted',
                                           'environment_ended' if not stopped else 'user_stop')
                        break
                if control:
                    record('skill_result', index=index, status=control.status,
                           reason=control.reason, parameters=plan.to_state(),
                           executed_frames=control.frames, state=s.to_state())
                    # An abort is not a safe continuation. Stop this experiment
                    # for review rather than leaving a stale input held.
                    if control.status != 'success' and not until_game_over:
                        stopped = True
                        end_reason = 'skill_' + control.status
                progress.observe(best, frame_index)
                if decision_source == 'progress_recovery':
                    record('recovery_result', index=index, status=control.status,
                           reason=control.reason, **progress.details())
                print(f'#{index:04d} x={s.x} action={decision.action.value}', flush=True)
            if s.dead: end_reason = 'death'
            elif s.clear: end_reason = 'clear'
            elif terminated or truncated: end_reason = 'environment_ended'
            print(f'Ended: {end_reason}; best_x={best}', flush=True)
            record('episode_end', reason=end_reason, best_x=best, state=s.to_state())
    finally:
        env.close()
        if dashboard: dashboard.close()
        close = getattr(policy, 'close', None)
        if callable(close): close()
    return path
