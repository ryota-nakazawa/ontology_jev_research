from __future__ import annotations

from enum import StrEnum


class Action(StrEnum):
    LEFT_JUMP = "left_jump"
    FIRE = "fire"
    NOOP = "noop"
    RIGHT = "right"
    RIGHT_JUMP = "right_jump"
    RIGHT_RUN = "right_run"
    RIGHT_RUN_JUMP = "right_run_jump"
    JUMP = "jump"
    LEFT = "left"
    BACK_UP_AND_JUMP = "back_up_and_jump"
    CLEAR_OBSTACLE = "clear_obstacle"


# Indices 0..6 preserve SIMPLE_MOVEMENT; index 7 appends stationary B.
ACTION_TO_INDEX: dict[Action, int] = {
    Action.FIRE: 7,
    Action.LEFT_JUMP: 8,
    Action.NOOP: 0,
    Action.RIGHT: 1,
    Action.RIGHT_JUMP: 2,
    Action.RIGHT_RUN: 3,
    Action.RIGHT_RUN_JUMP: 4,
    Action.JUMP: 5,
    Action.LEFT: 6,
}

# A macro is one choice that plays a fixed script of primitive inputs. Holding a
# single input for eight frames cannot express "retreat, build speed, then jump",
# and a wall three tiles high needs exactly that: Mario cannot clear it from a
# standstill, and the next decision would only repeat the failed jump.
MACRO_SCRIPTS: dict[Action, tuple[Action, ...]] = {
    Action.BACK_UP_AND_JUMP: (
        (Action.LEFT,) * 10          # reverse away from the wall
        + (Action.RIGHT_RUN,) * 12   # build running speed
        + (Action.RIGHT_RUN_JUMP,) * 16  # take off and hold to keep height
    ),
}

def expand(action: Action, hold_frames: int) -> tuple[Action, ...]:
    """The primitive inputs one chosen action plays.

    A macro carries its own script; every other choice is simply held for the
    decision window. Going through here is what keeps a macro from ever
    reaching the emulator as itself -- it has no controller index.
    """
    if action is Action.CLEAR_OBSTACLE:
        raise ValueError("ClearObstacle requires the feedback skill controller")
    script = MACRO_SCRIPTS.get(action)
    return script if script is not None else (action,) * hold_frames


JUMP_ACTIONS = frozenset({Action.RIGHT_JUMP, Action.RIGHT_RUN_JUMP, Action.JUMP, Action.LEFT_JUMP})

JUMP_RELEASE_ACTION: dict[Action, Action] = {
    Action.LEFT_JUMP: Action.LEFT,
    Action.RIGHT_JUMP: Action.RIGHT,
    Action.RIGHT_RUN_JUMP: Action.RIGHT_RUN,
    Action.JUMP: Action.NOOP,
}


ACTION_DESCRIPTIONS: dict[Action, str] = {
    Action.LEFT_JUMP: "Jump toward a verified landing area to the left.",
    Action.FIRE: "Press B without movement; firing requires fireball form and a fresh press.",
    Action.CLEAR_OBSTACLE: (
        "ClearObstacle: use the offered fixed parameters to cross the nearby 2-3 tile "
        "obstacle and land beyond it. A feedback controller monitors every frame, holds "
        "jump, traverses the top if needed and brakes on descent. Prefer this skill when "
        "ordinary forward input is blocked. It aborts if danger enters the corridor. "
        "The success probability is unmeasured; this is not an enemy-avoidance skill."
    ),
    Action.NOOP: "Release the controls and let current momentum continue.",
    Action.RIGHT: (
        "Walk right. Held for four decisions from full speed it covers 66px against a run's "
        "94px. Use it to arrive at an enemy or a ledge with the timing a jump needs, not as a "
        "way to put the meeting off: the enemy closes either way."
    ),
    Action.RIGHT_JUMP: (
        "Start a controlled forward jump, or keep holding jump while rising to preserve height."
    ),
    Action.RIGHT_RUN: (
        "Run right: the fastest way to advance, 94px over four decisions from full speed "
        "against a walk's 66px. A jump keeps whatever speed it took off with, so a gap has to "
        "be reached at running speed to be cleared at all. Run whenever the projected meeting "
        "for it is not `side_hit`."
    ),
    Action.RIGHT_RUN_JUMP: (
        "Start a running jump when terrain or projected contact requires it, or keep holding "
        "it while rising. Prefer this when `hazard.jump_must_start_this_decision` is true."
    ),
    Action.JUMP: (
        "Jump mostly in place, or keep holding jump while rising when forward motion is unsafe."
    ),
    Action.LEFT: "Move left to evade danger or recover from an overshoot.",
    Action.BACK_UP_AND_JUMP: (
        "A fixed 38-frame sequence: retreat left, build running speed, then hold a running jump. "
        "Choose it only when forward progress has stopped against an obstacle that a standing "
        "jump cannot clear, such as `episode.stalled_frames` rising with "
        "`terrain.clear_forward_tiles` at 0 and an obstacle two or more tiles high. It gives up "
        "ground and cannot be interrupted, so it is wrong whenever an ordinary jump would do."
    ),
}
