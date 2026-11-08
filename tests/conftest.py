from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SUITE_BUDGET_S = 60
_started = time.monotonic()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """The suite stays fast or it fails: a slow suite is one nobody runs."""
    elapsed = time.monotonic() - _started
    if elapsed > SUITE_BUDGET_S and exitstatus == 0:
        print(f"\nSUITE BUDGET EXCEEDED: {elapsed:.0f}s > {SUITE_BUDGET_S}s")
        session.exitstatus = 1


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed repository whose test command passes."""
    ((root := tmp_path / "project") / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def answer():\n    return 41\n", encoding="utf-8")
    (root / "src" / "legacy.py").write_text("password = load_secret()\n", encoding="utf-8")
    (root / "dev-ai.json").write_text(json.dumps({"test_command": "true"}), encoding="utf-8")
    sh(root, "sh", "-c", "git init -q -b main && git config user.email dev-ai@example.invalid")
    sh(root, "sh", "-c", "git config user.name 'dev-ai test' && git add . && git commit -qm base")
    return root


def set_test_command(root: Path, command: str) -> None:
    """Change the committed test command, as a repository owner would."""
    (root / "dev-ai.json").write_text(json.dumps({"test_command": command}), encoding="utf-8")
    sh(root, "git", "commit", "-qam", "test command")
