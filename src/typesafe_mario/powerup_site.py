"""One explicitly registered 1-1 site; map knowledge is not live evidence."""
from .actions import Action
from .stage_knowledge import SITE, observe_site  # noqa: F401 -- compatibility for parser/tests


def safe_floor(s):
    from .state import is_solid
    rows = s.local_grid
    pos = next(((r, row.index('M')) for r, row in enumerate(rows) if 'M' in row), None)
    if pos is None:
        return False
    r, c = pos
    floor = next((i for i in range(r+1, len(rows)) if is_solid(rows[i][c])), None)
    return floor is not None and all(is_solid(rows[floor][j]) for j in range(max(0,c-2), min(c+5,len(rows[0]))))


def eligible(s):
    platform = 320 <= s.x <= 380 and 139 <= s.y <= 147 and not s.navigation_features().get('gap_ahead')
    return (s.status == 'small' and s.grounded and 280 <= s.x <= 416 and (75 <= s.y <= 83 or platform)
            and any(o['id'] == SITE['id'] and o['observation'] == 'unused' for o in s.powerup_sites)
            and (safe_floor(s) or platform) and not any(-64 <= e.dx_pixels <= 112 and abs(e.dy_pixels) < 32 for e in s.enemies)
            and not any(abs(s.x+e.dx_pixels-404) < 64 for e in s.enemies))


class OpeningPowerup:
    def __init__(self, start):
        self.start = start
        self.frames = 0
        self.phase = 'descend_to_block_base' if start.y > 100 else 'align_under_registered_block'
        self.status = 'running'
        self.reason = None
        self.jump_frames = 0
        self.item_seen = False

    def finish(self, status, reason):
        self.status, self.reason = status, reason

    def next_action(self, s):
        if self.status != 'running':
            return None
        if s.status in {'tall', 'fireball'}:
            return self.finish('success', 'powerup_status_confirmed')
        if s.dead or s.lives < self.start.lives:
            return self.finish('failure', 'death')
        if self.frames >= 480:
            return self.finish('failure', 'powerup_attempt_timeout')
        if not 264 <= s.x <= 432 or any(-40 <= e.dx_pixels <= 64 and abs(e.dy_pixels) < 32 for e in s.enemies):
            return self.finish('aborted', 'route_or_enemy_changed')
        if self.phase != 'descend_to_block_base' and s.grounded and s.y < 90 and not safe_floor(s):
            return self.finish('aborted', 'support_changed')
        self.frames += 1
        if self.phase == 'descend_to_block_base':
            if any(abs(s.x+e.dx_pixels-404) < 64 for e in s.enemies):
                return self.finish('aborted', 'landing_zone_enemy')
            if s.grounded and s.y < 90:
                self.phase = 'align_under_registered_block'
            else:
                return Action.RIGHT if s.x < 402 else Action.LEFT if s.horizontal_speed > .4 else Action.NOOP
        if self.phase == 'align_under_registered_block':
            if not any(o['id'] == SITE['id'] and o['observation'] == 'unused' for o in s.powerup_sites):
                return self.finish('aborted', 'block_not_unused')
            if abs(s.x-332) <= 3:
                if abs(s.horizontal_speed) > .4:
                    return Action.LEFT if s.horizontal_speed > 0 else Action.RIGHT
                self.phase = 'release_before_hit'
                return Action.NOOP
            return Action.RIGHT if s.x < 332 else Action.LEFT
        if self.phase == 'release_before_hit':
            self.phase = 'hit_registered_block'
        if self.phase == 'hit_registered_block':
            self.jump_frames += 1
            if self.jump_frames <= 20:
                return Action.JUMP
            self.phase = 'observe_emergence'
        item = next((o for o in s.world_objects if o.kind == 'mushroom'), None)
        if item:
            self.item_seen = True
            self.phase = 'follow_observed_item'
            # Follow actual item, never its expected spawn position; stop before pipe.
            target = min(404, max(280, s.x + item.dx_pixels))
            if abs(target-s.x) > 6:
                return Action.RIGHT if target > s.x else Action.LEFT
        elif self.item_seen:
            return self.finish('aborted', 'item_lost_unconfirmed')
        return Action.NOOP
