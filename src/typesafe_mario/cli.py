from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .policy import HeuristicPolicy, TypeSafePolicy
from .runner import run_episode
from .state import MarioStateParser


def _demo_ram() -> bytearray:
    ram = bytearray(0x0800)
    # Mario position and one goomba ahead.
    ram[0x006D] = 0
    ram[0x0086] = 172
    ram[0x000F] = 1
    ram[0x0016] = 0x06
    ram[0x006E] = 0
    ram[0x0087] = 214
    ram[0x00CF] = 79
    # Fill the tile-map row immediately below Mario with solid ground.
    ground_row = (79 + 16 - 32) // 16
    for column in range(16):
        ram[0x0500 + ground_row * 16 + column] = 1
    return ram


def state_demo() -> int:
    info = {
        "world": 1,
        "stage": 1,
        "area": 1,
        "x_pos": 172,
        "y_pos": 79,
        "y_pixel": 79,
        "left_x_pos": 60,
        "progress": 172,
        "progress_max": 172,
        "status": "small",
        "player_state": 8,
        "life": 2,
        "coins": 0,
        "score": 200,
        "time": 387,
        "death": False,
        "clear": False,
    }
    snapshot = MarioStateParser().parse(info, _demo_ram(), previous_action="right")
    print(json.dumps(snapshot.to_state(), indent=2))
    print("\n--- TEXT VIEW ---\n")
    print(snapshot.to_text())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="typesafe-mario")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("state-demo", help="Show structured and text state without API calls")

    play = subparsers.add_parser("play", help="Run a Mario episode")
    play.add_argument("--env", default="SuperMarioBros-1-1-v0")
    play.add_argument(
        "--frames-per-decision",
        type=int,
        default=8,
        help="Minimum macro duration in emulator frames",
    )
    play.add_argument("--max-decisions", type=int, default=2000)
    play.add_argument("--seed", type=int, default=123)
    play.add_argument("--until-game-over", action="store_true",
                      help="With --skills, continue through decision limits, stalls and skill failures")
    play.add_argument("--interactive-session", action="store_true",
                      help="Keep continuous dashboard open; Restart starts a fresh episode")
    play.add_argument("--skip-flower-visit", action="store_true", help="Disable registered flower visit")
    play.add_argument("--skip-fire-skill", action="store_true", help="Disable deliberate stationary firing skill")
    play.add_argument("--skip-opening-powerup", action="store_true", help="Disable the optional registered opening powerup visit for comparison")
    play.add_argument("--continuous-skills", action="store_true",
                      help="Non-blocking semantic skills over the whole game, including handoffs")
    play.add_argument("--skills", action="store_true",
                      help="Experimental paused-decision feedback skills with per-frame logs")
    play.add_argument("--policy", choices=("typesafe", "direct", "vercel", "heuristic"), default="typesafe")
    play.add_argument(
        "--display",
        choices=("dashboard", "game", "none"),
        default="dashboard",
        help="Combined telemetry dashboard, plain game window, or headless mode",
    )
    play.add_argument(
        "--pause-while-thinking", action="store_true",
        help="Freeze the dashboard game during inference to isolate policy from response delay",
    )
    play.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    play.add_argument(
        "--screenshot",
        type=Path,
        help="Save the first populated dashboard frame as a PNG",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "state-demo":
        return state_demo()
    if args.command == "play":
        if args.until_game_over and not (args.skills or args.continuous_skills):
            raise SystemExit('--until-game-over requires --skills or --continuous-skills')
        if args.interactive_session and (not args.continuous_skills or args.display != "dashboard"):
            raise SystemExit("--interactive-session requires --continuous-skills --display dashboard")
        policy_class = TypeSafePolicy
        if args.continuous_skills:
            if args.policy == 'heuristic':
                raise SystemExit('--continuous-skills requires a Jev policy')
            from .skill_policy import TypeSafeSkillPolicy
            policy_class = TypeSafeSkillPolicy
        if args.policy in {"vercel", "direct"}:
            from .gateway import GatewayClient

            policy = policy_class(client=GatewayClient(
                route="direct" if args.policy == "direct" else "auto"))
        else:
            policy = policy_class() if args.policy == "typesafe" else HeuristicPolicy()
        if args.continuous_skills:
            from .continuous_runner import run_continuous_episode
            control = {} if args.interactive_session else None
            while True:
                log_path = run_continuous_episode(
                    env_id=args.env, policy=policy, seed=args.seed,
                    max_decisions=args.max_decisions, artifacts_dir=args.artifacts_dir,
                    display=args.display, until_game_over=args.until_game_over,
                    pursue_opening_powerup=not args.skip_opening_powerup,
                    pursue_flower=not args.skip_flower_visit, use_fire_skill=not args.skip_fire_skill,
                    session_control=control,
                )
                print(f"Continuous skill log: {log_path.resolve()}")
                if control is None or not control.get('restart'):
                    break
                if args.policy in {"vercel", "direct"}:
                    policy = policy_class(client=GatewayClient(
                        route="direct" if args.policy == "direct" else "auto"))
                else:
                    policy = policy_class()
            return 0
        if args.skills:
            from .skill_runner import run_skill_episode
            log_path = run_skill_episode(
                env_id=args.env, policy=policy, frames_per_decision=args.frames_per_decision,
                max_decisions=args.max_decisions, seed=args.seed,
                artifacts_dir=args.artifacts_dir, display=args.display,
                until_game_over=args.until_game_over,
            )
            print(f"Skill run log: {log_path.resolve()}")
            return 0
        log_path = run_episode(
            env_id=args.env,
            policy=policy,
            frames_per_decision=args.frames_per_decision,
            max_decisions=args.max_decisions,
            seed=args.seed,
            artifacts_dir=args.artifacts_dir,
            display=args.display,
            screenshot_path=args.screenshot,
            pause_while_thinking=args.pause_while_thinking,
        )
        print(f"Run log: {log_path.resolve()}")
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
