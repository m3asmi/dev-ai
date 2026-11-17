"""Installer tests use a temporary HOME; they never read the operator's settings."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import sh

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT, CODEX_RULES = ROOT / "scripts" / "install.sh", ROOT / "scripts" / "dev-ai.rules"
ALLOW_LAND_RULES = ROOT / "scripts" / "dev-ai-allow-land.rules"
ASKED = {f"dev-ai {verb} *": "ask" for verb in ("land", "drop", "clean", "init")}  # opencode: merges, destroys
SETTINGS = {"permissions": {"deny": ["Bash(rm:*)"], "allow": ["Bash(ls:*)", "Bash(dev-ai:*)"]}}
OPENCODE = {"permission": {"bash": {"rm *": "deny", "dev-ai *": "allow"}}}


def install(repo: Path, home: Path, tmp_path: Path, *args: str, path: str = "",
            answers: str = "") -> subprocess.CompletedProcess[str]:
    env = {"PATH": path or os.environ["PATH"], "HOME": str(home), "DEV_AI_BIN": str(tmp_path / "bin" / "dev-ai")}
    return subprocess.run(["bash", "scripts/install.sh", *args], cwd=repo, env=env, input=answers,  # none on stdin:
                          capture_output=True, text=True, timeout=60)  # every question keeps its default


@pytest.fixture
def home(repo: Path, tmp_path: Path) -> Path:
    """main with the script and the skill, no tag; a HOME with Claude Code, codex and opencode as a release left it."""
    (repo / "scripts").mkdir()
    for source in (INSTALL_SCRIPT, CODEX_RULES, ALLOW_LAND_RULES):
        shutil.copy(source, repo / "scripts" / source.name)
    for skill in (repo / "docs" / "skill.md", repo / "skills" / "frame-task" / "SKILL.md"):
        skill.parent.mkdir(parents=True), skill.write_text(f"# the skill in {skill.parent.name}\n", encoding="utf-8")
    sh(repo, "git", "add", "scripts", "docs", "skills")
    sh(repo, "git", "commit", "-qm", "installer")
    (repo / "docs" / "skill.md").write_text("# a half-edited skill\n", encoding="utf-8")
    path = tmp_path / "home"
    (path / ".claude").mkdir(parents=True)
    (path / ".codex").mkdir()  # installed, but with no prompts/ directory of its own yet
    (path / "dotfiles").mkdir()
    (path / "dotfiles" / "settings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
    (path / ".claude" / "settings.json").symlink_to(path / "dotfiles" / "settings.json")
    (path / ".config" / "opencode").mkdir(parents=True)
    (path / ".config" / "opencode" / "opencode.json").write_text(json.dumps(OPENCODE), encoding="utf-8")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "dai-land").symlink_to(tmp_path / "stable" / "bin" / "dev-ai")  # a release up to 0.5.0 made it
    return path


def snapshot(root: Path) -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir" for p in root.rglob("*")}


def test_the_dry_run_announces_everything_and_writes_nothing(repo: Path, home: Path, tmp_path: Path) -> None:
    before = snapshot(tmp_path)
    result = install(repo, home, tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    for announced in ("would link", "would copy"):
        assert announced in result.stdout, result.stdout
    for never in ("would grant", "granted", "would remove", "would write"):  # no permission, and nothing deleted
        assert never not in result.stdout, result.stdout
    assert snapshot(tmp_path) == before
    opted = install(repo, home, tmp_path, "--allow-land", "--dry-run", "--yes")
    assert opted.returncode == 0 and "dev-ai-allow-land.rules" in opted.stdout, opted.stdout
    assert snapshot(tmp_path) == before
    mistyped = install(repo, home, tmp_path, "--aply")  # a typo must not read as a done install
    assert mistyped.returncode == 1 and "usage:" in mistyped.stdout


def test_allow_land_installs_one_unambiguous_managed_rule(repo: Path, home: Path, tmp_path: Path) -> None:
    def judged(*command: str) -> str:  # codex's own checker over every rules file there, as a session loads them
        rules = [arg for path in sorted((home / ".codex/rules").glob("*.rules")) for arg in ("--rules", str(path))]
        return json.loads(subprocess.check_output(["codex", "execpolicy", "check", *rules, *command], timeout=30, env={
            "PATH": os.environ["PATH"], "HOME": str(home)}, stderr=subprocess.DEVNULL)).get("decision", "none")
    land = ("dev-ai", "land", "--task", "web-realtime-call", "--merge", "-m", "feat(web): add bounded calls")
    assert (asked := install(repo, home, tmp_path, "--yes")).returncode == 0
    assert (first := install(repo, home, tmp_path, "--allow-land", "--yes")).returncode == 0, first.stderr
    rules = (home / ".codex/rules/dev-ai.rules").read_text(encoding="utf-8")
    assert rules == ALLOW_LAND_RULES.read_text(encoding="utf-8") and rules.count('"land"') == 1
    assert 'pattern = ["dev-ai", "land"], decision = "allow"' in rules
    assert 'pattern = ["dev-ai", ["drop", "clean", "init"]], decision = "prompt"' in rules
    before = snapshot(tmp_path)
    assert (again := install(repo, home, tmp_path, "--allow-land", "--yes")).returncode == 0, again.stderr
    assert snapshot(tmp_path) == before
    assert install(repo, home, tmp_path, "--yes").returncode == 0 and snapshot(tmp_path) == before
    assert install(repo, home, tmp_path, "--prompt-land", "--yes").returncode == 0
    assert (home / ".codex/rules/dev-ai.rules").read_text(encoding="utf-8") == CODEX_RULES.read_text(encoding="utf-8")
    shutil.which("codex") or pytest.skip("codex's own policy checker judges what follows")
    assert judged(*land) == "prompt" and "BLOCKED where approvals are off" in asked.stdout  # the incident: never ran
    opted = install(repo, home, tmp_path, "--allow-land", "--yes")
    assert judged(*land) == "allow" and "aside; unproven" in opted.stdout and "BLOCKED" not in opted.stdout
    wrong = ("dev-ai landx", "dev-ai", "/usr/bin/dev-ai land", "env dev-ai land --merge")  # a prefix that gains nothing
    assert [judged(*w.split()) for w in wrong] == ["none"] * 4 and judged("dev-ai", "drop", "--destroy") == "prompt"
    (home / ".codex/rules/his.rules").write_text('prefix_rule(pattern = ["dev-ai", "land"], decision = "forbidden")\n')
    denied = install(repo, home, tmp_path, "--allow-land", "--yes")  # his denial stands, and is said
    assert judged(*land) == "forbidden" and "codex forbids a bare 'dev-ai land'" in denied.stdout, denied.stdout


def test_a_missing_context_tool_is_named_with_its_install_command_and_never_run(
    repo: Path, home: Path, tmp_path: Path) -> None:
    tools, ran = tmp_path / "tools", tmp_path / "claude-ran"
    tools.mkdir()
    for name, body in (("rtk", ""), ("claude", f"touch {ran}\n")):
        (tools / name).write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        (tools / name).chmod(0o755)
    result = install(repo, home, tmp_path, path=f"{tools}{os.pathsep}{os.environ['PATH']}")
    assert result.returncode == 0, result.stderr
    assert "rtk present" in result.stdout and "context-mode (Claude Code) missing" in result.stdout, result.stdout
    assert "claude plugin install context-mode@context-mode" in result.stdout
    assert not ran.exists(), "the installer ran the command it should only name"


def test_installing_does_what_it_announced_and_a_second_run_changes_nothing(
    repo: Path, home: Path, tmp_path: Path) -> None:
    (home / "dotfiles" / "settings.json").chmod(0o640)  # a copy swapped in, 0600: never wider (task 006)
    first = install(repo, home, tmp_path)
    assert first.returncode == 0, first.stderr
    assert (home / "dotfiles" / "settings.json").stat().st_mode & 0o777 == 0o600
    assert os.readlink(tmp_path / "bin" / "dev-ai") == str(repo / "bin" / "dev-ai")  # what lands runs (owner, 11-12)
    for where, name in ((where, name) for where in (".claude", ".agents", ".config/opencode")
                        for name in ("dev-ai", "frame-task")):
        source = "docs" if name == "dev-ai" else name  # its own file; codex reads ~/.agents/skills (its docs, 09-21)
        assert (home / where / "skills" / name / "SKILL.md").read_text(encoding="utf-8") == f"# the skill in {source}\n"
    assert not (home / ".codex" / "prompts").exists() and not (home / ".codex" / "skills").exists()
    codex = (home / ".codex" / "rules" / "dev-ai.rules").read_text(encoding="utf-8")  # read in every project
    assert codex == CODEX_RULES.read_text(encoding="utf-8") and [  # land merges: asked, as what destroys (2026-11-11)
        line.endswith('decision = "prompt")') for line in codex.splitlines() if '"land"' in line] == [True]
    opencode = json.loads((home / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
    assert opencode == {"permission": {"bash": {**OPENCODE["permission"]["bash"], **ASKED}}}
    verbs = [f"Bash(dev-ai {verb} *)" for verb in ("status", "start", "check", "scope-add", "review")]
    assert (home / ".claude" / "settings.json").is_symlink()
    assert json.loads((home / "dotfiles" / "settings.json").read_text(encoding="utf-8")) == {
        "permissions": {**SETTINGS["permissions"], "allow": [*SETTINGS["permissions"]["allow"], *verbs]},
        "sandbox": {"excludedCommands": ["dev-ai *"]}}
    assert not list(repo.glob(".codex/**/*")) and not (repo / ".claude").exists()  # nothing written per repo
    before = snapshot(tmp_path)
    second = install(repo, home, tmp_path)
    assert second.returncode == 0 and "already" in second.stdout, second.stderr
    assert snapshot(tmp_path) == before
    for state in ("{ his own", json.dumps({"permissions": {"allow": "everything"}}),  # left as it is, said, no failure
                  json.dumps({"permissions": {"allow": [42]}}), '{"x": NaN}', '{"x": 1e999}',
                  json.dumps({"permissions": {"allow": verbs}, "sandbox": {"excludedCommands": ["dev-ai *"]},
                              "x": float("nan")})):  # every rule there, still not plain JSON: said
        (home / "dotfiles" / "settings.json").write_text(state, encoding="utf-8")
        again = install(repo, home, tmp_path)
        assert again.returncode == 0 and "left as it is" in again.stdout, again.stdout
        assert (home / "dotfiles" / "settings.json").read_text(encoding="utf-8") == state
        assert [path.name for path in (home / "dotfiles").iterdir()] == ["settings.json"]  # no copy left behind
    (home / "dotfiles" / "settings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
    (home / "dotfiles").chmod(0o500)  # valid, its folder read-only: the install fails and says so (owner, 2026-11-04)
    failed = install(repo, home, tmp_path)
    (home / "dotfiles").chmod(0o700)
    assert failed.returncode == 1 and "rules not written" in failed.stdout, failed.stdout + failed.stderr
    sh(repo, "git", "commit", "-qam", "a landed skill")
    third = install(repo, home, tmp_path)
    assert third.returncode == 0 and "copy" in third.stdout, third.stdout
    assert (home / ".claude/skills/dev-ai/SKILL.md").read_text(encoding="utf-8") == "# a half-edited skill\n"


def test_what_stands_at_the_command_path_is_never_replaced(repo: Path, home: Path, tmp_path: Path) -> None:
    command, his = tmp_path / "bin" / "dev-ai", tmp_path / "his-own"
    his.write_text("#!/bin/sh\n# the operator's own command\n", encoding="utf-8")
    for make, target in ((shutil.copy, his), (os.symlink, his), (os.symlink, repo / "dev-ai.json")):
        make(target, command)
        before = snapshot(tmp_path)
        for args in (("--dry-run",), ()):
            refused = install(repo, home, tmp_path, *args)
            assert refused.returncode == 1 and "DEV_AI_BIN" in refused.stdout, refused.stdout
        assert snapshot(tmp_path) == before, "something was written before the refusal"
        assert os.path.realpath(command) == str(command if make is shutil.copy else target), "what stood there moved"
        command.unlink()
    for left in (False, True):  # an earlier install's link to its stable worktree, gone or not: re-pointed
        command.unlink(missing_ok=True), os.symlink(tmp_path / "dev-ai.stable" / "bin" / "dev-ai", command)
        left and (tmp_path / "dev-ai.stable" / "bin").mkdir(parents=True)
        assert (moved := install(repo, home, tmp_path)).returncode == 0 and "re-point" in moved.stdout, moved.stdout
        assert os.readlink(command) == str(repo / "bin" / "dev-ai") and ("no longer used" in moved.stdout) == left
        assert (tmp_path / "dev-ai.stable").exists() == left  # named, never removed


def test_the_installer_deletes_nothing(repo: Path, home: Path, tmp_path: Path) -> None:
    left = {".claude/commands/dev-check.md": "<!-- written by dev-ai's scripts/install.sh -->\n# dev-ai check\n",
            ".codex/prompts/dev-ai.md": f"Read and follow `{home}/.codex/skills/dev-ai/SKILL.md`, this runner's own\n",
            ".codex/skills/dev-ai/SKILL.md": "# the skill of an earlier release\n",
            ".config/opencode/command/dev-ai.md": "# dev-ai\n"}
    for name, text in left.items():
        (home / name).parent.mkdir(parents=True, exist_ok=True)
        (home / name).write_text(text, encoding="utf-8")
    shared = home / "dotfiles" / "shared.rules"  # his link at our path: written through, his file would change
    shared.write_text("# his\n", encoding="utf-8")
    (home / ".codex" / "rules").mkdir(parents=True, exist_ok=True)
    (home / ".codex" / "rules" / "dev-ai.rules").symlink_to(shared)
    result = install(repo, home, tmp_path, "--allow-land")
    assert result.returncode == 0, result.stderr
    assert "\n  remove " not in result.stdout and shared.read_text(encoding="utf-8") == "# his\n", result.stdout
    assert {name: (home / name).read_text(encoding="utf-8") for name in left} == left
    assert os.readlink(tmp_path / "bin" / "dai-land") == str(tmp_path / "stable" / "bin" / "dev-ai")
    rules = home / ".codex/rules/dev-ai.rules"
    rules.unlink()
    personal = (CODEX_RULES.read_text(encoding="utf-8") +
                'prefix_rule(pattern = ["dev-ai", "land", "--merge"], decision = "forbidden")\n')
    rules.write_text(personal, encoding="utf-8")
    assert install(repo, home, tmp_path, "--allow-land", "--yes").returncode == 0
    assert rules.read_text(encoding="utf-8") == personal


def test_opencode_asks_what_destroys_and_his_own_rules_stand(repo: Path, home: Path, tmp_path: Path) -> None:
    """The inserted ask follows his last allow; his later deny, own rules and malformed files stand."""
    config = home / ".config" / "opencode" / "opencode.json"
    his, asks = {"dev-ai *": "deny", "dev-ai clean *": "allow", "dev-ai init *": "allow"}, list(reversed(ASKED))
    yes = "dev-ai clean --yes"  # his deny after a broad allow: it still wins over the ask put before it
    for state, after in ((his, list(his)),  # land, drop denied by his `dev-ai *`, clean and init his keys
                         ({"*": "allow"}, ["*", *asks]),
                         ({"dev-ai *": "allow", yes: "deny"}, ["dev-ai *", *asks, yes])):
        config.write_text(json.dumps({"permission": {"bash": state}}), encoding="utf-8")
        assert install(repo, home, tmp_path, "--yes").returncode == 0
        bash = json.loads(config.read_text(encoding="utf-8"))["permission"]["bash"]
        assert list(bash) == after and bash == {**state, **{key: "ask" for key in after if key not in state}}
    for state in ('{"permission": {"bash": "allow"}}', "{ his own"):
        config.write_text(state, encoding="utf-8")
        again = install(repo, home, tmp_path, "--yes")
        assert again.returncode == 0 and "left as it is" in again.stdout and config.read_text(encoding="utf-8") == state


def test_each_part_is_asked_and_a_no_leaves_it_out(repo: Path, home: Path, tmp_path: Path) -> None:
    settings = (home / "dotfiles" / "settings.json").read_text(encoding="utf-8")
    opencode = snapshot(home / ".config" / "opencode")
    result = install(repo, home, tmp_path, answers="n\n" * 10)  # 2 skills for 3 harnesses, 3 harnesses' rules, tools
    assert result.returncode == 0 and result.stdout.count("[Y/n]") == 10, result.stdout
    assert (tmp_path / "bin" / "dev-ai").is_symlink() and "\n  rtk " not in result.stdout
    assert not (home / ".claude" / "skills").exists() and not (home / ".agents").exists()
    assert (home / "dotfiles" / "settings.json").read_text(encoding="utf-8") == settings
    assert not (home / ".codex" / "rules").exists() and snapshot(home / ".config" / "opencode") == opencode
    assert "[Y/n]" not in install(repo, home, tmp_path, "--yes", "--dry-run").stdout
