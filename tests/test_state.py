from __future__ import annotations

import unittest

from typesafe_mario.state import MarioStateParser


class MarioStateParserTests(unittest.TestCase):
    def base_info(self, **overrides: object) -> dict[str, object]:
        info: dict[str, object] = {
            "world": 1,
            "stage": 1,
            "area": 1,
            "x_pos": 100,
            "y_pos": 80,
            "y_pixel": 80,
            "progress": 100,
            "time": 390,
            "life": 2,
            "status": "small",
        }
        info.update(overrides)
        return info

    def test_first_snapshot_is_not_stalled(self) -> None:
        snapshot = MarioStateParser().parse(self.base_info())

        self.assertEqual(snapshot.stalled_steps, 0)
        self.assertEqual(snapshot.direction, "nearly_stationary")

    def test_motion_and_stall_are_derived_across_frames(self) -> None:
        parser = MarioStateParser()
        parser.parse(self.base_info())

        moving = parser.parse(self.base_info(x_pos=108, progress=108, y_pos=75))
        stalled = parser.parse(self.base_info(x_pos=108, progress=108, y_pos=75))

        self.assertEqual(moving.direction, "moving_right")
        self.assertEqual(moving.vertical_motion, "falling")
        self.assertEqual(moving.best_progress, 108)
        self.assertEqual(stalled.stalled_steps, 1)

    def test_ram_enemy_and_grid_become_structured_state(self) -> None:
        ram = bytearray(0x0800)
        ram[0x000F] = 1
        ram[0x0016] = 0x06
        ram[0x006E] = 0
        ram[0x0087] = 142
        ram[0x00CF] = 80
        ram[0x0010] = 1
        ram[0x0017] = 0x06
        ram[0x006F] = 0
        ram[0x0088] = 180
        ram[0x00D0] = 80

        snapshot = MarioStateParser().parse(self.base_info(), ram)
        state = snapshot.to_state()
        debug = snapshot.to_debug_state()

        self.assertEqual(state["hazard"]["nearest_enemy_kind"], "goomba")
        self.assertEqual(state["hazard"]["nearest_enemy_distance_pixels"], 42)
        self.assertEqual(len(state["hazard"]["upcoming_enemies"]), 2)
        self.assertEqual(state["hazard"]["spacing_to_second_enemy_pixels"], 38)
        self.assertGreaterEqual(len(debug["local_grid"]["rows"]), 13)
        self.assertTrue(all(len(row) == 11 for row in debug["local_grid"]["rows"]))
        self.assertIn("M", "".join(debug["local_grid"]["rows"]))
        self.assertIn("goomba 42px ahead", snapshot.to_text())

        moving = MarioStateParser()
        moving.parse(self.base_info(), ram)
        next_state = moving.parse(
            self.base_info(x_pos=108, progress=108),
            ram,
            previous_latency_ms=100,
        ).to_state()
        self.assertEqual(next_state["hazard"]["relative_velocity_x"], -8)
        self.assertEqual(next_state["hazard"]["estimated_contact_frames"], 4)
        self.assertTrue(next_state["hazard"]["contact_within_reaction_horizon"])
        self.assertTrue(next_state["hazard"]["takeoff_window_already_missed"])
        self.assertFalse(next_state["hazard"]["jump_must_start_this_decision"])
        self.assertEqual(next_state["reaction_timing"]["last_inference_delay_frames"], 6)
        self.assertEqual(next_state["hazard"]["projected_distance_after_reaction_pixels"], 0)

        deadline_ram = bytearray(0x0800)
        deadline_ram[0x000F] = 1
        deadline_ram[0x0016] = 0x06
        deadline_ram[0x006E] = 0
        deadline_ram[0x0087] = 236
        deadline_ram[0x00CF] = 80
        for column in range(16):
            deadline_ram[0x0500 + 5 * 16 + column] = 1
        deadline_parser = MarioStateParser()
        deadline_parser.parse(self.base_info(), deadline_ram)
        deadline_state = deadline_parser.parse(
            self.base_info(x_pos=108, progress=108),
            deadline_ram,
            previous_latency_ms=100,
            previous_response_delay_frames=8,
        ).to_state()
        self.assertEqual(deadline_state["hazard"]["estimated_contact_frames"], 16)
        self.assertEqual(deadline_state["hazard"]["takeoff_deadline_frames"], 0)
        self.assertEqual(deadline_state["reaction_timing"]["last_inference_delay_frames"], 8)
        self.assertTrue(deadline_state["hazard"]["jump_must_start_this_decision"])

    def test_pipe_geometry_is_exposed_as_navigation_state(self) -> None:
        ram = bytearray(0x0800)
        for column in range(16):
            ram[0x0500 + 5 * 16 + column] = 1
        pipe_column = 7
        ram[0x0500 + 3 * 16 + pipe_column] = 1
        ram[0x0500 + 4 * 16 + pipe_column] = 1

        snapshot = MarioStateParser().parse(self.base_info(), ram)
        terrain = snapshot.to_state()["terrain"]

        self.assertTrue(terrain["obstacle_ahead"])
        self.assertEqual(terrain["obstacle_distance_tiles"], 1)
        self.assertEqual(terrain["obstacle_height_tiles"], 2)
        self.assertNotIn("summary", terrain)

    def test_recent_control_tracks_macro_outcome(self) -> None:
        parser = MarioStateParser()
        parser.parse(self.base_info(), previous_action="right_run")
        state = parser.parse(
            self.base_info(x_pos=106, progress=106),
            previous_action="right_run",
        ).to_state()

        self.assertEqual(state["recent_control"]["action"], "right_run")
        self.assertEqual(state["recent_control"]["frames_observed"], 2)
        self.assertEqual(state["recent_control"]["progress_gained_pixels"], 6)

    def test_airborne_state_exposes_trajectory_and_low_reliability_geometry(self) -> None:
        ram = bytearray(0x0800)
        for column in range(16):
            ram[0x0500 + 5 * 16 + column] = 1
        parser = MarioStateParser()
        parser.parse(self.base_info(), ram)

        state = parser.parse(self.base_info(x_pos=106, y_pos=90, progress=106), ram).to_state()

        self.assertEqual(state["trajectory"]["airborne_frames"], 1)
        self.assertEqual(state["trajectory"]["horizontal_distance_since_takeoff_pixels"], 6)
        self.assertEqual(state["terrain"]["observation_reliability"], "low_airborne")

    def test_reset_clears_episode_history(self) -> None:
        parser = MarioStateParser(goal="Finish safely")
        parser.parse(self.base_info(x_pos=300, progress=300), previous_action="right_run")

        parser.reset()
        snapshot = parser.parse(self.base_info(x_pos=40, progress=40))

        self.assertEqual(snapshot.goal, "Finish safely")
        self.assertEqual(snapshot.best_progress, 40)
        self.assertEqual(snapshot.stalled_steps, 0)
        self.assertIsNone(snapshot.previous_action)


