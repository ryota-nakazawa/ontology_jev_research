"""What a meeting with an enemy is, and when Mario actually lands.

These are pinned to the one death the logs contain: run-20260923T113607Z,
decision #40. Mario fell off a pipe at x=665 with a goomba 28px ahead and 8px
below him. The state told Jev contact was one frame away and landing forty,
so "will_land_before_contact" came back False when Mario was two frames from
the ground. He walked into the goomba's side and died.
"""

from __future__ import annotations

import unittest

from typesafe_mario.state import EnemyObservation, MarioSnapshot


def snapshot(**overrides: object) -> MarioSnapshot:
    fields: dict[str, object] = {
        "goal": "Reach the flag.",
        "world": 1,
        "stage": 1,
        "area": 1,
        "x": 665,
        "y": 79,
        "dx": 14,
        "dy": -30,
        "direction": "moving_right",
        "vertical_motion": "falling",
        "airborne": True,
        "status": "small",
        "player_state": 8,
        "lives": 2,
        "coins": 0,
        "score": 0,
        "time_left": 350,
        "progress": 665,
        "best_progress": 665,
        "stalled_steps": 0,
        "grounded": False,
        "jump_phase": "falling",
        "frames_since_previous": 8,
    }
    fields.update(overrides)
    return MarioSnapshot(**fields)  # type: ignore[arg-type]


# Mario's marker sits two rows above the tile his feet rest on, so this is a
# one-tile drop, not a two-tile one.
GROUND = ("...........", "..M........", "...........", "...........", "###########")
STANDING = ("...........", "..M........", "...........", "###########")
# Both on the same surface: the RAM origins differ by a fixed 8px.
LEVEL_WITH_MARIO = 8


class SpeedIsARate(unittest.TestCase):
    def test_a_displacement_over_eight_frames_is_not_a_per_frame_speed(self) -> None:
        """The headless runner parsed once per decision and reported 17 px/frame."""
        over_a_window = snapshot(dx=14, dy=-30, frames_since_previous=8)
        self.assertAlmostEqual(over_a_window.horizontal_speed, 1.75)
        self.assertAlmostEqual(over_a_window.vertical_speed, -3.75)

    def test_a_per_frame_parse_reports_the_same_motion_unchanged(self) -> None:
        per_frame = snapshot(dx=2, dy=-4, frames_since_previous=1)
        self.assertAlmostEqual(per_frame.horizontal_speed, 2.0)
        self.assertAlmostEqual(per_frame.vertical_speed, -4.0)


class LandingIsMeasuredNotAssumed(unittest.TestCase):
    def test_the_drop_is_read_off_the_grid(self) -> None:
        self.assertEqual(snapshot(local_grid=GROUND).drop_to_surface_pixels(), 16)

    def test_standing_on_a_surface_is_a_drop_of_zero(self) -> None:
        self.assertEqual(snapshot(local_grid=STANDING).drop_to_surface_pixels(), 0)

    def test_a_pit_has_no_surface_to_land_on(self) -> None:
        pit = snapshot(local_grid=("...........", "..M........", "...........", "..........."))
        self.assertIsNone(pit.drop_to_surface_pixels())
        self.assertIsNone(pit.landing_frames())

    def test_a_fall_close_to_the_ground_lands_soon_not_in_forty_frames(self) -> None:
        falling = snapshot(local_grid=GROUND, dy=-30, frames_since_previous=8)
        frames = falling.landing_frames()
        assert frames is not None
        self.assertLess(frames, 10, "the old fixed estimate reported 40 here")

    def test_standing_on_the_ground_lands_now(self) -> None:
        self.assertEqual(snapshot(grounded=True, local_grid=GROUND).landing_frames(), 0)

    def test_a_longer_drop_takes_longer_than_a_shorter_one(self) -> None:
        short = snapshot(local_grid=GROUND, dy=0).landing_frames()
        tall = snapshot(
            local_grid=("..M........", "...........", "...........", "...........",
                        "...........", "###########"), dy=0
        ).landing_frames()
        assert short is not None and tall is not None
        self.assertLess(short, tall)


