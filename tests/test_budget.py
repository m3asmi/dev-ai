"""The budget is a test, so exceeding it is a red suite and not a good intention.

dev-ai replaces a pipeline that grew to 52 000 lines of scripts, 466 settings
and a test suite that no longer finished in ninety minutes. Adding here means
removing somewhere. Raising a limit is a decision to take on purpose, in a
commit that says why.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from devai.task import KINDS

ROOT = Path(__file__).resolve().parents[1]
MAX_CODE_LINES = 1640  # 1600, 1620 for `dev-ai clean` (2026-09-28), 1640 for opencode (2026-10-27): the owner's
MAX_TEST_LINES = 2000
MAX_SETTINGS = 10
MAX_REVIEW_LINES = 260  # 250 until opencode came back, the owner's decision of 2026-10-27
MAX_DOC_LINES = 705  # raised from 700 on 2026-09-28 for `dev-ai clean`, the owner's decision; see the commit


def _lines(directory: Path, pattern: str = "*.py") -> int:
    return sum(len(path.read_text(encoding="utf-8").splitlines()) for path in directory.rglob(pattern))


def test_code_stays_within_its_line_budget() -> None:
    """Code is not only `devai/`: a shell script that installs the tool is code too,
    and a budget a reviewer can route around by writing bash is not a budget."""
    assert _lines(ROOT / "devai") + _lines(ROOT / "scripts", "*.sh") <= MAX_CODE_LINES
    assert len((ROOT / "devai" / "review.py").read_text(encoding="utf-8").splitlines()) <= MAX_REVIEW_LINES


def test_tests_stay_within_their_line_budget() -> None:
    assert _lines(ROOT / "tests") <= MAX_TEST_LINES


def test_docs_stay_within_their_line_budget() -> None:
    docs = [ROOT / "README.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").glob("*.md"))]
    assert sum(len(path.read_text(encoding="utf-8").splitlines()) for path in docs) <= MAX_DOC_LINES


def _is_config(node: ast.AST | None) -> bool:
    called = getattr(node, "func", None)
    return isinstance(node, ast.Call) and getattr(called, "id", getattr(called, "attr", "")) == "config"


def _settings(python: list[str], shell: str = "") -> set[str]:
    """Configuration keys and environment names. The keys are read from the syntax tree: a literal key taken by
    `.get("key")` or by `["key"]` from `config(<anything>)`, from a name it was assigned to, or from `settings`.
    A pattern that knew `config(root).get` alone let `review_timeout`, read through
    `config(gitops.main_root(worktree))`, escape the count (2026-09-29). A key that is no literal, or a
    configuration handed on under another name, is not seen: a count of text follows no value."""
    keys: set[str] = set()
    for nodes in (list(ast.walk(ast.parse(source))) for source in python):
        held = {"settings"} | {
            target.id for node in nodes if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
            and _is_config(node.value) for target in getattr(node, "targets", [getattr(node, "target", None)])
            if isinstance(target, ast.Name)}
        for node in nodes:
            if isinstance(node, ast.Subscript):
                read, key = node.value, node.slice
            elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get" and node.args:
                read, key = node.func.value, node.args[0]
            else:
                continue
            literal = isinstance(key, ast.Constant) and isinstance(key.value, str)
            if literal and (_is_config(read) or getattr(read, "id", "") in held):
                keys.add(key.value)
    text = "\n".join([*python, shell])
    env = set(re.findall(r"\bDEV_AI_[A-Z_]+", text))
    env |= set(re.findall(r"""os\.environ(?:\.get\(|\[)\s*["']([A-Z_]+)["']""", text))
    return keys | env


def test_settings_stay_few() -> None:
    """A knob is a knob whatever reads it. Every `DEV_AI_*` name counts, in the shell that
    installs the tool as in the Python that runs it, whether the tool reads it or exports it:
    dev-pipeline reached 466 settings one uncounted variable at a time."""
    python = [path.read_text(encoding="utf-8") for path in sorted((ROOT / "devai").rglob("*.py"))]
    shell = "\n".join(path.read_text(encoding="utf-8") for path in sorted((ROOT / "scripts").rglob("*.sh")))
    names = _settings(python, shell)
    assert len(names) <= MAX_SETTINGS, sorted(names)


def test_a_setting_is_counted_whatever_reads_it() -> None:
    """The read that escaped, as `devai/review.py` writes it, and its siblings: a subscript, and a name the
    configuration was assigned to (codex, reviewing this test). What names no setting is left out."""
    read = ('config(gitops.main_root(worktree)).get("review_timeout")\ntask.config(root)["far"]\n'
            'held = config(root)\nheld.get("kept")\nsettings["plain"]\n')
    left_out = 'other(x).get("no_setting")\nconfig(root).get(name)\nheld[0]\nrows["state"]\n'
    assert _settings([read + left_out]) == {"review_timeout", "far", "kept", "plain"}


def test_every_blocker_kind_is_registered_and_every_registered_kind_is_used() -> None:
    """`KINDS` is the full list, so the log can show a check that never fired — how dev-pipeline
    kept a council that changed 0 of 22 outcomes. Read from the syntax tree, not at run time:
    a typo must fail this suite, never turn a blocker into a crash."""
    used: set[str] = set()
    for path in (ROOT / "devai").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name == "TaskError" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                used.add(node.args[1].value)
            if name == "append" and getattr(node.func.value, "id", "") == "blockers":
                used.add(node.args[0].elts[0].value)
    assert used == set(KINDS) and len(KINDS) == len(set(KINDS))


def test_no_model_is_called_outside_the_review() -> None:
    """Orchestration is deterministic code. The one place a model may be invoked
    is the cross-model review."""
    for path in (ROOT / "devai").rglob("*.py"):
        if path.name == "review.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"""["'](?:claude|codex|gemini|opencode)["']\s*,\s*["']-""", text), path.name
