# Mario delay correction plan

Approved scope: user requested implementation and execution after the review. Preserve Claude changes.

1. Snapshot current sources/tests.
2. Reproduce incorrect held-action lookup after grounded/airborne table split with a regression test: every candidate must share the same trajectory before its response arrives.
3. Correct lookup without replacing movement profiles or policy.
4. Run existing tests; compare predictions before/after.
5. Execute bounded Jev gameplay with actual response delay, report outcome without claiming statistical improvement.

Completed: held-input regression fix, opt-in paused dashboard with frozen observation clock, 65 tests, lint, 4 realtime trials + 1 visible paused trial. Results: docs/codex-mario-delay-results-2026-09-24.md. No score improvement established.