class AMeetingHasAKind(unittest.TestCase):
    def goomba(self, dy: int, dx: int = 28) -> EnemyObservation:
        return EnemyObservation(slot=0, kind_id=6, kind="goomba", dx_pixels=dx, dy_pixels=dy,
                                relative_velocity_x=-2)

    def test_meeting_an_enemy_on_the_same_ground_is_the_fatal_case(self) -> None:
        """The miscalibration this pins: dy_pixels of 8 IS level, not a stomp.

        Every grounded decision of run-20260923T114634Z read exactly 8, and the
        classifier called all thirteen a stomp. Mario walked into the thirteenth.
        """
        level = snapshot(grounded=True, dy=0, frames_since_previous=1, local_grid=STANDING)
        self.assertEqual(
            level.contact_kind(self.goomba(dy=LEVEL_WITH_MARIO), contact_frames=2), "side_hit"
        )

    def test_coming_down_onto_an_enemy_below_is_the_one_worth_seeking(self) -> None:
        falling = snapshot(dy=-2, frames_since_previous=1, local_grid=GROUND)
        self.assertEqual(
            falling.contact_kind(self.goomba(dy=LEVEL_WITH_MARIO + 16), contact_frames=2), "stomp"
        )

    def test_still_high_above_at_contact_means_it_is_passed_over(self) -> None:
        high = snapshot(dy=0, frames_since_previous=1, local_grid=GROUND)
        self.assertEqual(high.contact_kind(self.goomba(dy=LEVEL_WITH_MARIO + 80), contact_frames=1), "passes_above")

    def test_no_projected_contact_is_said_plainly(self) -> None:
        self.assertEqual(
            snapshot(local_grid=GROUND).contact_kind(self.goomba(dy=LEVEL_WITH_MARIO), contact_frames=None),
            "no_contact_projected",
        )

    def test_a_stomp_and_a_side_hit_are_no_longer_the_same_description(self) -> None:
        """Both used to be reported only as a distance and a countdown."""
        falling = snapshot(dy=-2, frames_since_previous=1, local_grid=GROUND)
        level = snapshot(grounded=True, dy=0, frames_since_previous=1, local_grid=STANDING)
        self.assertNotEqual(
            falling.contact_kind(self.goomba(dy=LEVEL_WITH_MARIO + 16), 2),
            level.contact_kind(self.goomba(dy=LEVEL_WITH_MARIO), 2),
        )


if __name__ == "__main__":
    unittest.main()


class LandingEndsTheFall(unittest.TestCase):
    """The bug this guards: a free fall projected past the ground.

    Decision #40 of the recorded death put Mario ten pixels below a goomba he
    was about to stand level with, so the meeting was classified passes_below
    when it was the side hit that killed him.
    """

    def test_a_meeting_after_landing_is_judged_from_where_mario_stops(self) -> None:
        from typesafe_mario.state import EnemyObservation

        falling = snapshot(dy=-30, frames_since_previous=8, local_grid=GROUND)
        # A tile below Mario now, because it stands on the ground he is falling to.
        goomba = EnemyObservation(slot=0, kind_id=6, kind="goomba", dx_pixels=28,
                                  dy_pixels=LEVEL_WITH_MARIO + 16, relative_velocity_x=-2)
        self.assertEqual(falling.landing_frames(), 4)
        self.assertEqual(
            falling.contact_kind(goomba, contact_frames=14),
            "side_hit",
            "they meet long after Mario has landed, so they meet level",
        )


class ProjectionHasAHorizon(unittest.TestCase):
    """A meeting a hundred frames out is a guess, not a projection.

    Over four runs side_hit fired 63 times at a median of 49 frames out and up
    to 165, while all four deaths were flagged at 14-18. Labelling the distant
    ones diluted the label that mattered.
    """

    def test_a_meeting_beyond_the_horizon_is_not_labelled(self) -> None:
        from typesafe_mario.state import EnemyObservation

        level = snapshot(grounded=True, dy=0, frames_since_previous=1, local_grid=STANDING)
        far = EnemyObservation(slot=0, kind_id=6, kind="goomba", dx_pixels=300,
                               dy_pixels=LEVEL_WITH_MARIO, relative_velocity_x=-2)
        self.assertEqual(level.contact_kind(far, contact_frames=400), "too_far_to_project")

    def test_the_range_every_recorded_death_fell_in_is_still_labelled(self) -> None:
        from typesafe_mario.state import EnemyObservation

        level = snapshot(grounded=True, dy=0, frames_since_previous=1, local_grid=STANDING)
        near = EnemyObservation(slot=0, kind_id=6, kind="goomba", dx_pixels=40,
                                dy_pixels=LEVEL_WITH_MARIO, relative_velocity_x=-2)
        for frames in (14, 15, 18):
            self.assertEqual(level.contact_kind(near, contact_frames=frames), "side_hit")


