"""Jev chooses semantic skills, never a raw per-eight-frame button."""
import time

from .actions import Action
from .knowledge_strategy import VERSION as STRATEGY_VERSION
from .policy import Decision, TypeSafePolicy

DISPLAY_ACTION = {
    'VisitFlower': Action.JUMP,
    'FireAtEnemy': Action.FIRE,
    'VisitOpeningPowerup': Action.RIGHT,
    'CollectPowerup': Action.RIGHT,
    'ClimbThenCrossGap': Action.RIGHT_RUN_JUMP,
    'EscapeValley': Action.BACK_UP_AND_JUMP,
    'EvadeRearEnemy': Action.JUMP,
    'ApproachObstacle': Action.RIGHT,
    'CrossStaircase': Action.RIGHT_RUN_JUMP,
    'ClimbStep': Action.RIGHT_RUN_JUMP,
    'Advance': Action.RIGHT_RUN, 'Survey': Action.NOOP, 'WaitForOpening': Action.NOOP,
    'LandForward': Action.RIGHT, 'ContinueJump': Action.RIGHT_JUMP,
    'JumpOverEnemy': Action.RIGHT_RUN_JUMP, 'CrossGap': Action.RIGHT_RUN_JUMP,
    'ClearObstacle': Action.CLEAR_OBSTACLE, 'RecoverObstacle': Action.BACK_UP_AND_JUMP,
}


class TypeSafeSkillPolicy(TypeSafePolicy):
    def choose_skill(self, snapshot, candidates, feedback):
        if len(candidates) == 1:
            spec = candidates[0]
            # No model inference or fabricated model probabilities for a forced choice.
            return spec, Decision(action=DISPLAY_ACTION[spec.name], confidence=0.0,
                                  probabilities={}, latency_ms=0.0,
                                  route='local_single_candidate', skill_name=spec.name)
        questions = {'skill': self._Choice(
            instructions={
                'goal': 'Reach the flag without dying. Choose an eligible semantic skill.',
                'execution': 'A feedback controller observes every game frame and executes the skill. '
                             'The game continues during this request under a local handoff controller. '
                             'The selected skill will be revalidated on arrival, never applied blindly.',
                'uncertainty': 'Expected results are goals, not predictions guaranteed to succeed. '
                               'Success probabilities are unmeasured. Use geometry and recent outcomes.',
                'knowledge': 'Use world_knowledge roles: goals and items are not enemies. '
                             'Never assume unseen items or hidden block contents. Article-only rules '
                             'are hypotheses, not validated trajectories. Prefer a safe eligible '
                             'CollectPowerup or VisitOpeningPowerup when it improves protection, but survival comes first.',
                'fire_strategy': 'In this experiment choose eligible VisitFlower before ordinary progression '
                                 'such as CrossGap or Advance while tall, unless an immediate enemy threat requires evasion. '
                                 'The registered visit returns away from the forward pit; it does not walk into it. '
                                 'Prefer FireAtEnemy over approaching a distant susceptible enemy while fiery. '
                                 'Shots can miss: retain evasion for close enemies and never assume a kill.',
                'opening_experiment': 'When VisitOpeningPowerup is eligible, prefer testing this registered '
                                      'upgrade detour over ordinary Advance or Survey while small. '
                                      'Skip it if current hazards or recent outcomes make the detour unsafe.',
                'progress': 'Prefer advancement or resolving the blocking obstacle. Repeated waiting '
                            'without improving conditions is not progress. RecoverObstacle is experimental.',
            }, criteria={s.name: s.to_state() for s in candidates})}
        from .continuous_skills import rear_threat
        state = snapshot.to_state()
        state['rear_threat'] = rear_threat(snapshot)
        state['knowledge_strategy_version'] = STRATEGY_VERSION
        state['skill_candidates'] = [s.to_state() for s in candidates]
        state['recent_skill_outcomes'] = feedback
        started = time.perf_counter()
        response = self._client.system_one(state=state, questions=questions)
        answer = self._answer(response, 'skill', 'choices')
        spec = next((s for s in candidates if s.name == str(answer.choice)), None)
        if spec is None:
            raise ValueError('Jev selected a skill outside the candidate list')
        decision = Decision(action=DISPLAY_ACTION[spec.name], confidence=answer.confidence,
                            probabilities=dict(answer.probabilities),
                            latency_ms=(time.perf_counter() - started) * 1000,
                            route=getattr(response, 'route', None), skill_name=spec.name)
        return spec, decision