if __name__ == "__main__":
    unittest.main()


class RecentControlTests(unittest.TestCase):
    """Whether the current action is working has to be judged on recent ground.

    Pinned to run-20260923T114945Z: Mario held right_jump against the pipe at
    x=594 for 126 decisions while recent_control reported 158 pixels gained and
    an outcome of "advanced" -- ground covered before he ever reached the wall.
    Nothing in the state ever contradicted the choice, so it never changed.
    """

    def ground(self) -> bytearray:
        ram = bytearray(0x0800)
        for column in range(16):
            ram[0x0500 + 5 * 16 + column] = 1
        return ram

    def info(self, x: int) -> dict[str, object]:
        return {"world": 1, "stage": 1, "area": 1, "x_pos": x, "y_pos": 80,
                "y_pixel": 80, "progress": x, "time": 390, "life": 2, "status": "small"}

    def test_progress_earned_before_a_wall_stops_counting_at_the_wall(self) -> None:
        ram = self.ground()
        parser = MarioStateParser()
        advancing = None
        for x in range(400, 601, 25):  # run up to the wall
            advancing = parser.parse(self.info(x), ram, previous_action="right_jump",
                                     frames_elapsed=8)
        assert advancing is not None
        self.assertGreater(advancing.recent_progress_pixels, 0)

        for _ in range(10):  # then hold the same action against it
            stuck = parser.parse(self.info(600), ram, previous_action="right_jump",
                                 frames_elapsed=8)

        self.assertEqual(stuck.recent_progress_pixels, 0)
        state = stuck.to_state()
        self.assertEqual(state["recent_control"]["progress_gained_pixels"], 0)
        self.assertEqual(
            state["recent_control"]["outcome"],
            "blocked",
            "a held action that gains nothing recently is blocked, however far it once got",
        )

    def test_an_action_that_is_still_moving_mario_reads_as_advanced(self) -> None:
        ram = self.ground()
        parser = MarioStateParser()
        last = None
        for x in range(400, 601, 25):
            last = parser.parse(self.info(x), ram, previous_action="right_run",
                                frames_elapsed=8)
        assert last is not None
        self.assertEqual(last.to_state()["recent_control"]["outcome"], "advanced")


if __name__ == "__main__":
    unittest.main()


