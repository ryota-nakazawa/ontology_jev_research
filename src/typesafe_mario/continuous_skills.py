"""Whole-game semantic skills. Frame limits and heuristics are experimental, not guarantees."""
from dataclasses import dataclass, field

from .actions import Action
from .flower_fire import FireAtEnemy, VisitFlower, fire_target, flower_eligible
from .knowledge_strategy import collectible
from .powerup_site import OpeningPowerup, eligible
from .skills import ClearObstacle, ObstaclePlan, clear_obstacle_candidate
from .state import MarioSnapshot, is_solid

RUNTIME_VERSION = 'continuous-skills-v16'


@dataclass(frozen=True)
class SkillSpec:
    name: str
    max_frames: int
    expected: str
    parameters: dict = field(default_factory=dict)

    def to_state(self):
        return {'name': self.name, 'max_frames': self.max_frames,
                'parameters': self.parameters, 'expected_result': self.expected,
                'success_probability': None,
                'risk': 'experimental controller; sampled geometry and timing may be wrong'}


def rear_threat(s):
    threats = [e for e in s.enemies if -80 <= e.dx_pixels < 0
               and abs(e.dy_pixels - 8) <= 16 and e.relative_velocity_x > 0
               and max(0, -e.dx_pixels - 12) / e.relative_velocity_x <= 24]
    if not threats:
        return None
    e = min(threats, key=lambda e: max(0, -e.dx_pixels - 12) / e.relative_velocity_x)
    return {'slot': e.slot, 'kind': e.kind, 'distance_pixels': -e.dx_pixels,
            'closing_speed': e.relative_velocity_x,
            'contact_frames': max(0, -e.dx_pixels - 12) / e.relative_velocity_x}


def forward_escape_clear(s):
    rows = s.local_grid
    pos = next(((r, row.index('M')) for r, row in enumerate(rows) if 'M' in row), None)
    if pos is None:
        return False
    r, c = pos
    floor = next((i for i in range(r + 1, len(rows)) if is_solid(rows[i][c])), None)
    return (floor is not None and c + 3 < len(rows[0])
            and all(is_solid(rows[floor][j])
                    and not any(is_solid(rows[i][j]) for i in range(max(0, floor - 2), floor))
                    for j in range(c + 1, c + 4))
            and not any(0 <= e.dx_pixels <= 64 and abs(e.dy_pixels - 8) <= 24 for e in s.enemies))


