from types import SimpleNamespace

from typesafe_mario.actions import Action
from typesafe_mario.cli import _demo_ram
from typesafe_mario.policy import TypeSafePolicy
from typesafe_mario.state import MarioStateParser


class GatewayFixture:
    def system_one(self, *, state, questions):
        return SimpleNamespace(
            answers={
                "next_action": SimpleNamespace(
                    choice="right_jump",
                    confidence=None,
                    probabilities={"right_jump": 0.8, "right": 0.2},
                ),
                "jump_needed": SimpleNamespace(noul=0.8),
                "danger": SimpleNamespace(score=1.5),
            }
        )


def test_gateway_decision_preserves_missing_confidence():
    policy = TypeSafePolicy(client=GatewayFixture())
    snapshot = MarioStateParser().parse({"x_pos": 172, "y_pos": 79}, _demo_ram())
    decision = policy.choose(snapshot, tuple(Action))
    assert decision.action == Action.RIGHT_JUMP
    assert decision.confidence is None
    assert decision.probabilities["right_jump"] == 0.8
    assert decision.jump_needed_probability == 0.8
    assert decision.danger_score == 1.5


def test_gateway_error_is_reported_without_interpreting_it_as_a_decision():
    import pytest

    from typesafe_mario.gateway import decode_response

    with pytest.raises(RuntimeError, match="403.*credit card"):
        decode_response({"error": {"status": 403, "message": "credit card required"}})


def test_gateway_response_keeps_probability_mapping():
    from typesafe_mario.gateway import decode_response

    response = decode_response(
        {
            "answers": {
                "next_action": {
                    "type": "choice",
                    "choice": "right",
                    "confidence": None,
                    "probabilities": {"right": 0.75, "left": 0.25},
                }
            }
        }
    )
    assert response.answers["next_action"].probabilities == {"right": 0.75, "left": 0.25}
    assert response.answers["next_action"].confidence is None
