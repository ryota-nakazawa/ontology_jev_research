"""Direct TypeSafe or automatic transport over a private Node subprocess."""

from __future__ import annotations

import json
import selectors
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def decode_response(payload: dict[str, Any]) -> SimpleNamespace:
    if "error" in payload:
        error = payload["error"]
        raise RuntimeError(f"Jev ({error.get('status')}): {error['message']}")
    return SimpleNamespace(
        route=payload.get("route"),
        answers={key: SimpleNamespace(**answer) for key, answer in payload["answers"].items()}
    )


class GatewayClient:
    def __init__(self, *, route: str = "auto") -> None:
        if route not in {"auto", "direct"}:
            raise ValueError("route must be auto or direct")
        root = Path(__file__).resolve().parents[2]
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node.js 22 or newer is required.")
        self._process = subprocess.Popen(
            [node, f"--env-file={root / '.env'}", str(root / "gateway/worker.mjs"),
             *(["--direct"] if route == "direct" else [])],
            cwd=root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    def system_one(self, *, state: Any, questions: dict[str, Any]) -> SimpleNamespace:
        process = self._process
        assert process.stdin is not None and process.stdout is not None
        request = {
            "state": state,
            "questions": {
                key: value.model_dump(exclude_none=True) for key, value in questions.items()
            },
        }
        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=25):
                    self.close()
                    raise RuntimeError("Jev request timed out; the worker was stopped.")
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("Gateway worker stopped. Check .env and run npm ci.")
            return decode_response(json.loads(line))
        except (BrokenPipeError, json.JSONDecodeError) as exc:
            self.close()
            raise RuntimeError("Gateway worker communication failed.") from exc

    def close(self) -> None:
        process = self._process
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()
