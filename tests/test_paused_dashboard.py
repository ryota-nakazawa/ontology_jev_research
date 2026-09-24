import io
import unittest
from concurrent.futures import Future
from unittest.mock import patch

from test_contact import snapshot

from typesafe_mario.actions import ACTION_TO_INDEX, Action
from typesafe_mario.dashboard import DashboardCommand
from typesafe_mario.policy import Decision
from typesafe_mario.runner import _run_realtime_dashboard


class PausedDashboardTests(unittest.TestCase):
    def test_waiting_keeps_game_and_observation_clock_frozen(self):
        future = Future()
        steps = []
        parses = []
        class Executor:
            def __init__(self, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def submit(self, *args): return future
        class Env:
            ram = None
            def step(self, action):
                steps.append(action)
                return None, 0, len(steps) == 2, False, {}
        class Parser:
            def parse(self, *args, **kw):
                parses.append(kw)
                return snapshot(dead=False, clear=False)
        case = self
        class Display:
            calls = 0
            def draw(self, *args, **kw):
                self.calls += 1
                if self.calls <= 3:
                    case.assertEqual(steps, [])
                    case.assertEqual(len(parses), 1)
                if self.calls == 3:
                    future.set_result(Decision(Action.RIGHT, 1, {'right': 1}, 250))
                if kw['run_ended']: return DashboardCommand.QUIT
                case.assertLess(self.calls, 10)
                return DashboardCommand.CONTINUE
        with patch('typesafe_mario.runner.ThreadPoolExecutor', Executor):
            _run_realtime_dashboard(env=Env(), dashboard=Display(),
                policy=type('Policy', (), {'choose': lambda *a: None})(),
                parser=Parser(), frame=None, info={}, log=io.StringIO(),
                frames_per_decision=8, max_decisions=10, screenshot_path=None,
                pause_while_thinking=True)
        self.assertEqual(steps, [ACTION_TO_INDEX[Action.RIGHT]] * 2)
        self.assertTrue(all(p['previous_response_delay_frames'] == 0 for p in parses))
