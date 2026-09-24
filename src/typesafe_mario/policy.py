from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .actions import ACTION_DESCRIPTIONS, Action
from .skills import ObstaclePlan, clear_obstacle_candidate
from .state import MarioSnapshot


@dataclass(frozen=True)
class Decision:
    action: Action
    confidence: float | None
    probabilities: Mapping[str, float]
    latency_ms: float
    jump_needed_probability: float | None = None
    danger_score: float | None = None
    skill_plan: ObstaclePlan | None = None
    route: str | None = None
    skill_name: str | None = None


class Policy(Protocol):
    def choose(self, snapshot: MarioSnapshot, actions: Sequence[Action]) -> Decision: ...


class TypeSafePolicy:
    def __init__(self, *, client: Any = None) -> None:
        try:
            from typesafe_sdk import Choice, Noul, Score, TypeSafeClient
        except ImportError as exc:
            raise RuntimeError(
                "typesafe-sdk is not installed. Install the project before using Jev."
            ) from exc
        self._Choice = Choice
        self._Noul = Noul
        self._Score = Score
        self._client = client if client is not None else TypeSafeClient()

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _answer(response: Any, question_id: str, typed_collection: str) -> Any:
        collection = getattr(response, typed_collection, None)
        if collection is not None and question_id in collection:
            return collection[question_id]
        answers = getattr(response, "answers", None)
        if answers is not None and question_id in answers:
            return answers[question_id]
        raise KeyError(f"TypeSafe response omitted {question_id!r}")

    def choose(self, snapshot: MarioSnapshot, actions: Sequence[Action]) -> Decision:
        plan = clear_obstacle_candidate(snapshot) if Action.CLEAR_OBSTACLE in actions else None
        offered = tuple(a for a in actions if a is not Action.CLEAR_OBSTACLE or plan is not None)
        criteria = {action.value: ACTION_DESCRIPTIONS[action] for action in offered}
        model_state = snapshot.to_state()
        if Action.CLEAR_OBSTACLE in actions:
            model_state["available_skills"] = [plan.to_state()] if plan else []
        questions = {
            "next_action": self._Choice(
                instructions={
                    "question": "Which controller macro should Mario commit to next?",
                    "goal": (
                        "Reach the stage flag. Progress is the objective, not survival in "
                        "place: Mario is judged by how far right he gets, and standing off an "
                        "enemy forever scores the same as walking into it. Move forward at the "
                        "speed the ground allows, and give up ground only to avoid a meeting "
                        "`hazard.action_outlook` projects as `side_hit`."
                    ),
                    "timing": "The selected action is held for at least 8 emulator frames.",
                    "geometry": (
                        "Use `terrain.observation_reliability`. While airborne, prefer "
                        "`terrain.last_grounded_preview` over low-reliability current geometry. "
                        "A trusted obstacle or gap within three tiles requires a forward jump. "
                        "`terrain.ground_below_visible` false means no ground is under Mario at "
                        "all and `clear_forward_tiles` is null because nothing can be measured, "
                        "not because the path is clear: this is what falling into a pit looks "
                        "like, and only forward speed can still reach the far side. "
                        "`terrain.gap_crossing_outlook` says whether the gap ahead can be "
                        "cleared: `clearable` means a running jump reaches the far side, so "
                        "commit with speed; `marginal` means it only just reaches, so take off "
                        "at the very edge at full run; `too_wide` means no jump crosses it and "
                        "running at it is fatal; `far_side_not_visible` means the gap runs past "
                        "what can be seen, so its width is a lower bound, not a measurement."
                    ),
                    "trajectory": (
                        "Use `trajectory`. If `crossing_known_gap` is true, preserve forward "
                        "speed and keep a forward jump held while rising. Do not switch to noop "
                        "or left over a gap."
                    ),
                    "stall": (
                        "If `episode.stalled_frames` is increasing and "
                        "`recent_control.outcome` is blocked, the current non-jump action failed."
                    ),
                    "enemy_timing": (
                        "Use `hazard` projections, not distance alone. Code has already accounted "
                        "for inference delay, action cadence, and the frames needed to clear an "
                        "enemy. If `jump_must_start_this_decision` is true, choose a forward jump "
                        "now; another right-run decision will miss the takeoff deadline. "
                        "`takeoff_deadline_closing_per_decision` says how much of that deadline "
                        "one decision costs: when it is close to or larger than the deadline "
                        "itself, this is the last decision that can still act, however large the "
                        "deadline looks. `takeoff_window_lost_while_airborne` true means the "
                        "deadline expires before Mario lands, so no jump can be taken in time; "
                        "use `action_outlook` to pick one that still avoids the meeting. If "
                        "`contact_within_reaction_horizon` is true, also jump immediately. If "
                        "`will_land_before_contact` is true, the current jump will not clear the "
                        "enemy and another takeoff will be needed after landing. Use "
                        "`upcoming_enemies` and their spacing to avoid landing on a second or "
                        "third enemy hidden behind the nearest one. "
                        "`hazard.action_outlook` is the one to decide from: it gives the "
                        "meeting each offered action would produce, not the one the current "
                        "motion is heading for. Choose an action whose outlook is `stomp` "
                        "or `passes_above` over one whose outlook is `side_hit`, even when "
                        "`contact_kind` itself looks harmless. `beyond_horizon` is not safety: "
                        "it means only that this action is too slow to reach the enemy inside "
                        "the projection, and every slow action earns it, so never prefer an "
                        "action for it. Among actions that are not `side_hit`, take the one "
                        "that carries Mario furthest right; `left` and `noop` cost ground and "
                        "are for when every forward action is a `side_hit`. `hazard.contact_kind` describes "
                        "only the current motion: `stomp` means Mario arrives above the enemy "
                        "and kills it, so holding the approach is safe and wanted; `side_hit` "
                        "means they meet level and Mario dies; "
                        "`passes_above` and `passes_below` mean no collision is projected, and "
                        "`too_far_to_project` means the enemy is further off than the "
                        "projection can speak for, not that it is safe."
                    ),
                    "delay": (
                        "`reaction_timing` describes how far the world moves before this choice "
                        "takes effect. Judge urgency from projected rather than current distance."
                    ),
                },
                criteria=criteria,
            ),
            "jump_needed": self._Noul(
                instructions=(
                    "Do trusted `terrain`, projected `hazard`, `trajectory`, and "
                    "`player.jump_phase` indicate that a forward jump should begin or remain "
                    "held now? `hazard.jump_must_start_this_decision=true` is unambiguously yes. "
                    "Also count a trusted obstacle/gap within three tiles, immediate projected "
                    "contact, or a rising jump over a known gap as yes."
                )
            ),
            "danger": self._Score(
                instructions="How dangerous is Mario's immediate situation?",
                criteria=[
                    "Safe open movement",
                    "Potential obstacle or enemy soon",
                    "Immediate collision, fall, or enemy threat",
                ],
            ),
        }
        started = time.perf_counter()
        response = self._client.system_one(state=model_state, questions=questions)
        latency_ms = (time.perf_counter() - started) * 1000

        action_answer = self._answer(response, "next_action", "choices")
        jump_answer = self._answer(response, "jump_needed", "nouls")
        danger_answer = self._answer(response, "danger", "scores")
        action = Action(str(action_answer.choice))
        if action not in offered:
            raise ValueError("Jev selected an action that was not offered")
        probabilities = {
            str(key): float(value) for key, value in dict(action_answer.probabilities).items()
        }
        return Decision(
            action=action,
            confidence=(
                float(action_answer.confidence) if action_answer.confidence is not None else None
            ),
            probabilities=probabilities,
            latency_ms=latency_ms,
            jump_needed_probability=float(jump_answer.noul),
            danger_score=float(danger_answer.score),
            skill_plan=plan if action is Action.CLEAR_OBSTACLE else None,
            route=getattr(response, "route", None),
        )


class HeuristicPolicy:
    """Offline smoke-test policy; not intended as the Mario benchmark baseline."""

    def choose(self, snapshot: MarioSnapshot, actions: Sequence[Action]) -> Decision:
        allowed = set(actions)
        action = Action.RIGHT_RUN if Action.RIGHT_RUN in allowed else actions[0]
        if snapshot.stalled_steps >= 2 and Action.RIGHT_RUN_JUMP in allowed:
            action = Action.RIGHT_RUN_JUMP
        return Decision(
            action=action,
            confidence=1.0,
            probabilities={candidate.value: float(candidate == action) for candidate in actions},
            latency_ms=0.0,
        )
