# Progress guard

User approved bounded recovery or experiment termination for repeated no-progress actions.

Implemented ProgressGuard with 8px progress threshold, 12-decision/180-game-frame stall budgets and at most one validated skill recovery per game. Integrated only into --skills experimental runner; decision source and termination reasons are explicit. Invalid/precondition-rejected actions count against the decision budget. Existing skill timeout remains bounded.

Validation: unit checks for jitter, actual progress and frame budget; runner integration with stationary environment verifies 12 Jev calls then termination without a safe candidate, and exactly one recovery followed by termination on failure. No credit-consuming run is needed to verify this deterministic stopping condition.
