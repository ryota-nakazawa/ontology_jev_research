"""All candidates share the already-held input until the response arrives."""
import unittest

from test_contact import LEVEL_WITH_MARIO, STANDING, snapshot

from typesafe_mario.state import EnemyObservation


class HeldInputRegression(unittest.TestCase):
    def test_collision_before_response_is_identical_for_every_candidate(self):
        snap = snapshot(grounded=True, dy=0, dx=24, frames_since_previous=8,
                        local_grid=STANDING, previous_action='right_run',
                        last_response_delay_frames=16)
        object.__setattr__(snap, 'enemies', (EnemyObservation(
            slot=0, kind_id=6, kind='goomba', dx_pixels=40,
            dy_pixels=LEVEL_WITH_MARIO, relative_velocity_x=-3),))
        outlook = snap.action_outlook()
        reference = outlook['right_run']
        self.assertEqual(reference['contact_kind'], 'side_hit')
        self.assertLessEqual(reference['contact_frames'], 16)
        for action, prediction in outlook.items():
            with self.subTest(action=action):
                self.assertEqual(prediction, reference)
