"""Local landing safety, separate from Jev selection; estimates are not guarantees."""
from .actions import Action
from .state import is_solid


def drop_ahead(s):
    if not s.grounded:
        return None
    rows = s.local_grid
    pos = next(((r, row.index('M')) for r, row in enumerate(rows) if 'M' in row), None)
    if pos is None:
        return None
    r, c = pos
    floor = next((i for i in range(r+1, len(rows)) if is_solid(rows[i][c])), None)
    if floor is None:
        return None
    for j in range(c+1, min(c+3, len(rows[0]))):
        lower = next((i for i in range(floor, len(rows)) if is_solid(rows[i][j])), None)
        if lower is None:  # Real pits remain the responsibility of CrossGap.
            return None
        if lower > floor:
            return {'edge_x': (s.x//16+j-c)*16, 'drop_pixels': (lower-floor)*16}
    return None


def landing_risks(s, action):
    """All observed enemies on the predicted landing height, including enemies behind."""
    frames = s.landing_frames()
    drop = s.drop_to_surface_pixels()
    if s.grounded or frames is None or drop is None or not 1 <= frames <= 24:
        return None
    travel = s._advance(action.value, frames, s.horizontal_speed, True)
    enemies = []
    for e in s.enemies:
        if abs(e.dy_pixels - 8 - drop) > 20:
            continue
        enemy_travel = (e.relative_velocity_x + s.horizontal_speed) * frames
        separation = e.dx_pixels + enemy_travel - travel
        enemies.append({'slot': e.slot, 'kind': e.kind,
                        'predicted_separation': round(separation, 2)})
    return {'landing_frames': frames, 'travel': travel, 'enemies': enemies,
            'margin': min((abs(e['predicted_separation']) for e in enemies), default=999)}


def same_landing_surface(s, travel):
    rows = s.local_grid
    pos = next(((r, row.index('M')) for r, row in enumerate(rows) if 'M' in row), None)
    if pos is None:
        return False
    r, c = pos
    target = c + ((s.x + int(travel)) // 16 - s.x // 16)
    if not 0 <= target < len(rows[0]):
        return False
    floor = next((i for i in range(r+1, len(rows)) if is_solid(rows[i][c])), None)
    other = next((i for i in range(r+1, len(rows)) if is_solid(rows[i][target])), None)
    return floor is not None and other == floor


class LandingSafety:
    def __init__(self):
        self.active = False
        self.frames = 0
        self.airborne = False
        self.phase = None
        self.evidence = None

    def adjust_airborne(self, s, proposed):
        if s.grounded or s.vertical_speed > 0:
            return proposed
        original = landing_risks(s, proposed)
        if original is None or original['margin'] >= 24:
            return proposed
        alternatives = []
        for action in (Action.NOOP, Action.LEFT, Action.RIGHT):
            risk = landing_risks(s, action)
            if risk and same_landing_surface(s, risk['travel']):
                alternatives.append((risk['margin'], action, risk))
        if not alternatives:
            return proposed
        margin, action, risk = max(alternatives, key=lambda item: item[0])
        self.evidence = {'original': original, 'selected': risk}
        if margin >= original['margin'] + 4:
            self.phase = 'landing_adjust_for_enemies'
            return action
        return proposed

    def filter(self, s, proposed):
        self.phase = None
        self.evidence = None
        if self.active:
            self.airborne |= not s.grounded
            if s.dead or s.clear or self.frames >= 90 or (self.airborne and s.grounded):
                self.active = False
            else:
                self.frames += 1
                self.phase = 'dismount_jump_hold' if self.frames <= 30 else 'dismount_jump_landing'
                return self.adjust_airborne(s, Action.RIGHT_RUN_JUMP if self.frames <= 30 else Action.RIGHT_RUN)
        drop = drop_ahead(s)
        enemies = [e for e in s.enemies if -8 <= e.dx_pixels <= 96 and 24 <= e.dy_pixels <= 88]
        if drop and enemies and proposed in {Action.RIGHT, Action.RIGHT_RUN, Action.LEFT, Action.NOOP}:
            self.active, self.airborne, self.frames = True, False, 0
            self.evidence = {'drop': drop, 'enemy_slots': [e.slot for e in enemies]}
            self.phase = 'dismount_jump_release'
            # Ensure a new A edge while still standing on the platform.
            return Action.RIGHT_RUN
        return self.adjust_airborne(s, proposed)
