from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .actions import (
    ACTION_TO_INDEX,
    JUMP_ACTIONS,
    JUMP_RELEASE_ACTION,
    MACRO_SCRIPTS,
    Action,
    expand,
)
from .dashboard import DashboardCommand, LiveDashboard
from .policy import Decision, Policy
from .state import MarioStateParser


def _unwrap_ram(env: Any) -> Any:
    current = env
    visited: set[int] = set()
    while id(current) not in visited:
        visited.add(id(current))
        ram = getattr(current, "ram", None)
        if ram is not None:
            return ram
        next_env = getattr(current, "env", None)
        if next_env is None:
            break
        current = next_env
    return None


def create_mario_env(env_id: str, render_mode: str = "human") -> Any:
    try:
        import gym_super_mario_bros  # noqa: F401
        import gymnasium as gym
        from gym_super_mario_bros.actions import SIMPLE_MOVEMENT
        from nes_py.wrappers import JoypadSpace
    except ImportError as exc:
        raise RuntimeError(
            'Mario dependencies are missing. Install with: pip install -e ".[mario]"'
        ) from exc

    env = gym.make(env_id, render_mode=render_mode)
    return JoypadSpace(env, [*SIMPLE_MOVEMENT, ['B'], ['left', 'A']])


def _record_decision(
    log: Any,
    *,
    decision_index: int,
    snapshot: Any,
    decision: Decision,
    reward: float,
    terminated: bool,
    truncated: bool,
) -> None:
    record = {
        "decision": decision_index,
        "state": snapshot.to_state(),
        "debug_state": snapshot.to_debug_state(),
        "state_text": snapshot.to_text(),
        "action": decision.action.value,
        "confidence": decision.confidence,
        "probabilities": dict(decision.probabilities),
        "jump_needed_probability": decision.jump_needed_probability,
        "danger_score": decision.danger_score,
        "latency_ms": decision.latency_ms,
        "reward": reward,
        "terminated": bool(terminated),
        "truncated": bool(truncated),
    }
    log.write(json.dumps(record, separators=(",", ":")) + "\n")
    log.flush()


def _run_realtime_dashboard(
    *,
    env: Any,
    dashboard: LiveDashboard,
    policy: Policy,
    parser: MarioStateParser,
    frame: Any,
    info: dict[str, Any],
    log: Any,
    frames_per_decision: int,
    max_decisions: int,
    screenshot_path: Path | None,
    pause_while_thinking: bool = False,
) -> None:
    actions = tuple(a for a in Action if a is not Action.CLEAR_OBSTACLE)
    active_decision: Decision | None = None
    pending: Future[Decision] | None = None
    pending_snapshot: Any = None
    pending_index = 0
    pending_request_frame = 0
    next_index = 0
    frame_index = 0
    last_request_frame = -frames_per_decision
    macro_remaining: list[Action] = []
    episode_reward = 0.0
    reward_since_decision = 0.0
    previous_action: Action | None = None
    previous_reward = 0.0
    previous_latency_ms = 0.0
    previous_response_delay_frames = 0
    screenshot_saved = False
    terminated = truncated = False

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="typesafe-jev") as executor:
        while True:
            decision_updated = False
            # Re-reading an unchanged frame would erase velocity and advance
            # stalled/airborne counters during wall-clock inference time.
            if not (pause_while_thinking and pending is not None):
                snapshot = parser.parse(
                    info,
                    _unwrap_ram(env),
                    previous_action=previous_action.value if previous_action else None,
                    previous_reward=previous_reward,
                    previous_latency_ms=previous_latency_ms,
                    previous_response_delay_frames=previous_response_delay_frames,
                )

            if pending is not None and pending.done():
                active_decision = pending.result()
                _record_decision(
                    log,
                    decision_index=pending_index,
                    snapshot=pending_snapshot,
                    decision=active_decision,
                    reward=reward_since_decision,
                    terminated=terminated,
                    truncated=truncated,
                )
                print(
                    f"#{pending_index:04d} x={pending_snapshot.x:04d} "
                    f"action={active_decision.action.value:<15} "
                    f"confidence={active_decision.confidence} "
                    f"latency={active_decision.latency_ms:.0f}ms"
                )
                pending = None
                reward_since_decision = 0.0
                decision_updated = True
                previous_latency_ms = active_decision.latency_ms
                previous_response_delay_frames = frame_index - pending_request_frame

            run_ended = bool(
                snapshot.dead
                or snapshot.clear
                or terminated
                or truncated
                or (next_index >= max_decisions and pending is None)
            )

            if (
                not run_ended
                and pending is None
                and not macro_remaining
                and next_index < max_decisions
                and frame_index - last_request_frame >= frames_per_decision
            ):
                pending_snapshot = snapshot
                pending_index = next_index
                pending = executor.submit(policy.choose, snapshot, actions)
                pending_request_frame = frame_index
                next_index += 1
                last_request_frame = frame_index

            if not run_ended and not (pause_while_thinking and pending is not None):
                action = active_decision.action if active_decision else Action.NOOP
                if decision_updated and action in MACRO_SCRIPTS:
                    macro_remaining = list(MACRO_SCRIPTS[action])
                if macro_remaining:
                    # The script carries its own release edges; play it frame by frame.
                    action = macro_remaining.pop(0)
                    if not macro_remaining:
                        last_request_frame = frame_index
                elif action in MACRO_SCRIPTS:
                    # The script has run out but the decision still names the
                    # macro, and no new one has arrived. Hold the input it ended
                    # on: handing the emulator a macro name crashed the window.
                    action = MACRO_SCRIPTS[action][-1]
                elif decision_updated and action in JUMP_ACTIONS and snapshot.grounded:
                    # A new jump macro needs a button-up edge before A is pressed again.
                    action = JUMP_RELEASE_ACTION[action]
                frame, reward, terminated, truncated, info = env.step(ACTION_TO_INDEX[action])
                previous_action = action
                previous_reward = float(reward)
                reward_since_decision += float(reward)
                episode_reward += float(reward)
                frame_index += 1

            command = dashboard.draw(
                frame,
                snapshot,
                active_decision,
                decision_index=max(0, next_index - 1),
                episode_reward=episode_reward,
                waiting=pending is not None,
                run_ended=run_ended,
            )
            if screenshot_path is not None and active_decision is not None and not screenshot_saved:
                dashboard.save(screenshot_path)
                screenshot_saved = True
            if command == DashboardCommand.QUIT:
                break
            if command == DashboardCommand.RESTART:
                if pending is not None:
                    pending.cancel()
                frame, info = env.reset()
                parser.reset()
                active_decision = None
                pending = None
                pending_snapshot = None
                pending_index = 0
                pending_request_frame = 0
                next_index = 0
                frame_index = 0
                last_request_frame = -frames_per_decision
                macro_remaining = []
                episode_reward = 0.0
                reward_since_decision = 0.0
                previous_action = None
                previous_reward = 0.0
                previous_latency_ms = 0.0
                previous_response_delay_frames = 0
                terminated = truncated = False
                print("--- Restarted ---")


