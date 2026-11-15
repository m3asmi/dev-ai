#!/usr/bin/env bash
# Install dev-ai for daily use: the main checkout's command on
# PATH, the skills (dev-ai, frame-task) in every harness, and each harness's user rules: five verbs run unprompted,
# `land`, `drop`, `clean` and `init` asked by default; --allow-land opts codex into land only.
# Installs; --dry-run prints what it would change and changes nothing; --yes asks nothing. Re-runnable.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The main checkout, even when this script runs from a task worktree of it.
REPO="$(dirname "$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir)")"
OLD="$(dirname "$REPO")/dev-ai.stable"  # the worktree installs put there before 2026-11-12, its link ours
BIN="${DEV_AI_BIN:-$HOME/.local/bin/dev-ai}"
say() { printf '%s\n' "$*"; }
act() { if [ -n "$APPLY" ]; then say "  $1"; else say "  would $1"; fi; }
applying() { [ -n "$APPLY" ]; }  # a bare `[ -n "$APPLY" ] && cmd` would end a function on 1

APPLY=1 ASK=1 LAND_MODE=auto  # installing is what this command is for; --dry-run is how you look before it does
for arg in "$@"; do case "$arg" in --dry-run) APPLY="" ;; --yes) ASK="" ;;
    --allow-land) LAND_MODE=allow ;; --prompt-land) LAND_MODE=prompt ;;
    *) say "usage: install.sh [--dry-run] [--yes] [--allow-land|--prompt-land]"; exit 1 ;; esac; done
wants() {  # <question>: yes unless answered n; read on stdin, an empty answer or none keeps yes, --yes asks nothing
    local answer=""
    if [ -n "$ASK" ]; then printf '%s [Y/n] ' "$1"; read -r answer || echo; fi
    case "$answer" in [nN]*) return 1 ;; *) return 0 ;; esac
}

# main's tip, committed: what landed runs. A tag had to be pushed too, and v0.19.0 never was (the owner, 2026-10-14).
REV="$(git -C "$REPO" rev-parse --verify --quiet 'main^{commit}')" || { say "no branch main in $REPO"; exit 1; }
TAG="$(git -C "$REPO" describe --tags --always "$REV")"  # a name to read, never what is checked out
say "dev-ai $TAG from $REPO${APPLY:+ (applying)}"
# Before anything is written. The command's path holds nothing, or a link an install wrote, to this checkout or
# to the worktree of an earlier one, gone or not: whatever else stands there is the operator's, never replaced
# (the owner, 2026-09-29). `ln -sfn` replaced a file and a link of his, and telling his links from ours by where
# they led failed twice (task 034).
LINK="$(readlink "$BIN" 2>/dev/null || true)"
[ ! -e "$BIN" ] && [ ! -L "$BIN" ] || [ "$LINK" = "$REPO/bin/dev-ai" ] || [ "$LINK" = "$OLD/bin/dev-ai" ] || {
    say "$BIN is not the link this install writes: move it, or name another with DEV_AI_BIN"; exit 1; }

# 1. The command on PATH is the main checkout's own: what is there runs at once, no install to re-run after a
# pull or a landing (the owner, 2026-11-12, who dropped the stable worktree). Nothing is deleted, here or below:
# what an earlier release wrote stays where it is, the operator's to remove (the owner, 2026-09-29).
if [ "$LINK" = "$REPO/bin/dev-ai" ]; then
    say "  $BIN already points at $REPO"
elif [ -L "$BIN" ]; then  # an earlier install's, to its stable worktree: anything else ended the run above
    act "re-point $BIN from $OLD to $REPO"
    applying && ln -sfn "$REPO/bin/dev-ai" "$BIN"
else
    act "link $BIN -> $REPO/bin/dev-ai"
    if applying; then mkdir -p "$(dirname "$BIN")"; ln -s "$REPO/bin/dev-ai" "$BIN"; fi
fi
[ ! -d "$OLD" ] || say "  $OLD is no longer used: git -C $REPO worktree remove $OLD, yours to run"