class RearEvade:
    """Bounded local response; keep a committed vertical jump through delayed takeoff."""
    def __init__(self, start):
        self.start = start
        self.frames = 0
        self.jump_frames = None
        self.airborne = False
        self.status, self.reason, self.phase = 'running', None, 'rear_escape'
        self.step_escape = None

    def finish(self, status, reason):
        self.status, self.reason = status, reason

    def next_action(self, s):
        if self.status != 'running':
            return None
        if s.dead or s.lives < self.start.lives:
            return self.finish('failure', 'death')
        if self.frames >= 80:
            return self.finish('failure', 'rear_evasion_budget')
        self.frames += 1
        if self.jump_frames is not None:
            self.airborne |= not s.grounded
            if self.airborne and s.grounded:
                return self.finish('completed', 'rear_jump_landed_reassess')
            self.jump_frames += 1
            self.phase = 'rear_jump_hold' if self.jump_frames <= 24 else 'rear_jump_landing'
            if (self.step_escape and s.y >= self.step_escape['height_y']
                    and s.x < self.step_escape['target_x']):
                self.phase = 'rear_jump_onto_obstacle'
                return Action.RIGHT_JUMP if self.jump_frames <= 24 else Action.RIGHT
            return Action.JUMP if self.jump_frames <= 24 else Action.NOOP
        threat = rear_threat(s)
        if not threat:
            return self.finish('completed', 'rear_threat_no_longer_closing')
        if not s.grounded:
            return self.finish('aborted', 'rear_escape_lost_support')
        if forward_escape_clear(s) and threat['contact_frames'] > 8:
            self.phase = 'rear_escape_forward'
            return Action.RIGHT_RUN
        # No forward jump into a pit or wall. Momentum is still possible and logged.
        if s.previous_action in {'jump', 'right_jump', 'right_run_jump'}:
            self.phase = 'rear_jump_release'
            return Action.NOOP
        nav = s.navigation_features()
        distance = nav.get('obstacle_distance_tiles')
        height = nav.get('obstacle_height_tiles', 0)
        if (distance is not None and 1 <= distance <= 2 and 1 <= height <= 3
                and nav.get('gap_distance_tiles') is None):
            self.step_escape = {'target_x': (s.x // 16 + distance) * 16 + 12,
                                'height_y': s.y + height * 16 + 8}
        self.jump_frames = 1
        self.phase = 'rear_jump_hold'
        return Action.JUMP


def nearby_hazard(s):
    nav = s.navigation_features()
    return (not nav.get('ground_below_visible', False)
            or any(0 <= e.dx_pixels <= 80 and abs(e.dy_pixels) < 32 for e in s.enemies)
            or nav.get('obstacle_distance_tiles') is not None
            and nav['obstacle_distance_tiles'] <= 3
            or nav.get('gap_distance_tiles') is not None and nav['gap_distance_tiles'] <= 4)


def rear_clear(s):
    rows = s.local_grid
    for r, row in enumerate(rows):
        if 'M' not in row:
            continue
        c = row.index('M')
        floor = next((i for i in range(r + 1, len(rows)) if is_solid(rows[i][c])), None)
        return (floor is not None and c >= 2
                and all(is_solid(rows[floor][j])
                        and not any(is_solid(rows[i][j]) for i in range(max(0, floor - 3), floor))
                        for j in range(c - 2, c))
                and not any(-48 <= e.dx_pixels <= 16 for e in s.enemies))
    return False


def staircase_plan(s):
    """Observed rising steps, a narrow valley, and a visible equal-height far summit."""
    if (not s.grounded or not s.local_grid
            or any(-32 <= e.dx_pixels <= 160 for e in s.enemies)):
        return None
    rows = s.local_grid
    pos = next(((r, row.index('M')) for r, row in enumerate(rows) if 'M' in row), None)
    if pos is None:
        return None
    r, c = pos
    floor = next((i for i in range(r + 1, len(rows)) if is_solid(rows[i][c])), None)
    if floor is None:
        return None
    tops = [next((i for i in range(len(rows)) if is_solid(rows[i][j])), len(rows))
            for j in range(len(rows[0]))]
    peak = c
    while peak + 1 < len(tops) and tops[peak + 1] == tops[peak] - 1:
        peak += 1
    rise = floor - tops[peak]
    if not 1 <= rise <= 3:
        return None
    far = peak + 1
    while far < len(tops) and tops[far] > tops[peak]:
        far += 1
    if far >= len(tops) or not 1 <= far - peak - 1 <= 3 or tops[far] != tops[peak]:
        return None
    return {'top_x': (s.x // 16 + peak - c) * 16,
            'far_x': (s.x // 16 + far - c) * 16,
            'top_y': s.y + rise * 16,
            'step_x': (s.x // 16 + 1) * 16,
            'target_y': s.y + 16, 'jump_hold_frames': 24}


def valley_escape_plan(s):
    nav = s.navigation_features()
    if (not s.grounded or nav.get('obstacle_distance_tiles') != 1
            or nav.get('obstacle_height_tiles') != 4
            or any(-48 <= e.dx_pixels <= 96 for e in s.enemies)):
        return None
    rows = s.local_grid
    pos = next(((r, row.index('M')) for r, row in enumerate(rows) if 'M' in row), None)
    if pos is None:
        return None
    r, c = pos
    floor = next((i for i in range(r+1, len(rows)) if is_solid(rows[i][c])), None)
    if floor is None or c < 1 or not is_solid(rows[floor][c-1]):
        return None
    if any(is_solid(rows[i][c-1]) for i in range(max(0, floor-4), floor)):
        return None
    left = (s.x//16+1)*16
    return {'obstacle_left': left, 'retreat_x': left-28, 'takeoff_x': left-16,
            'minimum_x': left-40, 'target_x': left+2, 'jump_hold_frames': 40}


def catalog(s: MarioSnapshot):
    if s.dead or s.clear:
        return []
    if not s.grounded:
        return [SkillSpec('LandForward', 72, 'keep forward input until observed landing'),
                SkillSpec('ContinueJump', 72, 'preserve jump height then land moving forward')]
    choices = [SkillSpec('WaitForOpening', 24, 'brake and observe briefly'),
               SkillSpec('Survey', 8, 'release input briefly and observe; momentum may continue')]
    if flower_eligible(s):
        choices.append(SkillSpec('VisitFlower', 550,
            'hit observed second upgrade block and climb to the observed flower; confirm fire form',
            {'site_id': '1-1-second-upgrade'}))
    target = fire_target(s)
    if target:
        choices.append(SkillSpec('FireAtEnemy', 72,
            'face forward and pulse fire at a distant enemy; yield to close danger',
            {'slot': target.slot, 'kind': target.kind}))
    if eligible(s):
        choices.append(SkillSpec('VisitOpeningPowerup', 480,
            'visit verified unused opening block, hit it, observe item, collect only while safe',
            {'site_id': '1-1-opening-upgrade'}))
    item = collectible(s)
    if item:
        choices.append(SkillSpec('CollectPowerup', 60,
            'collect observed nearby upgrade on level ground; confirm powerup status change',
            {'slot': item.slot, 'kind': item.kind}))
    threat = rear_threat(s)
    if threat:
        choices.append(SkillSpec('EvadeRearEnemy', 80,
                                 'escape forward on clear ground or jump without forward input, then reassess',
                                 threat))
    if not nearby_hazard(s):
        choices.append(SkillSpec('Advance', 120, 'advance until terrain or an enemy requires selection'))
    enemies = [e for e in s.enemies if 16 <= e.dx_pixels <= 128 and abs(e.dy_pixels) < 32]
    if enemies:
        e = min(enemies, key=lambda e: e.dx_pixels)
        choices.append(SkillSpec('JumpOverEnemy', 80, 'pass selected enemy and land without damage',
                                 {'slot': e.slot, 'kind': e.kind, 'target_x': s.x + e.dx_pixels + 24,
                                  'jump_hold_frames': 24}))
    nav = s.navigation_features()
    staircase = staircase_plan(s)
    if staircase:
        choices.append(SkillSpec('CrossStaircase', 180,
                                 'climb the summit, immediately jump across the valley, land on the far side',
                                 staircase))
    escape = valley_escape_plan(s)
    if escape:
        choices.append(SkillSpec('EscapeValley', 180,
                                 'retreat within observed floor, run up and jump over the four-tile wall', escape))
    step_distance = nav.get('obstacle_distance_tiles')
    if (step_distance is not None and 2 <= step_distance <= 4
            and 1 <= nav.get('obstacle_height_tiles', 0) <= 3
            and nav.get('ground_below_visible')
            and (nav.get('gap_distance_tiles') is None or nav['gap_distance_tiles'] > step_distance + 1)
            and not any(-16 <= e.dx_pixels <= step_distance * 16 + 32 for e in s.enemies)):
        choices.append(SkillSpec('ApproachObstacle', 90, 'approach the obstacle on observed ground and slow for takeoff',
                                 {'obstacle_left': (s.x // 16 + step_distance) * 16}))
    climb_gap = (step_distance == 1 and nav.get('obstacle_height_tiles') == 1
                 and nav.get('gap_distance_tiles') in (2, 3)
                 and nav.get('gap_crossing_outlook') == 'clearable')
    if climb_gap and abs(s.horizontal_speed) <= 1:
        edge = (s.x//16 + nav['gap_distance_tiles']) * 16
        far = edge + nav['gap_width_tiles_visible'] * 16
        choices.append(SkillSpec('ClimbThenCrossGap', 200,
            'land on the summit first, then run up and cross the pit without waiting for the API',
            {'step_x': (s.x//16+1)*16, 'target_y': s.y+16,
             'gap_start_x': edge, 'gap_end_x': far, 'vertical_start_frames': 24}))
    if (not staircase and not climb_gap and step_distance is not None and 1 <= step_distance <= 2
            and nav.get('obstacle_height_tiles') == 1
            and nav.get('ground_below_visible')
            and not any(0 <= e.dx_pixels < 48 and abs(e.dy_pixels) < 32 for e in s.enemies)):
        step_x = (s.x // 16 + step_distance) * 16
        choices.append(SkillSpec('ClimbStep', 80, 'jump onto the higher step and confirm landing',
                                 {'step_x': step_x, 'target_x': step_x + 8,
                                  'target_y': s.y + 16, 'jump_hold_frames': 24}))
    distance = nav.get('gap_distance_tiles')
    if not climb_gap and distance is not None and distance <= 4 and nav.get('gap_crossing_outlook') == 'clearable':
        edge = (s.x // 16 + distance) * 16
        far = edge + nav['gap_width_tiles_visible'] * 16
        choices.append(SkillSpec('CrossGap', 120, 'run up, take off before the edge, and land beyond it',
                                 {'gap_start_x': edge, 'gap_end_x': far,
                                  'takeoff_x': edge - 16, 'target_x': far + 8,
                                  'jump_hold_frames': 30}))
    plan = clear_obstacle_candidate(s)
    if plan:
        choices.append(SkillSpec('ClearObstacle', plan.max_frames, 'land beyond the obstacle',
                                 plan.to_state()['parameters']))
    if nav.get('obstacle_ahead') and rear_clear(s):
        choices.append(SkillSpec('RecoverObstacle', 100, 'retreat, approach, jump, and regain forward progress',
                                 {'target_x': s.x + 32, 'minimum_x': s.x - 28,
                                  'obstacle_left': (s.x // 16 + nav['obstacle_distance_tiles']) * 16,
                                  'jump_hold_frames': 30}))
    return choices


def response_valid(spec, current, age_frames, ttl=45):
    if age_frames > ttl or current.dead or current.clear:
        return False
    candidates = [c for c in catalog(current) if c.name == spec.name]
    for c in candidates:
        if (spec.name == 'ClearObstacle'
                and (c.parameters['obstacle_left'] != spec.parameters['obstacle_left']
                     or abs(current.x - spec.parameters['takeoff_x']) > 2)):
            continue
        if (spec.name in {'JumpOverEnemy', 'CollectPowerup', 'FireAtEnemy'}
                and any(c.parameters[k] != spec.parameters[k] for k in ('slot', 'kind'))):
            continue
        if (spec.name == 'EscapeValley'
                and c.parameters['obstacle_left'] != spec.parameters['obstacle_left']):
            continue
        if (spec.name == 'ApproachObstacle'
                and c.parameters['obstacle_left'] != spec.parameters['obstacle_left']):
            continue
        if spec.name == 'EvadeRearEnemy' and any(
                c.parameters[k] != spec.parameters[k] for k in ('slot', 'kind')):
            continue
        if spec.name == 'ClimbThenCrossGap' and any(
                c.parameters[k] != spec.parameters[k] for k in ('step_x', 'gap_start_x', 'gap_end_x', 'target_y')):
            continue
        if spec.name == 'CrossStaircase' and any(
                c.parameters[k] != spec.parameters[k] for k in ('top_x', 'far_x', 'top_y')):
            continue
        if spec.name == 'ClimbStep' and any(
                c.parameters[k] != spec.parameters[k] for k in ('step_x', 'target_y')):
            continue
        if spec.name == 'CrossGap' and any(
                c.parameters[k] != spec.parameters[k] for k in ('gap_start_x', 'gap_end_x')):
            continue
        if spec.name in {'RecoverObstacle', 'CrossGap', 'JumpOverEnemy'}:
            key = 'obstacle_left' if spec.name == 'RecoverObstacle' else 'target_x'
            if abs(c.parameters[key] - spec.parameters[key]) > 24:
                continue
        return True
    return False


class SkillControl:
    def __init__(self, spec, start):
        self.spec, self.start = spec, start
        self.status, self.reason, self.phase = 'running', None, 'start'
        self.frames = 0
        self.airborne_seen = not start.grounded
        self.gap_jump_frames = None
        self.valley_phase = 'retreat'
        self.valley_jump_frames = 0
        self.climb_gap_phase = 'climb'
        self.climb_gap_control = None
        if spec.name == 'ClimbThenCrossGap':
            params = spec.parameters
            self.climb_gap_control = SkillControl(SkillSpec('PrecisionClimb', 90, 'land on summit',
                {'target_x': params['step_x'] + 2, 'target_y': params['target_y'],
                 'vertical_start_frames': params['vertical_start_frames'], 'jump_hold_frames': 30}), start)
        self.stair_phase = 'climb'
        self.stair_control = None
        if spec.name == 'CrossStaircase':
            params = spec.parameters
            self.stair_control = SkillControl(SkillSpec('ClimbStep', 80, 'reach summit',
                {'target_x': params['step_x'] + 8, 'target_y': params['target_y'],
                 'jump_hold_frames': 24}), start)
        self.inner = ClearObstacle(ObstaclePlan(**spec.parameters), start) if spec.name == 'ClearObstacle' else None
        if spec.name == 'VisitFlower':
            self.inner = VisitFlower(start)
        if spec.name == 'FireAtEnemy':
            self.inner = FireAtEnemy(start, spec.parameters)
        if spec.name == 'VisitOpeningPowerup':
            self.inner = OpeningPowerup(start)
        if spec.name == 'EvadeRearEnemy':
            self.inner = RearEvade(start)

    def finish(self, status, reason):
        self.status, self.reason = status, reason

    def next_action(self, s):
        if self.status != 'running':
            return None
        if s.dead or s.lives < self.start.lives:
            return self.finish('failure', 'death')
        if self.start.status != 'small' and s.status == 'small':
            return self.finish('failure', 'damage')
        if self.climb_gap_control:
            if self.frames >= self.spec.max_frames:
                return self.finish('failure', 'frame_budget')
            action = self.climb_gap_control.next_action(s)
            if action is None:
                if self.climb_gap_control.status != 'success':
                    return self.finish(self.climb_gap_control.status, self.climb_gap_control.reason)
                if self.climb_gap_phase == 'cross':
                    return self.finish('success', 'climbed_and_crossed_gap')
                params = self.spec.parameters
                if s.x >= params['gap_start_x']:
                    return self.finish('failure', 'overshot_summit')
                self.climb_gap_phase = 'cross'
                self.climb_gap_control = SkillControl(SkillSpec('CrossGap', 110, 'cross from summit',
                    {'gap_start_x': params['gap_start_x'], 'gap_end_x': params['gap_end_x'],
                     'takeoff_x': params['gap_start_x'] - 16, 'target_x': params['gap_end_x'] + 8,
                     'jump_hold_frames': 30}), s)
                action = self.climb_gap_control.next_action(s)
            self.frames += 1
            self.phase = 'climb_gap_' + self.climb_gap_phase + '_' + self.climb_gap_control.phase
            return action
        if self.stair_control:
            if self.frames >= self.spec.max_frames:
                return self.finish('failure', 'frame_budget')
            action = self.stair_control.next_action(s)
            if action is None:
                if self.stair_control.status != 'success':
                    return self.finish(self.stair_control.status, self.stair_control.reason)
                if self.stair_phase == 'cross':
                    return self.finish('success', 'landed_across_staircase')
                params = self.spec.parameters
                if not (params['top_x'] - 2 <= s.x < params['top_x'] + 16
                        and s.y >= params['top_y'] - 2):
                    return self.finish('failure', 'summit_not_reached')
                self.stair_phase = 'cross'
                self.stair_control = SkillControl(SkillSpec('CrossPlatform', 90,
                    'cross valley and land on the far staircase',
                    {'target_x': params['far_x'] + 8, 'jump_hold_frames': 24}), s)
                action = self.stair_control.next_action(s)
            self.frames += 1
            self.phase = 'stair_' + self.stair_phase + '_' + self.stair_control.phase
            return action
        if self.inner:
            a = self.inner.next_action(s)
            self.frames, self.phase = self.inner.frames, self.inner.phase
            self.status, self.reason = self.inner.status, self.inner.reason
            return a
        n = self.spec.name
        if n == 'CollectPowerup':
            if ((self.start.status == 'small' and s.status in {'tall', 'fireball'})
                    or (self.start.status == 'tall' and s.status == 'fireball')):
                return self.finish('success', 'powerup_status_confirmed')
            observed = next((o for o in s.world_objects if o.slot == self.spec.parameters['slot']
                             and o.kind == self.spec.parameters['kind']), None)
            if observed is None:
                return self.finish('aborted', 'item_lost_unconfirmed')
            # Recheck terrain and threats every frame; allow own walking speed.
            from dataclasses import replace
            safe = collectible(replace(s, dx=0))
            if safe is None or safe.slot != observed.slot:
                return self.finish('aborted', 'collection_route_changed')
            if self.frames >= self.spec.max_frames:
                return self.finish('failure', 'frame_budget')
            self.frames += 1
            self.phase = 'approach_observed_powerup'
            return Action.RIGHT
        if self.frames >= self.spec.max_frames:
            return self.finish('completed' if n in {'Advance', 'Survey', 'WaitForOpening'} else 'failure',
                               'frame_budget')
        if n == 'Advance' and (not s.grounded or nearby_hazard(s)):
            return self.finish('yielded', 'hazard_requires_selection')
        if n in {'Survey', 'WaitForOpening', 'RecoverObstacle', 'ApproachObstacle'} and rear_threat(s):
            return self.finish('yielded', 'rear_enemy_requires_selection')
        if (n in {'Survey', 'WaitForOpening', 'RecoverObstacle'}
                and any(0 <= e.dx_pixels <= 40 and abs(e.dy_pixels) <= 16 for e in s.enemies)):
            return self.finish('yielded', 'enemy_requires_selection')
        jumping = n in {'JumpOverEnemy', 'CrossGap', 'CrossPlatform', 'ClimbStep', 'PrecisionClimb', 'EscapeValley', 'RecoverObstacle', 'LandForward', 'ContinueJump'}
        if jumping and self.airborne_seen and s.grounded:
            target = self.spec.parameters.get('target_x', self.start.x)
            landed = s.x >= target and (n not in {'ClimbStep', 'PrecisionClimb'} or s.y >= self.spec.parameters['target_y'] - 2)
            return self.finish('success' if landed else 'failure',
                               'landed_beyond_target' if landed else 'landed_short')
        self.airborne_seen |= not s.grounded
        f = self.frames
        self.frames += 1
        if n == 'PrecisionClimb':
            self.phase = 'vertical_ascent' if f <= self.spec.parameters['vertical_start_frames'] else 'onto_summit'
            if f == 0:
                return Action.NOOP
            if f <= self.spec.parameters['vertical_start_frames']:
                return Action.JUMP
            return Action.RIGHT_JUMP if f <= self.spec.parameters['jump_hold_frames'] else Action.RIGHT
        if n == 'EscapeValley':
            params = self.spec.parameters
            if s.x < params['minimum_x']:
                return self.finish('aborted', 'valley_rear_limit')
            if self.valley_phase != 'jump' and not s.grounded:
                return self.finish('aborted', 'valley_support_lost')
            if any(abs(e.dx_pixels) < 32 and abs(e.dy_pixels) < 32 for e in s.enemies):
                return self.finish('aborted', 'valley_enemy_entered')
            if self.valley_phase == 'retreat' and s.x <= params['retreat_x']:
                self.valley_phase = 'runup'
            if (self.valley_phase == 'runup' and s.x >= params['takeoff_x']
                    and s.horizontal_speed >= 1):
                self.valley_phase = 'jump'
            self.phase = 'valley_' + self.valley_phase
            if self.valley_phase == 'retreat':
                return Action.LEFT
            if self.valley_phase == 'runup':
                return Action.RIGHT_RUN
            self.valley_jump_frames += 1
            return Action.RIGHT_RUN_JUMP if self.valley_jump_frames <= 40 else Action.RIGHT_RUN
        if n == 'ApproachObstacle':
            nav = s.navigation_features()
            if (not s.grounded or not nav.get('ground_below_visible')
                    or (nav.get('gap_distance_tiles') is not None
                        and nav['gap_distance_tiles'] <= (nav.get('obstacle_distance_tiles') or 0))
                    or any(-16 <= e.dx_pixels <= 48 for e in s.enemies)):
                return self.finish('aborted', 'approach_corridor_changed')
            left = self.spec.parameters['obstacle_left']
            if s.x >= left - 16:
                self.phase = 'approach_brake'
                if abs(s.horizontal_speed) <= 1:
                    return self.finish('success', 'reached_takeoff_range')
                return Action.LEFT if s.horizontal_speed > 0 else Action.RIGHT
            self.phase = 'approach_obstacle'
            return Action.RIGHT
        if n == 'Advance':
            self.phase = 'advance'
            return Action.RIGHT_RUN
        if n in {'Survey', 'WaitForOpening'}:
            self.phase = 'observe' if n == 'Survey' else 'brake'
            return Action.LEFT if n == 'WaitForOpening' and s.horizontal_speed > 1 else Action.NOOP
        if n == 'CrossGap':
            params = self.spec.parameters
            if self.gap_jump_frames is None:
                if not s.grounded:
                    return self.finish('aborted', 'lost_support_before_takeoff')
                if s.x >= params['gap_start_x']:
                    return self.finish('aborted', 'missed_takeoff_edge')
                self.phase = 'gap_runup'
                # Release A throughout runup; takeoff depends on position, not API timing.
                if (s.x < params['takeoff_x']
                        or s.previous_action in {'right_jump', 'right_run_jump'}):
                    return Action.RIGHT_RUN
                self.gap_jump_frames = 0
            self.gap_jump_frames += 1
            self.phase = ('gap_jump_hold' if self.gap_jump_frames <= params['jump_hold_frames']
                          else 'gap_landing')
            return (Action.RIGHT_RUN_JUMP if self.gap_jump_frames <= params['jump_hold_frames']
                    else Action.RIGHT_RUN)
        if n == 'RecoverObstacle':
            if f < 12:
                self.phase = 'retreat'
                if not s.grounded or not rear_clear(s) or s.x < self.spec.parameters['minimum_x']:
                    return self.finish('aborted', 'retreat_invalidated')
                return Action.LEFT
            if f < 24:
                self.phase = 'approach'
                return Action.RIGHT_RUN
            f -= 24
        if n in {'LandForward', 'ContinueJump'}:
            self.phase = 'landing'
            return Action.RIGHT_JUMP if n == 'ContinueJump' and s.vertical_speed > 0 else Action.RIGHT
        self.phase = 'release' if f == 0 else 'jump'
        if f == 0:
            return Action.RIGHT_RUN
        return Action.RIGHT_RUN_JUMP if f <= self.spec.parameters['jump_hold_frames'] else Action.RIGHT_RUN


class AwaitDecision:
    """Local handoff control, never attributed to Jev. No claim of guaranteed safety."""
    def __init__(self):
        self.phase = 'brake_while_waiting'
        self.rear_control = None
        self.jump_frames = None
        self.airborne_seen = False

    @property
    def committed(self):
        return self.jump_frames is not None or self.rear_control is not None

    def next_action(self, s):
        if self.rear_control is None and self.jump_frames is None and s.grounded and rear_threat(s):
            self.rear_control = RearEvade(s)
        if self.rear_control is not None:
            action = self.rear_control.next_action(s)
            self.phase = 'local_' + self.rear_control.phase
            if action is not None:
                return action
            self.rear_control = None
        if self.jump_frames is not None:
            self.airborne_seen |= not s.grounded
            if s.dead or s.clear or (self.airborne_seen and s.grounded) or self.jump_frames >= 80:
                self.jump_frames = None
                self.airborne_seen = False
            else:
                self.jump_frames += 1
                self.phase = 'local_emergency_jump' if self.jump_frames <= 30 else 'local_jump_landing'
                return Action.RIGHT_RUN_JUMP if self.jump_frames <= 30 else Action.RIGHT_RUN

        if not s.grounded:
            self.phase = 'land_while_waiting'
            return Action.RIGHT_JUMP if s.vertical_speed > 0 else Action.RIGHT
        if any(0 <= e.dx_pixels <= 48 and abs(e.dy_pixels) <= 16 for e in s.enemies):
            self.phase = 'local_emergency_jump'
            # A release is needed before a NEW jump, never after its first input.
            if s.previous_action in {'right_jump', 'right_run_jump'}:
                return Action.RIGHT_RUN
            self.jump_frames = 1
            self.airborne_seen = False
            return Action.RIGHT_RUN_JUMP
        self.phase = 'brake_while_waiting'
        return Action.LEFT if s.horizontal_speed > 1 else Action.NOOP