class TakeoffDeadlineTests(unittest.TestCase):
    """The deadline has to be watched at the speed it actually moves.

    Pinned to the death that ended eight of ten runs at x=689. The takeoff
    deadline read 62, 50, 12, 2 on successive decisions while Mario ran at a
    goomba. `jump_must_start_this_decision` compares it against a fixed
    eight-frame window, but measured over twenty runs the deadline falls by a
    median of 10 frames per decision and by 25 at the ninth decile, so it steps
    over that window instead of landing in it: the flag fired on 4.4% of
    decisions, and at x=689 it first went true with two frames left. Jev then
    chose the right jump at 0.91 confidence and still died.
    """

    def approaching(self, deadline_now: int, deadline_before: int | None, **over: object):
        from typesafe_mario.state import EnemyObservation

        contact = deadline_now + 8  # the deadline is contact minus clearance
        fields: dict[str, object] = {
            "grounded": True, "dy": 0, "frames_since_previous": 8, "local_grid": STANDING,
            "previous_takeoff_deadline_frames": (
                None if deadline_before is None else deadline_before
            ),
        }
        fields.update(over)
        snap = snapshot(**fields)
        # One pixel of closing speed per frame makes contact_frames the distance.
        object.__setattr__(snap, "enemies", (EnemyObservation(
            slot=0, kind_id=6, kind="goomba", dx_pixels=contact,
            dy_pixels=LEVEL_WITH_MARIO, relative_velocity_x=-1),))
        return snap.threat_features()

    def test_a_deadline_stepping_over_the_window_still_raises_the_flag(self) -> None:
        hazard = self.approaching(deadline_now=12, deadline_before=50)

        self.assertEqual(hazard["takeoff_deadline_closing_per_decision"], 38)
        self.assertTrue(
            hazard["jump_must_start_this_decision"],
            "12 frames left and 38 lost per decision is the last chance, not a comfortable margin",
        )

    def test_a_slowly_closing_deadline_is_not_urgent_yet(self) -> None:
        hazard = self.approaching(deadline_now=40, deadline_before=42)

        self.assertEqual(hazard["takeoff_deadline_closing_per_decision"], 2)
        self.assertFalse(hazard["jump_must_start_this_decision"])

    def test_a_deadline_inside_one_window_is_urgent_however_slowly_it_moves(self) -> None:
        hazard = self.approaching(deadline_now=4, deadline_before=5)

        self.assertTrue(hazard["jump_must_start_this_decision"])

    def test_a_takeoff_that_expires_before_landing_is_already_lost(self) -> None:
        """At x=689 this was the state one decision before death: deadline 12
        while falling, with the ground still frames away."""
        hazard = self.approaching(
            deadline_now=2, deadline_before=12, grounded=False, dy=-30, local_grid=GROUND
        )

        self.assertTrue(hazard["takeoff_window_lost_while_airborne"])
        self.assertFalse(hazard["jump_must_start_this_decision"], "he cannot take off in mid-air")

    def test_a_takeoff_still_reachable_after_landing_is_not_lost(self) -> None:
        hazard = self.approaching(
            deadline_now=60, deadline_before=62, grounded=False, dy=-30, local_grid=GROUND
        )

        self.assertFalse(hazard["takeoff_window_lost_while_airborne"])