def run_episode(
    *,
    env_id: str,
    policy: Policy,
    frames_per_decision: int,
    max_decisions: int,
    seed: int,
    artifacts_dir: Path,
    display: str = "dashboard",
    screenshot_path: Path | None = None,
    pause_while_thinking: bool = False,
) -> Path:
    if frames_per_decision < 1:
        raise ValueError("frames_per_decision must be at least 1")

    if display not in {"dashboard", "game", "none"}:
        raise ValueError("display must be dashboard, game, or none")
    render_mode = "human" if display == "game" else "rgb_array"
    env = create_mario_env(env_id, render_mode=render_mode)
    dashboard = LiveDashboard() if display == "dashboard" else None
    parser = MarioStateParser(decision_horizon_frames=frames_per_decision)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = artifacts_dir / f"run-{timestamp}.jsonl"

    frame, info = env.reset(seed=seed)

    try:
        with log_path.open("w", encoding="utf-8") as log:
            if dashboard:
                _run_realtime_dashboard(
                    env=env,
                    dashboard=dashboard,
                    policy=policy,
                    parser=parser,
                    frame=frame,
                    info=info,
                    log=log,
                    frames_per_decision=frames_per_decision,
                    max_decisions=max_decisions,
                    screenshot_path=screenshot_path,
                    pause_while_thinking=pause_while_thinking,
                )
                return log_path

            actions = tuple(a for a in Action if a is not Action.CLEAR_OBSTACLE)
            # Read the game every frame, the way the dashboard loop does, and
            # decide once per window as before. Parsing only at the decision
            # boundary gave this loop an eighth of the observations, and it
            # played far worse for it: it died at x=703 in every run while the
            # dashboard reached past x=1100. Speeds, stalls and enemy closing
            # rates are all differences between successive parses, so sampling
            # them eight times more coarsely is not the same measurement.
            snapshot = parser.parse(info, _unwrap_ram(env), frames_elapsed=1)
            for decision_index in range(max_decisions):
                if snapshot.dead or snapshot.clear:
                    break

                decided_from = snapshot
                decision = policy.choose(decided_from, actions)
                # A macro plays its own script instead of one held input, so the
                # headless run makes the same move the dashboard run would.
                script = list(expand(decision.action, frames_per_decision))
                if decision.action in JUMP_ACTIONS and decided_from.grounded:
                    # A new jump needs a button-up edge before A is pressed
                    # again, or holding it across the boundary never starts one.
                    script[0] = JUMP_RELEASE_ACTION[decision.action]
                total_reward = 0.0
                terminated = truncated = False
                for step in script:
                    frame, reward, terminated, truncated, info = env.step(ACTION_TO_INDEX[step])
                    total_reward += float(reward)
                    snapshot = parser.parse(
                        info,
                        _unwrap_ram(env),
                        previous_action=step.value,
                        previous_reward=float(reward),
                        previous_latency_ms=decision.latency_ms,
                        previous_response_delay_frames=0,
                        frames_elapsed=1,
                    )
                    if terminated or truncated:
                        break

                # The state the decision was made from, not the one it led to:
                # replaying a policy change needs what the model actually saw.
                _record_decision(
                    log,
                    decision_index=decision_index,
                    snapshot=decided_from,
                    decision=decision,
                    reward=total_reward,
                    terminated=terminated,
                    truncated=truncated,
                )
                print(
                    f"#{decision_index:04d} x={decided_from.x:04d} "
                    f"action={decision.action.value:<15} "
                    f"confidence={decision.confidence} latency={decision.latency_ms:.0f}ms"
                )

                if terminated or truncated:
                    break
    finally:
        if dashboard:
            dashboard.close()
        env.close()
        close = getattr(policy, "close", None)
        if callable(close):
            close()

    return log_path
