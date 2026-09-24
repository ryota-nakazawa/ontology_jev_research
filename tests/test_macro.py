from typesafe_mario.actions import (
    ACTION_DESCRIPTIONS,
    ACTION_TO_INDEX,
    MACRO_SCRIPTS,
    Action,
    expand,
)


def test_a_macro_is_a_choice_not_a_controller_input() -> None:
    """Jev picks it by name; only the primitives it expands to reach the emulator."""
    assert Action.BACK_UP_AND_JUMP in MACRO_SCRIPTS
    assert Action.BACK_UP_AND_JUMP not in ACTION_TO_INDEX
    for step in MACRO_SCRIPTS[Action.BACK_UP_AND_JUMP]:
        assert step in ACTION_TO_INDEX, "every scripted frame must be a real input"


def test_the_script_retreats_builds_speed_then_jumps_in_that_order() -> None:
    script = MACRO_SCRIPTS[Action.BACK_UP_AND_JUMP]
    phases = [action for i, action in enumerate(script) if i == 0 or script[i - 1] != action]
    assert phases == [Action.LEFT, Action.RIGHT_RUN, Action.RIGHT_RUN_JUMP]
    assert script.count(Action.LEFT) >= 8, "too short a retreat leaves no room to accelerate"
    assert script.count(Action.RIGHT_RUN) >= 10, "speed has to be rebuilt before takeoff"
    assert script.count(Action.RIGHT_RUN_JUMP) >= 12, "jump is held to keep height"
    assert len(script) > 8, "a macro must outlast one ordinary decision window"


def test_every_action_offered_carries_a_description() -> None:
    for action in Action:
        assert action in ACTION_DESCRIPTIONS
    text = ACTION_DESCRIPTIONS[Action.BACK_UP_AND_JUMP]
    assert "stalled_frames" in text, "the description names the state that justifies it"
    assert "cannot be interrupted" in text, "its cost is stated, not hidden"


def test_every_action_expands_to_inputs_the_emulator_accepts() -> None:
    """The crash this guards against: a chosen macro reaching env.step by name."""
    for action in Action:
        if action is Action.CLEAR_OBSTACLE:
            continue  # Feedback skills cannot expand to an open-loop script.
        frames = expand(action, 8)
        assert frames, f"{action} expands to nothing"
        for step in frames:
            assert step in ACTION_TO_INDEX


def test_an_ordinary_choice_is_held_for_the_decision_window() -> None:
    assert expand(Action.RIGHT_RUN, 8) == (Action.RIGHT_RUN,) * 8
    assert expand(Action.BACK_UP_AND_JUMP, 8) == MACRO_SCRIPTS[Action.BACK_UP_AND_JUMP]


def test_a_finished_macro_never_reaches_the_emulator_by_name() -> None:
    """The crash this guards: the dashboard window died on decision 14.

    A macro is one choice that plays a script. When the script runs out the
    decision still names the macro, and until a new answer arrives the loop
    keeps stepping -- so it handed env.step the macro itself and raised
    KeyError: BACK_UP_AND_JUMP. Holding the input the script ended on is what
    the player would do anyway.
    """
    for action, script in MACRO_SCRIPTS.items():
        assert action not in ACTION_TO_INDEX, f"{action} is a choice, not an input"
        assert script[-1] in ACTION_TO_INDEX, (
            f"{action} must end on an input the emulator accepts, so a finished "
            "script has something to hold"
        )