class ActionOutlookTests(unittest.TestCase):
    """Each action gets its own projected meeting, the way a tetris placement
    is described by the board it leaves rather than by the board it starts from.

    Pinned to the decision that ended most runs of the day. At x=687 a goomba
    stood level with Mario and close; `contact_kind`, which reads only the
    motion Mario is already in, said `no_contact_projected`. He ran forward and
    died. The two choices had to be told apart before they were made.
    """

    def facing(self, dx: int, **over: object):
        from typesafe_mario.state import EnemyObservation

        fields: dict[str, object] = {
            "grounded": True, "dy": 0, "dx": 24, "frames_since_previous": 8,
            "local_grid": STANDING,
        }
        fields.update(over)
        snap = snapshot(**fields)
        object.__setattr__(snap, "enemies", (EnemyObservation(
            slot=0, kind_id=6, kind="goomba", dx_pixels=dx,
            dy_pixels=LEVEL_WITH_MARIO, relative_velocity_x=-2),))
        return snap.action_outlook()

    def test_running_into_a_close_enemy_and_jumping_over_it_are_told_apart(self) -> None:
        outlook = self.facing(dx=30)

        self.assertEqual(outlook["right_run"]["contact_kind"], "side_hit")
        self.assertNotEqual(
            outlook["right_run_jump"]["contact_kind"], "side_hit",
            "the jump has to come back as something other than the fatal case",
        )

    def test_braking_avoids_a_meeting_that_running_walks_into(self) -> None:
        """The distance the recorded run was at two decisions before it died."""
        outlook = self.facing(dx=60)

        self.assertEqual(outlook["right_run"]["contact_kind"], "side_hit")
        self.assertEqual(outlook["left"]["contact_kind"], "beyond_horizon")

    def test_every_offered_primitive_action_gets_an_outlook(self) -> None:
        outlook = self.facing(dx=60)

        self.assertEqual(
            set(outlook), {"right_run", "right_run_jump", "right_jump", "jump",
                           "right", "noop", "left"}
        )
        for action, projection in outlook.items():
            self.assertIn("contact_kind", projection, action)
            self.assertIn("contact_frames", projection, action)

    def test_no_enemy_ahead_means_nothing_to_project(self) -> None:
        self.assertEqual(snapshot(local_grid=STANDING).action_outlook(), {})

    def test_the_advance_profile_separates_actions_over_the_horizon(self) -> None:
        """Eight frames cannot tell the actions apart; thirty-two can."""
        from typesafe_mario.state import MarioSnapshot as S

        at_8 = {a: S._advance(a, 8, 3.0) for a in S.ACTION_ADVANCE_PIXELS["grounded"]}
        at_32 = {a: S._advance(a, 32, 3.0) for a in S.ACTION_ADVANCE_PIXELS["grounded"]}
        self.assertLess(max(at_8.values()) - min(at_8.values()), 10)
        self.assertGreater(max(at_32.values()) - min(at_32.values()), 60)

    def test_the_same_action_carries_mario_differently_at_different_speeds(self) -> None:
        """The defect the single-speed table had: one number for every state."""
        from typesafe_mario.state import MarioSnapshot as S

        self.assertGreater(S._advance("right_run", 32, 3.0), S._advance("right_run", 32, 0.0))
        self.assertGreater(
            S._advance("left", 32, 3.0), S._advance("left", 32, 0.0),
            "braking from a run still drifts forward; braking from a standstill reverses",
        )

    def test_a_jump_locks_in_the_speed_it_took_off_with(self) -> None:
        """Measured: at 3px/frame a running jump matches a run, at 2 it falls behind."""
        from typesafe_mario.state import MarioSnapshot as S

        self.assertEqual(S._advance("right_run_jump", 32, 3.0), S._advance("right_run", 32, 3.0))
        self.assertLess(S._advance("right_run_jump", 32, 2.0), S._advance("right_run", 32, 2.0))


class FallFloorTests(unittest.TestCase):
    """A projected fall stops at the ground, and an unknown fall is not invented.

    Pinned to the decision that killed six of ten runs at x=672: falling with a
    16px drop left and a goomba level with Mario 28px ahead. Integrating gravity
    without a floor sank him 17.65px -- under two pixels too far, but past the
    sprite-height threshold -- so every forward action was projected as
    `passes_below`, meaning no collision, and Mario ran into the goomba.
    """

    def falling_at(self, drop_grid: tuple[str, ...], **over: object):
        from typesafe_mario.state import EnemyObservation

        fields: dict[str, object] = {
            "grounded": False, "jump_phase": "falling", "dy": -30, "dx": 24,
            "frames_since_previous": 8, "local_grid": drop_grid,
        }
        fields.update(over)
        snap = snapshot(**fields)
        object.__setattr__(snap, "enemies", (EnemyObservation(
            slot=0, kind_id=6, kind="goomba", dx_pixels=28,
            dy_pixels=LEVEL_WITH_MARIO + 1, relative_velocity_x=-2),))
        return snap

    def test_landing_level_with_an_enemy_is_a_side_hit_not_a_pass_below(self) -> None:
        outlook = self.falling_at(GROUND).action_outlook()

        self.assertEqual(outlook["right_run"]["contact_kind"], "side_hit")
        for action, projection in outlook.items():
            self.assertNotEqual(
                projection["contact_kind"], "passes_below",
                f"{action}: a 16px drop cannot put Mario a sprite below the ground he lands on",
            )

    def test_braking_in_mid_air_does_not_avoid_the_meeting(self) -> None:
        """Measured: at 3px/frame over 16 frames `left` carries Mario 15px on the
        ground and 29px in the air. He cannot brake once he has left it, and a
        profile without that distinction reported the escape that was not there.
        """
        outlook = self.falling_at(GROUND).action_outlook()

        self.assertEqual(outlook["left"]["contact_kind"], "side_hit")

    def test_braking_on_the_ground_still_avoids_it(self) -> None:
        grounded = self.falling_at(STANDING, grounded=True, jump_phase="grounded", dy=0)
        self.assertEqual(grounded.action_outlook()["left"]["contact_kind"], "beyond_horizon")

    def test_an_unbounded_fall_is_held_rather_than_guessed(self) -> None:
        """Over a pit there is no surface to land on, so no descent is projected."""
        over_a_pit = ("...........", "..M........") + ("...........",) * 7
        snap = self.falling_at(over_a_pit)

        self.assertIsNone(snap.drop_to_surface_pixels())
        self.assertEqual(snap.action_outlook()["right_run"]["contact_kind"], "side_hit")