class GroundVisibilityTests(unittest.TestCase):
    """Falling into a pit must not read as the clearest possible path.

    Pinned to run-20260923T120017Z, where all three episodes ended in a pit.
    On every falling decision the grid held no ground at all, so neither an
    obstacle nor a gap was found and clear_forward_tiles reported its maximum
    of 8 -- "clear for eight tiles" -- while Mario dropped off the screen.
    """

    def snapshot_over(self, grid: tuple[str, ...]) -> dict[str, object]:
        from typesafe_mario.state import MarioSnapshot

        snap = MarioSnapshot(
            goal="", world=1, stage=1, area=1, x=1000, y=126, dx=2, dy=-4,
            direction="moving_right", vertical_motion="falling", airborne=True,
            status="small", player_state=8, lives=2, coins=0, score=0, time_left=300,
            progress=1000, best_progress=1000, stalled_steps=0, grounded=False,
            jump_phase="falling", local_grid=grid,
        )
        return snap.navigation_features()

    def test_no_ground_below_is_unknown_not_clear(self) -> None:
        empty = ("...........",) * 4 + ("..M........",) + ("...........",) * 4
        terrain = self.snapshot_over(empty)

        self.assertIsNone(
            terrain["clear_forward_tiles"],
            "eight tiles of clearance was reported while Mario fell into a pit",
        )
        self.assertFalse(terrain["ground_below_visible"])
        self.assertIn("pit", str(terrain["summary"]))

    def test_ground_below_still_measures_the_path_ahead(self) -> None:
        standing = ("...........",) * 4 + ("..M........", "###########") + ("...........",) * 3
        terrain = self.snapshot_over(standing)

        self.assertTrue(terrain["ground_below_visible"])
        self.assertEqual(terrain["clear_forward_tiles"], 8)


class GapMeasurementTests(unittest.TestCase):
    """A gap has to be measured, not just noticed.

    Pinned to run-20260923T120017Z, whose three episodes all ended in a pit.
    Standing on a pipe at x=916 the state reported a seven-tile gap two tiles
    ahead, because a column counted as a gap unless it had ground at exactly
    the height of the pipe top. Mario committed to crossing eight tiles, which
    no jump reaches, and Jev was told that was the situation for every frame of
    the fall that followed.
    """

    def terrain(self, grid: tuple[str, ...]) -> dict[str, object]:
        from typesafe_mario.state import MarioSnapshot

        return MarioSnapshot(
            goal="", world=1, stage=1, area=1, x=916, y=143, dx=2, dy=0,
            direction="moving_right", vertical_motion="level_or_grounded", airborne=False,
            status="small", player_state=8, lives=2, coins=0, score=0, time_left=300,
            progress=916, best_progress=916, stalled_steps=0, grounded=True,
            jump_phase="grounded", local_grid=grid,
        ).navigation_features()

    def pad(self, *rows: str) -> tuple[str, ...]:
        blank = "." * 15
        return (blank,) * 4 + rows + (blank,) * (8 - len(rows))

    def test_lower_ground_beyond_a_pipe_is_not_a_pit(self) -> None:
        on_a_pipe = self.pad(
            "..M............",
            "..###..........",
            "..###..........",
            "..#############",
        )
        terrain = self.terrain(on_a_pipe)

        self.assertFalse(terrain["gap_ahead"], "ground three rows down is still ground")
        self.assertEqual(terrain["gap_crossing_outlook"], "no_gap")

    def test_a_real_pit_is_measured_to_its_far_side(self) -> None:
        three_wide = self.pad(
            "..M............",
            "####...########",
        )
        terrain = self.terrain(three_wide)

        self.assertTrue(terrain["gap_ahead"])
        self.assertEqual(terrain["gap_width_tiles_visible"], 3)
        self.assertTrue(terrain["gap_far_side_visible"])
        self.assertEqual(terrain["gap_crossing_outlook"], "clearable")

    def test_a_pit_no_jump_crosses_is_told_apart_from_one_that_is_routine(self) -> None:
        seven_wide = self.pad(
            "..M............",
            "####.......####",
        )
        terrain = self.terrain(seven_wide)

        self.assertEqual(terrain["gap_width_tiles_visible"], 7)
        self.assertEqual(terrain["gap_crossing_outlook"], "too_wide")

    def test_a_gap_running_past_the_window_is_a_lower_bound_not_a_width(self) -> None:
        open_ended = self.pad(
            "..M............",
            "####...........",
        )
        terrain = self.terrain(open_ended)

        self.assertFalse(terrain["gap_far_side_visible"])
        self.assertEqual(terrain["gap_crossing_outlook"], "far_side_not_visible")

    def test_two_separate_pits_are_not_merged_into_one_impossible_gap(self) -> None:
        two_pits = self.pad(
            "..M............",
            "####..####..###",
        )
        terrain = self.terrain(two_pits)

        self.assertEqual(
            terrain["gap_width_tiles_visible"], 2, "the width ends at the first ground beyond"
        )
        self.assertEqual(terrain["gap_crossing_outlook"], "clearable")


