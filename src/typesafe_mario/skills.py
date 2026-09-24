"""Conditional skills with frame-by-frame feedback, independent of Jev transport."""
from dataclasses import asdict, dataclass

from .actions import Action
from .state import MarioSnapshot, is_solid

SKILL_VERSION = 'clear-obstacle-v2'


@dataclass(frozen=True)
class ObstaclePlan:
    obstacle_left: int
    obstacle_right: int
    height_tiles: int
    retreat_x: int
    takeoff_x: int
    landing_min_x: int
    landing_max_x: int
    jump_hold_frames: int = 30
    max_frames: int = 180

    def to_state(self):
        return {'skill': 'ClearObstacle', 'version': SKILL_VERSION,
                'parameters': asdict(self), 'success_probability': None,
                'expected_result': 'land beyond the obstacle without damage',
                'risk': 'geometry is sampled; enemies and head collisions may invalidate the plan'}


def clear_obstacle_candidate(s: MarioSnapshot) -> ObstaclePlan | None:
    if not s.grounded or s.dead or s.clear or not s.local_grid:
        return None
    rows = s.local_grid
    pos = next(((r, row.index('M')) for r, row in enumerate(rows) if 'M' in row), None)
    if pos is None:
        return None
    r, c = pos
    floor = next((i for i in range(r + 1, len(rows)) if is_solid(rows[i][c])), None)
    if floor is None or c < 2:
        return None
    # Two observed tiles behind Mario must be level and unobstructed.
    if any(not is_solid(rows[floor][j]) or any(is_solid(rows[i][j])
           for i in range(max(0, floor - 3), floor)) for j in range(c - 2, c)):
        return None
    nav = s.navigation_features()
    distance = nav.get('obstacle_distance_tiles')
    height = nav.get('obstacle_height_tiles', 0)
    if distance is None or distance != 1 or not 2 <= height <= 3 or abs(s.horizontal_speed) > 1:
        return None
    first = c + distance
    end = first
    while end < len(rows[0]) and is_solid(rows[floor - 1][end]):
        end += 1
    if end >= len(rows[0]) - 2 or end - first > 3:
        return None
    # Landing and the next tile are known level ground, with no low ceiling.
    for j in range(end, end + 3):
        if not is_solid(rows[floor][j]) or any(is_solid(rows[i][j])
                for i in range(max(0, floor - 4), floor)):
            return None
    left = (s.x // 16 + distance) * 16
    right = left + (end - first) * 16
    if any(s.x - 40 <= s.x + e.dx_pixels <= right + 48 for e in s.enemies):
        return None
    # Start only within the observed rear corridor. Parameters are fixed by code.
    retreat = s.x if height <= 3 else min(s.x, left - 40)
    takeoff = s.x if height <= 3 else left - 28
    return ObstaclePlan(left, right, height, retreat, takeoff,
                        right + 2, right + 40)


class ClearObstacle:
    def __init__(self, plan: ObstaclePlan, start: MarioSnapshot):
        self.plan = plan
        self.start = start
        self.phase = 'retreat' if start.x > plan.retreat_x else 'approach'
        self.status = 'running'
        self.reason = None
        self.frames = 0
        self.jump_frames = 0
        self.airborne_seen = False

    def finish(self, status, reason):
        self.status, self.reason = status, reason

    def next_action(self, s: MarioSnapshot) -> Action | None:
        if self.status != 'running':
            return None
        if s.dead or s.lives < self.start.lives:
            return self.finish('failure', 'death')
        if self.start.status != 'small' and s.status == 'small':
            return self.finish('failure', 'damage')
        if self.airborne_seen and s.grounded:
            if (self.plan.landing_min_x <= s.x <= self.plan.landing_max_x
                    and abs(s.y - self.start.y) <= 2):
                return self.finish('success', 'landed_beyond_obstacle')
            if (self.plan.obstacle_left - 2 <= s.x <= self.plan.obstacle_right + 12
                    and s.y >= self.start.y + self.plan.height_tiles * 16 - 4):
                self.phase = 'traverse_top'
            elif s.x >= self.plan.obstacle_left:
                return self.finish('failure', 'landed_outside_target')
        if self.frames >= self.plan.max_frames:
            return self.finish('failure', 'timeout')
        if any(abs(e.dx_pixels) < 24 and abs(e.dy_pixels) < 24 for e in s.enemies):
            return self.finish('aborted', 'enemy_entered_corridor')
        self.frames += 1
        if self.phase == 'retreat':
            if not s.grounded or not s.navigation_features().get('ground_below_visible'):
                return self.finish('aborted', 'rear_support_lost')
            if s.x <= self.plan.retreat_x:
                self.phase = 'approach'
            else:
                return Action.LEFT
        if self.phase == 'approach':
            # Collision resolution can push Mario 1px behind the sampled
            # takeoff position (435 -> 434). Do not demand an unreachable x.
            # The tolerance is deliberately small, not permission to jump from
            # an arbitrary retreat position.
            if (s.grounded and s.x >= self.plan.takeoff_x - 2
                    and (s.horizontal_speed > 0 or self.frames >= 2)):
                self.phase = 'jump'
                return Action.RIGHT_RUN  # release A before the next frame
            return Action.RIGHT_RUN
        if self.phase == 'traverse_top' and s.x < self.plan.obstacle_right + 8:
            return Action.RIGHT
        self.airborne_seen |= not s.grounded
        self.jump_frames += 1
        if s.x >= self.plan.landing_min_x:
            self.phase = 'landing'
            return Action.LEFT if s.horizontal_speed > 0 else Action.NOOP
        if self.jump_frames <= self.plan.jump_hold_frames:
            return Action.RIGHT_RUN_JUMP
        return Action.RIGHT_RUN
