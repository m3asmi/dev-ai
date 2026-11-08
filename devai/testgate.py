"""The host runs the project's own tests on the exact patch. Never the model."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = 1800
GRACE_S = 10  # after SIGTERM: a script's EXIT trap, an Odoo closing its cursors; then SIGKILL
POLL_S = 15  # how often a running suite asks whether the patch moved under it


def run(command: str, worktree: Path, slug: str, log_path: Path, timeout_s: int,
        moved: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    """Run `command` with the worktree as working directory, in a process group of its own.

    `DEV_AI_WORKTREE` is exported so a test command can prove it loads the code
    of the patch and not of the main checkout — a run once lost three hours to
    tests importing the wrong tree. The timeout ends the whole group: killing the
    shell alone left `sleep` running and the script's EXIT trap unrun (probe of
    2026-09-22), which for Odoo is a server left alive on its test database. A patch
    that `moved` ends it too: its verdict is void, and its run held a machine (point 6c).
    """
    env = {**os.environ, "DEV_AI_WORKTREE": str(worktree), "DEV_AI_TASK": slug}
    started = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log, subprocess.Popen(command, shell=True, cwd=worktree, env=env, stdout=log,
                                                       stderr=subprocess.STDOUT, start_new_session=True) as process:
        exit_code: int | None = None
        left: float = timeout_s  # asked after each read of the patch, which can take a while (codex)
        try:  # a Ctrl-C ends the group too: its own session no longer hears the terminal's, and it goes up
            while exit_code is None and not moved() and (left := started + timeout_s - time.monotonic()) > 0:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    exit_code = process.wait(timeout=min(POLL_S, left))
        finally:
            if exit_code is None:
                _end(process)
    return {
        "command": command,
        "exit_code": 124 if exit_code is None and left <= 0 else exit_code,  # None: stopped, the patch moved
        "timed_out": exit_code is None and left <= 0,
        "duration_s": round(time.monotonic() - started, 1),
        "log": str(log_path),
    }


def _end(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM to the whole group, so bash runs its EXIT trap and Odoo stops as on Ctrl-C; whatever of the group
    is still there after GRACE_S, or when a Ctrl-C cuts the grace short, gets SIGKILL. The shell's exit says
    nothing about its children, and a group already gone is no error: all from this task's reviews."""
    deadline = time.monotonic() + GRACE_S
    try:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=GRACE_S)  # reaped: a zombie leader would count as present below
        while time.monotonic() < deadline and _present(process.pid):
            time.sleep(0.05)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def _present(pgid: int) -> bool:
    """Whether any process of the group is left: signal 0 asks without touching."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True
