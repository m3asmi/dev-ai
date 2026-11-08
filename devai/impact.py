"""What in a patch needs another model's eyes, and what must never reach one.

Any change of behaviour — code, tests, configuration, and the instructions an agent
reads — gets one independent review; only descriptive documentation is exempt. The
word list this replaces (dev-pipeline's `security_impact.py`, on added lines) fired
on `token` and not on its French equivalent, and could not see a guard being removed:
on this repository, b2539df took a confirmation out and was classified neutral.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_DESCRIPTIVE = {".md", ".rst", ".adoc"}
# Prose an agent executes is not descriptive: harness instructions, skills, rules. Codex reads
# AGENTS.override.md ahead of AGENTS.md (codex, reviewing this patch).
_INSTRUCTIONS = re.compile(
    r"(?i)(?:^|/)(?:agents(?:[.]override)?|claude(?:[.]local)?|gemini|skill|copilot-instructions)[.]md$"
    r"|(?:^|/)[.](?:claude|codex|cursor|github|opencode|agents)/|[.](?:cursor|windsurf)rules$"
)
# The owner's deny list: files that never go to another service, nor into a commit.
_SECRET_FILE = re.compile(
    r"(?i)^(?:[.]env(?:[.][^/]*)?|[^/]*[.](?:pem|ppk)|id_(?:rsa|ed25519|ecdsa|dsa)|[.]netrc|[.]pgpass|"
    r"odoo[^/]*[.]conf|pg_hba[.]conf|userlist[.]txt)$"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")  # PEM, and PGP's armor


def secret_bearing(paths: list[str], added: list[str]) -> list[str]:
    """What must never reach a reviewer or a commit: a file from the deny list, or a
    PEM or PGP private-key header among the added lines. No scanner beyond that."""
    found = [path for path in paths if _SECRET_FILE.match(PurePosixPath(path).name)]
    if any(_PRIVATE_KEY.search(line) for line in added):
        found.append("a private key among the added lines")
    return found


def needs_review(paths: list[str]) -> list[str]:
    """The changed paths that are not descriptive documentation; empty means docs only.
    Judged on paths, whatever the lines say and in whatever language, deletions included."""
    return [
        path for path in paths
        if PurePosixPath(path).suffix.lower() not in _DESCRIPTIVE or _INSTRUCTIONS.search(path)
    ]