class EnemyVisibilityTests(unittest.TestCase):
    """A slot holds an enemy when its active flag says so, not when its type is non-zero.

    Pinned to the death that ended four of ten runs at x=1656-1674. The frame
    shows a green koopa troopa touching Mario. Its slot was active and 10px
    ahead, but its type is 0x00, which the parser skipped as an empty slot, so
    the state reported two goombas behind Mario and nothing else -- flat ground,
    no gap, no contact projected -- on the decision that killed him.
    """

    def ram_with(self, slot: int, kind_id: int, active: int, x: int, y: int) -> bytearray:
        ram = bytearray(0x0800)
        for column in range(16):
            ram[0x0500 + 5 * 16 + column] = 1
        ram[0x000F + slot] = active
        ram[0x0016 + slot] = kind_id
        ram[0x006E + slot] = x // 256
        ram[0x0087 + slot] = x % 256
        ram[0x00CF + slot] = y
        return ram

    def info(self) -> dict[str, object]:
        return {"world": 1, "stage": 1, "area": 1, "x_pos": 100, "y_pos": 80,
                "y_pixel": 80, "progress": 100, "time": 390, "life": 2, "status": "small"}

    def test_a_green_koopa_is_an_enemy_not_an_empty_slot(self) -> None:
        ram = self.ram_with(slot=1, kind_id=0x00, active=1, x=140, y=88)
        snapshot = MarioStateParser().parse(self.info(), ram)

        kinds = [enemy.kind for enemy in snapshot.enemies]
        self.assertEqual(kinds, ["green_koopa_troopa"])
        self.assertEqual(snapshot.to_state()["hazard"]["nearest_enemy_distance_pixels"], 40)

    def test_an_inactive_slot_is_ignored_however_its_type_reads(self) -> None:
        ram = self.ram_with(slot=3, kind_id=0x06, active=0, x=140, y=88)
        snapshot = MarioStateParser().parse(self.info(), ram)

        self.assertEqual(snapshot.enemies, ())

    def test_a_goomba_is_still_seen(self) -> None:
        ram = self.ram_with(slot=0, kind_id=0x06, active=1, x=142, y=88)
        snapshot = MarioStateParser().parse(self.info(), ram)

        self.assertEqual([e.kind for e in snapshot.enemies], ["goomba"])


class ForwardReachTests(unittest.TestCase):
    """Every forward measurement is bounded by the window, so its width is a unit.

    Widening the forward reach from eight tiles to twelve, to measure gaps that
    ran past the edge, cost more than any other change made that day: over ten
    seeds each the median run fell from 1790 to 692 and early deaths rose from
    40% to 64%. Nothing was reported wrongly -- the scale of every forward
    number just changed underneath a strategy written against the old one.
    """

    def test_the_forward_reach_is_eight_tiles(self) -> None:
        ram = bytearray(0x0800)
        for column in range(16):
            ram[0x0500 + 5 * 16 + column] = 1
        info = {"world": 1, "stage": 1, "area": 1, "x_pos": 100, "y_pos": 80,
                "y_pixel": 80, "progress": 100, "time": 390, "life": 2, "status": "small"}

        snapshot = MarioStateParser().parse(info, ram)

        self.assertEqual(len(snapshot.local_grid[0]), 11, "two tiles behind plus eight ahead")
        self.assertLessEqual(
            snapshot.to_state()["terrain"]["clear_forward_tiles"] or 0,
            8,
            "clear_forward_tiles saturates at the reach, and its ceiling is part of its meaning",
        )

class HighPlatformTests(unittest.TestCase):
    def scene(self, lower_ground):
        from dataclasses import replace
        ram = bytearray(0x800)
        # Mario at screen y=48, platform surface at y=80; ground at y=208.
        for column in (6, 7):
            ram[0x500 + 3 * 16 + column] = 1
        if lower_ground:
            for column in range(16):
                ram[0x500 + 11 * 16 + column] = 1
        parser = MarioStateParser()
        grid = parser._extract_local_grid(ram, 100, 48, ())
        snapshot = parser.parse(MarioStateParserTests().base_info())
        return replace(snapshot, local_grid=tuple(grid), grounded=True, enemies=())

    def test_high_platform_can_see_lower_ground_and_advance(self):
        from typesafe_mario.continuous_skills import catalog
        s = self.scene(True)
        self.assertIsNone(s.navigation_features()['gap_distance_tiles'])
        self.assertIn('Advance', [c.name for c in catalog(s)])

    def test_real_pit_below_high_platform_remains_a_gap(self):
        from typesafe_mario.continuous_skills import catalog
        s = self.scene(False)
        self.assertEqual(s.navigation_features()['gap_distance_tiles'], 2)
        self.assertNotIn('Advance', [c.name for c in catalog(s)])