class OverlapAndCrowdTests(unittest.TestCase):
    """Two failures that both read as "safe" one decision before a death.

    Pinned to the wall at x=1778, where six runs of ten ended. Mario was falling
    towards two goombas walking abreast, 32px and 55px ahead. The projection
    judges at the first frame of horizontal overlap, where he was still high,
    and looks only at the nearest enemy -- so every action came back
    `passes_above`. One decision later every action was `side_hit` and nothing
    could be done.

    Two of these are expected failures, and deliberately so. Both were fixed
    once: the overlap was followed to a real collision and three enemies were
    weighed together. Measured over ten seeds that took the median run from
    1788 to 725 and runs past x=1500 from nine to two, because the fix rests on
    ACTION_ADVANCE_PIXELS, which is measured from full running speed. A braking
    decision is taken exactly when Mario is not at full running speed, so `left`
    was credited with forward drift it does not have and reported safe against
    enemies it was backing into; Jev retreated and was caught from behind. The
    projection cannot widen until the advance profile is speed-relative. These
    tests stay so the defect stays visible and the next attempt starts here.
    """

    def pair(self, first: int, second: int, dy: int = 60, **over: object):
        from typesafe_mario.state import EnemyObservation

        fields: dict[str, object] = {
            "grounded": False, "jump_phase": "airborne", "dy": 0, "dx": 24,
            "frames_since_previous": 8,
            # Ground four tiles below, as it was there.
            "local_grid": ("..........." ,) * 4 + ("..M........",)
            + ("...........",) * 4 + ("###########",) * 2 + ("...........",) * 2,
        }
        fields.update(over)
        snap = snapshot(**fields)
        object.__setattr__(snap, "enemies", tuple(
            EnemyObservation(slot=i, kind_id=6, kind="goomba", dx_pixels=dx,
                             dy_pixels=dy, relative_velocity_x=-2)
            for i, dx in enumerate((first, second))))
        return snap

    @unittest.expectedFailure
    def test_descending_towards_an_enemy_is_not_a_pass_over_it(self) -> None:
        """Judged at first horizontal overlap Mario was 46px clear; he landed on them."""
        outlook = self.pair(32, 55).action_outlook()

        for action, projection in outlook.items():
            self.assertNotEqual(
                projection["contact_kind"], "passes_above",
                f"{action}: falling towards an enemy is not flying over it",
            )

    @unittest.expectedFailure
    def test_the_enemy_behind_the_one_being_stomped_still_counts(self) -> None:
        outlook = self.pair(32, 55).action_outlook()

        self.assertEqual(
            outlook["right_run"]["contact_kind"], "side_hit",
            "carrying forward reaches the second goomba even though the first is stomped",
        )
        survivable = {a for a, p in outlook.items() if p["contact_kind"] != "side_hit"}
        self.assertTrue(
            survivable & {"right", "noop", "left"},
            f"slowing down has to leave a way out; only {sorted(outlook)} were offered",
        )

    def test_a_lone_enemy_far_below_is_still_passed_over(self) -> None:
        """The overlap must end in a pass when Mario really does clear it."""
        from typesafe_mario.state import EnemyObservation

        snap = self.pair(40, 400, dy=200)
        object.__setattr__(snap, "enemies", (EnemyObservation(
            slot=0, kind_id=6, kind="goomba", dx_pixels=40,
            dy_pixels=200, relative_velocity_x=-2),))
        self.assertEqual(snap.action_outlook()["right_run"]["contact_kind"], "passes_above")


