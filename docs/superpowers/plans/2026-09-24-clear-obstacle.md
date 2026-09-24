# ClearObstacle implementation plan

User approved the proposed skill design and fixed-scene validation.

- Preserve current code before changes.
- Add pure candidate/precondition generation and a bounded per-frame controller in skills.py.
- Use visible geometry only; require grounded, known rear support, bounded obstacle height/width and a landing platform. No arbitrary Jev-generated controller numbers.
- Phases: retreat if necessary, approach a measured takeoff point, release jump, hold jump, monitor landing. Stop on damage/death, danger, missing support during retreat, timeout. Log unknown outcomes honestly.
- First reproduce x594/x722 from saved input logs. Validate skill against the same initial scenes without API.
- Add ClearObstacle as a conditional Jev choice with frozen parameters. Revalidate when the response arrives. Integrate the same controller into dashboard and synchronous runners.
- Record parameters, phase changes, every actual primitive input and before/after states, terminal reason; do not invent Jev rationale.
- Run unit/regression tests and fixed-scene emulation, then bounded actual Jev trial. Report controller success separately from full-game performance.