# 2. The skills and codex's rules, where each harness reads its user's, each asked on its own: an operator may
# keep his own copy. They come from main's commit, not from the files of the checkout: a skill read from a
# half-edited file would drive every harness.
install_file() {  # <home: there, the harness is installed> <label> <what> <where it goes> <its file>
    [ -d "$1" ] || { say "  $2 not installed, skipped"; return 0; }
    git -C "$REPO" cat-file -e "$REV:$5" 2>/dev/null || { say "  $2: $TAG carries no $5, land it on main first"; return 0; }
    # A link of his is never written through (codex, task 004).
    if [ -L "$4" ]; then say "  $2 $3: $4 is a link, left as it is: his to update"
    elif [ "${6:-}" = managed ] && [ -f "$4" ] &&
        ! git -C "$REPO" show "$REV:scripts/dev-ai.rules" 2>/dev/null | cmp -s - "$4" &&
        ! git -C "$REPO" show "$REV:scripts/dev-ai-allow-land.rules" 2>/dev/null | cmp -s - "$4"; then
        say "  $2 $3: $4 has custom content, left as it is: his to update"
    elif [ -f "$4" ] && git -C "$REPO" show "$REV:$5" | cmp -s - "$4"; then
        say "  $2 $3 already current"
    else
        wants "Install the $3 for $2?" || { say "  $2 $3 skipped"; return 0; }
        act "copy $TAG's $5 to $4"
        if applying; then mkdir -p "$(dirname "$4")"; git -C "$REPO" show "$REV:$5" > "$4"; fi
    fi
}
OPENCODE="$HOME/.config/opencode"  # it reads ~/.claude and ~/.agents too: a copy of its own serves it alone
for skill in "dev-ai docs/skill.md" "frame-task skills/frame-task/SKILL.md"; do read -r name file <<< "$skill"
    install_file "$HOME/.claude" "Claude Code" "$name skill" "$HOME/.claude/skills/$name/SKILL.md" "$file"
    install_file "$HOME/.codex" "codex" "$name skill" "$HOME/.agents/skills/$name/SKILL.md" "$file"  # its docs
    install_file "$OPENCODE" "opencode" "$name skill" "$OPENCODE/skills/$name/SKILL.md" "$file"
done
# Read in every project, trusted or not, where a project's own rules are not (codex's docs, 2026-11-08).
CODEX_RULES=scripts/dev-ai.rules
CODEX_TARGET="$HOME/.codex/rules/dev-ai.rules"
if [ "$LAND_MODE" = allow ] || { [ "$LAND_MODE" = auto ] && [ -f "$CODEX_TARGET" ] && [ ! -L "$CODEX_TARGET" ] &&
    git -C "$REPO" show "$REV:scripts/dev-ai-allow-land.rules" 2>/dev/null | cmp -s - "$CODEX_TARGET"; }; then
    CODEX_RULES=scripts/dev-ai-allow-land.rules
fi
install_file "$HOME/.codex" "codex" "dev-ai rules" "$CODEX_TARGET" "$CODEX_RULES" managed

RULES=""  # Claude Code's allow rules for five verbs and its sandbox exclusion (README, Permissions)
if [ -d "$HOME/.claude" ]; then wants "Add dev-ai's Claude Code rules?" && RULES=1 || say "  Claude Code rules skipped"; fi
[ -z "$RULES" ] || python3 -I - "$HOME/.claude/settings.json" "$APPLY" <<'PY' || { say "  Claude Code rules not written, the error above: fix it, then install again"; exit 1; }
import json, os, sys, tempfile
path, apply = os.path.realpath(sys.argv[1]), sys.argv[2] == "1"  # a link is kept: its target is written
verbs = ("status", "start", "check", "scope-add", "review")  # never land (the owner, 2026-11-11), drop, clean, init
try:  # after his own, none changed; another shape is said, an I/O error fails the install (the owner, 2026-11-04)
    data, added = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}, 0
    for section, key, rules in (("permissions", "allow", [f"Bash(dev-ai {v} *)" for v in verbs]),
                                ("sandbox", "excludedCommands", ["dev-ai *"])):
        held = data.setdefault(section, {}).setdefault(key, [])
        held += (new := [rule for rule in rules if rule not in held]) if all(  # TypeError unless a list of strings
            isinstance(rule, str) for rule in held) else None
        added += len(new)
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"  # plain JSON, or ValueError
    print(f"  {'' if apply else 'would '}add {added} Claude Code rules to {path}" if added else "  rules already there")
    if added and apply:  # a new 0600 file of its own, swapped in: never a half-written one (codex, task 006)
        fd, copy = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings-dev-ai-")
        with os.fdopen(fd, "w", encoding="utf-8") as out: out.write(text)
        os.replace(copy, path)
