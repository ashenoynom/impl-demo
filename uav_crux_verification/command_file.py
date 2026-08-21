"""Locked, multi-writer command file shared by streamer / receiver /
orchestrator / fault injector.

Shape:
  {
    "scenarios": { "<id>": {"id", "requirement_ext", "test_case_id",
                             "window_s", "queued_at"} },
    "acks":      { "<id>": {"id", "requirement_ext", "test_case_id",
                             "mode", "start_epoch", "end_epoch"} },
    "fault":     {"armed": bool, "requirement": str|null}
  }

Multiple scenarios can be active at once (parallel requirement trees touch
disjoint channel sets). Every mutation goes through locked_update() —
an fcntl.flock over a sidecar lock file — because five orchestrator threads,
the receiver, and the streamer all read-modify-write this file.
"""

from __future__ import annotations

import fcntl
import json
import pathlib
from contextlib import contextmanager
from typing import Any, Callable

COMMAND_PATH = pathlib.Path(__file__).parent / "uav_command_state.json"
LOCK_PATH = pathlib.Path(__file__).parent / ".uav_command_state.lock"


@contextmanager
def _lock():
    LOCK_PATH.touch(exist_ok=True)
    with open(LOCK_PATH) as lockfile:
        fcntl.flock(lockfile, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lockfile, fcntl.LOCK_UN)


def _read_unlocked() -> dict:
    try:
        return json.loads(COMMAND_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def read_state() -> dict:
    with _lock():
        return _read_unlocked()


def locked_update(mutate: Callable[[dict], Any]) -> Any:
    """Read-modify-write under the lock; mutate() may return a value."""
    with _lock():
        state = _read_unlocked()
        state.setdefault("scenarios", {})
        state.setdefault("acks", {})
        state.setdefault("fault", {"armed": False, "requirement": None})
        result = mutate(state)
        COMMAND_PATH.write_text(json.dumps(state, indent=2))
        return result
