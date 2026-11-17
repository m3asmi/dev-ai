"""The owner's rule: secret-bearing content never goes to another service. The review sends the
patch to a provider and `land` would commit it, so such a patch fails its check and is refused a review,
which needs no check. No real secret here."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_review import PASS, reviewer_says

from devai import commands, review
from devai.task import TaskError

HEADERS = {  # split so that no key header sits in this file
    "src/keys.py": "-----BEGIN RSA " + "PRIVATE KEY-----",
    "src/pgp.py": "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----",  # missed until 0.18.3 (it-ai, 2026-10-13)
}


@pytest.mark.parametrize(("name", "secret"), [
    (".env", True), ("config/.env.local", True), ("deploy/server.pem", True), ("odoo-prod.conf", True),
    ("home/id_ed25519", True), ("src/keys.py", True), ("src/pgp.py", True),  # the last two hold a PEM, a PGP header
    ("odoo.conf.example", False), ("src/environment.py", False)])
def test_a_secret_bearing_patch_fails_its_check_and_never_reaches_a_reviewer(
    repo: Path, monkeypatch: pytest.MonkeyPatch, name: str, secret: bool) -> None:
    task = commands.start(repo, "fix-answer", "make the answer right", ["*"], None, "claude", author_model="m")
    target = Path(task.worktree) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    body = f'KEY = """{HEADERS[name]}"""\n' if name in HEADERS else "x = 1\n"
    target.write_text(body, encoding="utf-8")
    result = commands.check(target.parent, "fix-answer")
    assert result["blocker_kinds"] == (["secret_in_patch"] if secret else [])
    if secret:
        assert result["tests"] is None and ".gitignore" in result["blockers"][0]
        calls = reviewer_says(monkeypatch, PASS)
        with pytest.raises(TaskError, match="secret-bearing") as refused:
            review.run(target.parent, "fix-answer", None, "gpt-6-sol")
        assert refused.value.kind == "secret_in_patch" and calls == []  # nothing left this machine