class ResponseDelayTests(unittest.TestCase):
    """The chosen action starts when the answer arrives, not when it is chosen.

    In the live window Jev answers in about 277ms -- 16 emulator frames, during
    which Mario covers roughly 50px still doing the previous action. Projecting
    from the present as though the button were already down is what made the
    same vocabulary worth three times as much headless (median 1785) as on
    screen (median 279): headless pauses the game for the answer, so there the
    delay is zero and the projection happened to be right.
    """

    def facing(self, dx: int, delay: int, **over: object):
        from typesafe_mario.state import EnemyObservation

        fields: dict[str, object] = {
            "grounded": True, "dy": 0, "dx": 24, "frames_since_previous": 8,
            "local_grid": STANDING, "last_response_delay_frames": delay,
            "previous_action": "right_run",
        }
        fields.update(over)
        snap = snapshot(**fields)
        object.__setattr__(snap, "enemies", (EnemyObservation(
            slot=0, kind_id=6, kind="goomba", dx_pixels=dx,
            dy_pixels=LEVEL_WITH_MARIO, relative_velocity_x=-2),))
        return snap.action_outlook()

    def test_a_jump_that_clears_instantly_does_not_clear_after_sixteen_frames(self) -> None:
        near = 30
        self.assertNotEqual(
            self.facing(near, delay=0)["right_run_jump"]["contact_kind"], "side_hit"
        )
        self.assertEqual(
            self.facing(near, delay=16)["right_run_jump"]["contact_kind"],
            "side_hit",
            "by the time the jump starts Mario has already run into the goomba",
        )

    def test_a_paused_game_is_the_zero_delay_case_and_is_unchanged(self) -> None:
        """Headless runs block on the answer, so their projection must not move."""
        without = self.facing(60, delay=0)
        self.assertEqual(without["right_run"]["contact_kind"], "side_hit")
        self.assertEqual(without["left"]["contact_kind"], "beyond_horizon")

    def test_the_delay_brings_distant_meetings_into_view(self) -> None:
        """At 90px nothing was projected at all; the meeting is real, just late."""
        prompt = self.facing(90, delay=0)
        delayed = self.facing(90, delay=16)
        self.assertEqual(prompt["right_run"]["contact_kind"], "beyond_horizon")
        self.assertEqual(
            delayed["right_run"]["contact_kind"], "side_hit",
            "the meeting is real; without the delay it fell outside the horizon entirely",
        )


class BeyondHorizonTests(unittest.TestCase):
    """Too slow to reach the enemy is not the same as safe.

    Every slow action pushes the meeting past the 32-frame projection, so
    reporting it as no contact made stalling the recommended move. At 98px from
    a goomba the forward jump that would clear it came back `side_hit` while
    jumping on the spot came back safe; ten runs out of ten jumped on the spot
    and died at the same tile, x=304.
    """

    def outlook(self, dx: int):
        from typesafe_mario.state import EnemyObservation

        snap = snapshot(grounded=True, dy=0, dx=24, frames_since_previous=8,
                        local_grid=STANDING, previous_action="right_run")
        object.__setattr__(snap, "enemies", (EnemyObservation(
            slot=0, kind_id=6, kind="goomba", dx_pixels=dx,
            dy_pixels=LEVEL_WITH_MARIO, relative_velocity_x=-2),))
        return snap.action_outlook()

    def test_an_unreached_enemy_is_named_beyond_horizon_not_no_contact(self) -> None:
        outlook = self.outlook(98)

        slow = {a for a, p in outlook.items() if p["contact_kind"] == "beyond_horizon"}
        self.assertTrue(slow, "the slow actions do not reach the enemy inside the projection")
        for action in slow:
            self.assertNotEqual(
                outlook[action]["contact_kind"], "no_contact_projected",
                f"{action}: being too slow to arrive is not a clean pass",
            )

    def test_a_genuine_pass_is_still_distinguishable_from_never_arriving(self) -> None:
        """passes_above means Mario got there and went over it."""
        kinds = {p["contact_kind"] for p in self.outlook(40).values()}
        self.assertTrue(
            kinds - {"beyond_horizon"}, "something has to actually reach the enemy at 40px"
        )
