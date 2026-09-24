# Continuous skill foundation

Approved scope: user wants the full-game skill architecture as a working foundation, then improve using logs.

1. New whole-game semantic skill catalog and bounded feedback controllers, independent of API and rendering.
2. Direct Jev skill selection over eligible parameterized skills; no old 8-frame primitive instruction. Distinct local waiting/landing controller while a single asynchronous request is in flight.
3. Per-frame state observations; revalidate response against current state and TTL before activation; maintain no raw open-loop primitive selection. Retain prior paused mode as comparison.
4. Structured logs: requests/state/candidates, responses/source/latency, activation/rejection, per-frame input/control/state, skill outcome, stalls/recovery, terminal summary and source hashes. Do not fabricate causes or confidence.
5. Tests: semantic eligibility, termination, response staleness, per-frame hazards, emergency and API failure paths; bounded real run and analyzer output.
6. Update launcher to continuous direct mode through game over, manual Q/Esc stop. Document remaining uncalibrated skills and no promise of high score or safety.

Completed: catalog, asynchronous direct selection, feedback controllers, logging/analyzer, launcher and documentation. Two real runs verified the runtime but ended at x306/x305; handoff timing and enemy avoidance remain calibration work.
