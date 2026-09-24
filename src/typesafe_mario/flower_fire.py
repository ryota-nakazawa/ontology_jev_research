"""Bounded second-site flower collection and stand-off firing controllers."""
from .actions import Action
from .powerup_site import safe_floor
from .stage_knowledge import FLOWER_SITE


def waiting_route_supported(s, target=1290):
    from .state import is_solid
    rows=s.local_grid
    pos=next(((r,row.index('M')) for r,row in enumerate(rows) if 'M' in row),None)
    if pos is None:
        return False
    r,c=pos
    floor=next((i for i in range(r+1,len(rows)) if is_solid(rows[i][c])),None)
    end=c+target//16-s.x//16
    lo,hi=min(c,end),max(c,end)+1
    return floor is not None and 0<=lo<=hi<len(rows[0]) and all(is_solid(rows[floor][j]) for j in range(lo,hi+1))


def flower_eligible(s):
    return (s.status == 'tall' and s.grounded and 1176 <= s.x <= 1344
            and any(o['id'] == FLOWER_SITE['id'] and o['observation'] == 'unused' for o in s.powerup_sites)
            and not any(-64 <= e.dx_pixels <= 96 and abs(e.dy_pixels) < 40 for e in s.enemies)
            and s.navigation_features().get('ground_below_visible')
            and (75 <= s.y <= 83 or 139 <= s.y <= 147))


def fire_target(s):
    if s.status != 'fireball' or not s.grounded or abs(s.horizontal_speed) > 1 or not safe_floor(s):
        return None
    if any(-48 <= e.dx_pixels <= 48 and abs(e.dy_pixels) < 32 for e in s.enemies):
        return None
    if s.navigation_features().get('obstacle_ahead'):
        return None
    return next((e for e in s.enemies if e.kind in {'goomba','green_koopa_troopa','red_koopa_troopa'}
                 and 64 <= e.dx_pixels <= 144 and abs(e.dy_pixels-8) <= 16), None)


class FireAtEnemy:
    def __init__(self, start, parameters):
        self.start, self.parameters = start, parameters
        self.frames = 0
        self.status, self.reason, self.phase = 'running', None, 'aim_right'

    def finish(self, status, reason):
        self.status, self.reason = status, reason

    def next_action(self, s):
        if self.status != 'running':
            return None
        if s.status != 'fireball' or s.dead or not s.grounded or not safe_floor(s):
            return self.finish('aborted', 'firing_conditions_changed')
        if any(-40 <= e.dx_pixels <= 48 and abs(e.dy_pixels) < 32 for e in s.enemies):
            return self.finish('yielded', 'enemy_close_use_evasion')
        target = next((e for e in s.enemies if e.slot == self.parameters['slot'] and e.kind == self.parameters['kind']), None)
        if target is None:
            return self.finish('completed', 'target_no_longer_observed_not_confirmed_kill')
        if target.dx_pixels < 48 or abs(target.dy_pixels-8)>24:
            return self.finish('yielded', 'target_moved_out_of_firing_lane')
        if self.frames >= 72:
            return self.finish('completed', 'firing_budget_reassess')
        f = self.frames
        self.frames += 1
        if f == 0:
            return Action.RIGHT  # face target, and release any previous B press
        if f % 12 == 1 and s.active_fireballs < 2:
            self.phase = 'fire_pulse'
            return Action.FIRE
        self.phase = 'release_b_observe'
        return Action.NOOP


class VisitFlower:
    def __init__(self, start):
        self.start = start
        self.frames = self.phase_frames = 0
        self.phase = 'descend_right' if start.y > 100 else 'reach_wait_point'
        self.status, self.reason = 'running', None
        self.saw_flower = False

    def finish(self, status, reason):
        self.status, self.reason = status, reason

    def switch(self, phase):
        self.phase, self.phase_frames = phase, 0

    def steer(self, s, target):
        if abs(s.x-target) <= 3:
            if abs(s.horizontal_speed) > .4:
                return Action.LEFT if s.horizontal_speed > 0 else Action.RIGHT
            return None
        return Action.RIGHT if s.x < target else Action.LEFT

    def next_action(self, s):
        if self.status != 'running':
            return None
        if s.status == 'fireball':
            return self.finish('success', 'fire_form_confirmed')
        if s.dead or s.status != 'tall':
            return self.finish('failure', 'lost_powerup_or_dead')
        if self.frames >= 550:
            return self.finish('failure', 'flower_visit_timeout')
        if not 1170 <= s.x <= 1348 or any(-64 <= e.dx_pixels <= 80 and abs(e.dy_pixels) < 40 for e in s.enemies):
            return self.finish('aborted', 'flower_route_unsafe')
        self.frames += 1
        self.phase_frames += 1
        if self.phase == 'descend_right':
            if s.grounded and s.y < 90:
                self.switch('reach_wait_point')
            else:
                return self.steer(s,1298) or Action.NOOP
        if self.phase == 'reach_wait_point':
            if s.grounded and not waiting_route_supported(s):
                return self.finish('aborted', 'waiting_route_support_changed')
            a = self.steer(s,1290)
            if a is not None:
                return a
            self.switch('wait_for_route')
        if self.phase == 'wait_for_route':
            if abs(s.horizontal_speed) > .4:
                return Action.LEFT if s.horizontal_speed > 0 else Action.RIGHT
            if any(1160 <= s.x+e.dx_pixels <= 1328 for e in s.enemies):
                return Action.NOOP
            self.switch('align_under_flower_block')
        if self.phase == 'align_under_flower_block':
            if not any(o['id']==FLOWER_SITE['id'] and o['observation']=='unused' for o in s.powerup_sites):
                return self.finish('aborted','flower_block_not_unused')
            a=self.steer(s,1244)
            if a is not None:
                return a
            self.switch('hit_block')
            return Action.NOOP
        if self.phase == 'hit_block':
            if self.phase_frames <= 20:
                return Action.JUMP
            self.switch('wait_for_flower')
        if self.phase == 'wait_for_flower':
            flower=next((o for o in s.world_objects if o.kind=='fire_flower'),None)
            if flower:
                self.saw_flower=True
                self.switch('retreat_for_roof_jump')
            elif self.phase_frames > 100:
                return self.finish('aborted','flower_not_observed')
            else:
                return Action.NOOP
        if self.phase == 'retreat_for_roof_jump':
            a=self.steer(s,1284)
            if a is not None or not s.grounded or s.y>90:
                return a or Action.NOOP
            self.switch('jump_to_roof')
            return Action.NOOP
        if self.phase == 'jump_to_roof':
            if self.phase_frames <= 30:
                return Action.LEFT_JUMP if s.y >= 125 else Action.JUMP
            if s.grounded and s.y < 120:
                return self.finish('failure','roof_jump_landed_short')
            flower=next((o for o in s.world_objects if o.kind=='fire_flower'),None)
            if flower is None:
                return self.finish('aborted','flower_lost_unconfirmed')
            return Action.RIGHT if flower.dx_pixels > 2 else Action.LEFT if flower.dx_pixels < -2 else Action.NOOP
        return Action.NOOP