except (ValueError, AttributeError, TypeError) as error:  # not plain JSON, or not the shape these rules fit
    print(f"  {path} left as it is ({error}): the rules are in the README (Permissions)")
PY

# opencode has no sandbox: what merges or destroys is asked, after his last rule allowing it (the last match wins), so
# `dev-ai *: allow` no longer runs `drop --destroy` unasked and every later rule of his still wins (codex, task 004).
if [ -d "$OPENCODE" ] && wants "Add dev-ai's opencode rules?"; then
python3 -I - "$OPENCODE/opencode.json" "$APPLY" <<'PY' || { say "  opencode rules not written, the error above: fix it, then install again"; exit 1; }
import fnmatch, json, os, sys, tempfile
path, apply = os.path.realpath(sys.argv[1]), sys.argv[2] == "1"
try:
    if os.path.exists(sys.argv[1] + "c"): raise ValueError("an opencode.jsonc stands beside it")  # beside the link
    data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    held = data.setdefault("permission", {}).setdefault("bash", {})
    if not isinstance(held, dict): raise TypeError("its bash permission is not a map of patterns")
    rules, new = list(held.items()), []
    for key in (f"dev-ai {v} *" for v in ("land", "drop", "clean", "init")):
        hits = [i for i, (k, _) in enumerate(rules) if fnmatch.fnmatchcase(key[:-1] + "x", k)]
        if key not in held and (not hits or rules[hits[-1]][1] == "allow"):  # his ask, deny or own key stands
            rules.insert(hits[-1] + 1 if hits else 0, (key, "ask")); new.append(key)
    held.clear(); held.update(rules)
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    print(f"  {'' if apply else 'would '}add {len(new)} opencode rules to {path}" if new else "  rules already there")
    if new and apply:
        fd, copy = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".opencode-dev-ai-")
        with os.fdopen(fd, "w", encoding="utf-8") as out: out.write(text)
        os.replace(copy, path)
except (ValueError, AttributeError, TypeError) as error:
    print(f"  {path} left as it is ({error}): the rules are in the README (Permissions)")
PY
elif [ -d "$OPENCODE" ]; then say "  opencode rules skipped"; fi

# 4. Tools that keep a harness's context small, named when absent with their project's own install command,
# never run. Measured on the operator's machine, 2026-09-22: rtk keeps 81.9 % of tool output out of context,
# context-mode 72 % of a session. The owner, 2026-09-30: task 042 took the offer out, a suggestion comes back.
suggest() {  # <probe> <label> <gain> <the project's own install command>
    if eval "$1" >/dev/null 2>&1; then say "  $2 present"; return 0; fi
    say "  $2 missing, $3; to install it:"
    say "    $4"
}
if wants "Look for rtk and context-mode, which keep a harness's context small?"; then
    suggest 'command -v rtk' "rtk" "81.9 % of tool output kept out of context, then rtk init -g" \
        'curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh'
    suggest 'grep -q "\"context-mode@" "$HOME/.claude/plugins/installed_plugins.json"' "context-mode (Claude Code)" \
        "72 % of a session kept out of context" \
        'claude plugin marketplace add mksglu/context-mode && claude plugin install context-mode@context-mode'
fi

applying || say "dry run: nothing changed. Run it without --dry-run to install."
