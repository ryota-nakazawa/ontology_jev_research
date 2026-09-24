"""Non-blocking whole-game skill loop, with a single in-flight Jev request."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from .actions import ACTION_TO_INDEX, Action
from .continuous_skills import (
    RUNTIME_VERSION,
    AwaitDecision,
    SkillControl,
    catalog,
    rear_threat,
    response_valid,
)
from .dashboard import DashboardCommand, LiveDashboard
from .landing import LandingSafety
from .progress import ProgressGuard
from .runner import _unwrap_ram, create_mario_env
from .skill_analysis import write_summary
from .state import MarioStateParser


def run_continuous_episode(*, policy, env_id, seed, max_decisions, artifacts_dir,
                           display='dashboard', until_game_over=False, fps=60, session_control=None, pursue_opening_powerup=True, pursue_flower=True, use_fire_skill=True):
    env = create_mario_env(env_id, 'human' if display == 'game' else 'rgb_array')
    dashboard = LiveDashboard() if display == 'dashboard' else None
    output = Path(artifacts_dir) / 'continuous-skills'
    output.mkdir(parents=True, exist_ok=True)
    path = output / (datetime.now(UTC).strftime('run-%Y%m%dT%H%M%S.%fZ') + '.jsonl')
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='jev-skill')
    parser = MarioStateParser(decision_horizon_frames=8)
    frame, info = env.reset(seed=seed)
    s = parser.parse(info, _unwrap_ram(env))
    best, frame_index, request_count = s.x, 0, 0
    total_reward = 0
    progress = ProgressGuard(s.x)
    pending = None
    request_frame = 0
    active = None
    active_id = None
    active_source = None
    attempted_sites = set()
    shown_decision = None
    feedback = []
    awaiting = AwaitDecision()
    landing_guard = LandingSafety()
    end_reason = 'unknown'
    terminated = truncated = False
    stall_reported = False
    started_at = time.monotonic()
    previous_tick = started_at
    try:
        with path.open('w') as log:
            def record(event, **data):
                log.write(json.dumps({'event': event, 'frame': frame_index,
                                      'elapsed_ms': round((time.monotonic() - started_at) * 1000, 2),
                                      **data}) + '\n')
                log.flush()

            def finish_active(status=None, reason=None):
                nonlocal active, active_id, active_source
                if active is None:
                    return
                if status is not None:
                    active.finish(status, reason)
                result = {'skill': active.spec.name, 'status': active.status,
                          'reason': active.reason, 'frames': active.frames,
                          'start_x': active.start.x, 'end_x': s.x}
                feedback.append(result)
                del feedback[:-6]
                record('skill_result', control_id=active_id, source=active_source,
                       result=result, after=s.to_state())
                active = None
                active_id = None
                active_source = None

            record('run_start', mode='continuous_skills', version=RUNTIME_VERSION, seed=seed,
                   env_id=env_id, fps=fps, until_game_over=until_game_over,
                   max_decisions=None if until_game_over else max_decisions,
                   pursue_opening_powerup=pursue_opening_powerup,
                   pursue_flower=pursue_flower, use_fire_skill=use_fire_skill,
                   source_hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in Path(__file__).parent.glob('*.py')})
            while True:
                if s.dead or s.clear or terminated or truncated:
                    end_reason = ('death' if s.dead else 'clear' if s.clear else 'environment_ended')
                    finish_active('success' if s.clear else 'failure', end_reason)
                    break
                progress.frame = frame_index
                if best >= progress.anchor_x + progress.min_progress:
                    progress.observe(best, frame_index)
                    stall_reported = False
                if progress.stalled and not stall_reported:
                    record('stall_detected', **progress.details(), state=s.to_state())
                    stall_reported = True
                if pending is not None and pending.done():
                    age = frame_index - request_frame
                    try:
                        spec, decision = pending.result()
                    except Exception as exc:  # noqa: BLE001 -- worker boundary, log type only
                        # Never persist transport exception text/headers.
                        record('request_error', request_id=request_count - 1,
                               category=type(exc).__name__, age_frames=age)
                        finish_active('aborted', 'request_error')
                        end_reason = 'request_error'
                        break
                    pending = None
                    record('response', request_id=request_count - 1, skill=spec.to_state(),
                           age_frames=age, latency_ms=decision.latency_ms, route=decision.route,
                           probabilities=dict(decision.probabilities), confidence=decision.confidence)
                    if not awaiting.committed and not landing_guard.active and response_valid(spec, s, age):
                        active = SkillControl(spec, s)
                        active_id = f'jev-{request_count - 1}'
                        active_source = ('local_single_candidate' if decision.route == 'local_single_candidate' else 'jev')
                        if active.spec.parameters.get('site_id'):
                            attempted_sites.add(active.spec.parameters['site_id'])
                        shown_decision = decision
                        record('skill_started', control_id=active_id, source=active_source,
                               request_id=request_count - 1, skill=spec.to_state(), state=s.to_state())
                    else:
                        record('response_rejected', request_id=request_count - 1,
                               reason=('landing_guard_committed' if landing_guard.active else
                                       'handoff_committed' if awaiting.committed else
                                       'expired' if age > 45 else 'preconditions_changed'),
                               state=s.to_state())
                action = active.next_action(s) if active and not landing_guard.active else None
                if active and action is None:
                    finish_active()
                if active is None and pending is None and not awaiting.committed and not landing_guard.active:
                    if not until_game_over and request_count >= max_decisions:
                        end_reason = 'decision_limit'
                        break
                    candidates = [c for c in catalog(s) if c.parameters.get('site_id') not in attempted_sites
                                  and (pursue_opening_powerup or c.name != 'VisitOpeningPowerup')
                                  and (pursue_flower or c.name != 'VisitFlower')
                                  and (use_fire_skill or c.name != 'FireAtEnemy')]
                    progressing = [c for c in candidates if c.name not in {'Survey', 'WaitForOpening'}]
                    if progress.stalled and progressing:
                        candidates = progressing
                        record('stalled_wait_excluded', candidates=[c.name for c in candidates], state=s.to_state())
                    recovery = next((c for c in candidates if c.name == 'EscapeValley'), None)
                    if recovery is None:
                        recovery = next((c for c in candidates if c.name == 'ClearObstacle'), None)
                    if recovery is None:
                        recovery = next((c for c in candidates if c.name == 'RecoverObstacle'), None)
                    if progress.stalled and progress.can_recover and recovery:
                        progress.begin_recovery()
                        active = SkillControl(recovery, s)
                        active_id = f'recovery-{frame_index}'
                        active_source = 'local_recovery'
                        shown_decision = None
                        record('skill_started', control_id=active_id, source=active_source,
                               skill=recovery.to_state(), state=s.to_state())
                        action = active.next_action(s)
                        if action is None:
                            finish_active()
                    else:
                        progress.observe(best, frame_index)
                        request_frame = frame_index
                        record('request', request_id=request_count, state=s.to_state(),
                               candidates=[c.to_state() for c in candidates], feedback=list(feedback))
                        pending = executor.submit(policy.choose_skill, s, candidates, list(feedback))
                        request_count += 1
                if action is None:
                    action = Action.NOOP if landing_guard.active else awaiting.next_action(s)
                    source = 'local_handoff'
                    phase = awaiting.phase
                else:
                    source = active_source
                    phase = active.phase
                proposed_action = action
                was_guard_active = landing_guard.active
                action = landing_guard.filter(s, action)
                if landing_guard.active and not was_guard_active:
                    finish_active('aborted', 'landing_safety_takeover')
                    awaiting = AwaitDecision()
                if landing_guard.phase:
                    source = 'local_landing_guard'
                    phase = landing_guard.phase
                    record('landing_safety', proposed=proposed_action.value, actual=action.value,
                           phase=phase, evidence=landing_guard.evidence, state=s.to_state())
                before = s.to_state()
                frame, reward, terminated, truncated, info = env.step(ACTION_TO_INDEX[action])
                frame_index += 1
                total_reward += float(reward)
                s = parser.parse(info, _unwrap_ram(env), previous_action=action.value,
                                 previous_reward=float(reward), previous_response_delay_frames=0)
                best = max(best, s.x)
                record('controller_frame', control_id=active_id, source=source, phase=phase,
                       pending_request=request_count - 1 if pending else None, input=action.value,
                       before=before, after=s.to_state(), rear_threat=rear_threat(s), reward=float(reward),
                       terminated=terminated, truncated=truncated)
                if dashboard:
                    command = dashboard.draw(frame, s, shown_decision, decision_index=request_count,
                                             episode_reward=total_reward, waiting=pending is not None,
                                             run_ended=terminated or truncated)
                    if command in {DashboardCommand.QUIT, DashboardCommand.RESTART}:
                        finish_active('aborted', 'user_stop')
                        end_reason = ('user_restart' if command == DashboardCommand.RESTART
                                      and session_control is not None else 'user_stop')
                        break
                elif fps:
                    time.sleep(max(0, 1 / fps - (time.monotonic() - previous_tick)))
                    previous_tick = time.monotonic()
            if pending is not None:
                record('request_abandoned', request_id=request_count - 1, reason=end_reason)
            record('episode_end', reason=end_reason, best_x=best, requests=request_count,
                   total_frames=frame_index, state=s.to_state())
            print(f'Ended: {end_reason}; best_x={best}; frames={frame_index}; requests={request_count}', flush=True)
    finally:
        if pending is not None:
            pending.cancel()
        close = getattr(policy, 'close', None)
        if callable(close):
            close()
        executor.shutdown(wait=False, cancel_futures=True)
        env.close()
        if dashboard:
            try:
                if session_control is not None:
                    write_summary(path)
                    session_control['restart'] = end_reason == 'user_restart'
                    if end_reason not in {'user_stop', 'user_restart', 'unknown'}:
                        while True:
                            command = dashboard.draw(
                                frame, s, shown_decision, decision_index=request_count,
                                episode_reward=total_reward, waiting=False, run_ended=True)
                            if command != DashboardCommand.CONTINUE:
                                session_control['restart'] = command == DashboardCommand.RESTART
                                break
            finally:
                dashboard.close()
    write_summary(path)
    return path
