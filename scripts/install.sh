#!/usr/bin/env bash
# Install dev-ai for daily use: a stable worktree at main's tip, the command on
# PATH, the skills (dev-ai, frame-task) in every harness, and Claude Code's user rules for six verbs, never `drop`,
# `clean` nor `init`: a broader rule of the operator's own is his (README, Permissions).
# Installs; --dry-run prints what it would change and changes nothing; --yes asks nothing. Re-runnable.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The main checkout, even when this script runs from a task worktree of it.
REPO="$(dirname "$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir)")"
STABLE="${DEV_AI_STABLE:-$(dirname "$REPO")/dev-ai.stable}"
BIN="${DEV_AI_BIN:-$HOME/.local/bin/dev-ai}"
say() { printf '%s\n' "$*"; }
act() { if [ -n "$APPLY" ]; then say "  $1"; else say "  would $1"; fi; }
applying() { [ -n "$APPLY" ]; }  # a bare `[ -n "$APPLY" ] && cmd` would end a function on 1

APPLY=1 ASK=1  # installing is what this command is for; --dry-run is how you look before it does
for arg in "$@"; do case "$arg" in --dry-run) APPLY="" ;; --yes) ASK="" ;;
    *) say "usage: install.sh [--dry-run] [--yes]"; exit 1 ;; esac; done
wants() {  # <question>: yes unless answered n; read on stdin, an empty answer or none keeps yes, --yes asks nothing
    local answer=""
    if [ -n "$ASK" ]; then printf '%s [Y/n] ' "$1"; read -r answer || echo; fi
    case "$answer" in [nN]*) return 1 ;; *) return 0 ;; esac
}

# main's tip, committed: what landed runs. A tag had to be pushed too, and v0.19.0 never was (the owner, 2026-10-14).
REV="$(git -C "$REPO" rev-parse --verify --quiet 'main^{commit}')" || { say "no branch main in $REPO"; exit 1; }
TAG="$(git -C "$REPO" describe --tags --always "$REV")"  # a name to read, never what is checked out
say "dev-ai $TAG from $REPO${APPLY:+ (applying)}"
# Before anything is written. The command's path holds nothing, or the link this install writes, its worktree
# gone or not: whatever else stands there is the operator's, never replaced (the owner, 2026-09-29). `ln -sfn`
# replaced a file and a link of his, and telling his links from ours by where they led failed twice (task 034).
[ ! -e "$BIN" ] && [ ! -L "$BIN" ] || [ "$(readlink "$BIN")" = "$STABLE/bin/dev-ai" ] || {
    say "$BIN is not the link this install writes: move it, or name another with DEV_AI_BIN"; exit 1; }

# 1. The stable worktree. Daily use never runs from the checkout being edited.
if [ -d "$STABLE" ]; then
    # It must be a worktree of this repository, not the checkout being edited, not a task
    # worktree, and clean: `git checkout <commit>` in any of those would take work with it.
    OWNER="$(git -C "$STABLE" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo none)"
    BRANCH="$(git -C "$STABLE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo none)"
    case "$(dirname "$OWNER")=$(readlink -f "$STABLE")=$BRANCH" in
        "$REPO=$(readlink -f "$REPO")="*) say "$STABLE is the checkout being edited: refusing"; exit 1 ;;
        "$REPO="*"=dev-ai/"*) say "$STABLE holds task branch $BRANCH: refusing"; exit 1 ;;
        "$REPO="*) ;;
        *) say "$STABLE is not a worktree of $REPO: refusing"; exit 1 ;;
    esac
    [ -z "$(git -C "$STABLE" status --porcelain)" ] || { say "$STABLE is dirty: refusing"; exit 1; }
    if [ "$(git -C "$STABLE" rev-parse HEAD)" != "$REV" ]; then
        act "move $STABLE from $(git -C "$STABLE" describe --tags --always) to $TAG"
        applying && git -C "$STABLE" checkout --quiet --detach "$REV"
    else
        say "  stable worktree already at $TAG"
    fi
else
    act "create $STABLE at $TAG"
    applying && git -C "$REPO" worktree add --quiet --detach "$STABLE" "$REV"
fi

# 2. The command on PATH, written where nothing stands. Nothing is deleted, here or below: what an
# earlier release wrote stays where it is, the operator's to remove (the owner, 2026-09-29).
if [ -L "$BIN" ]; then  # the link this install writes: anything else ended the run above
    say "  $BIN already points at the stable worktree"
else
    act "link $BIN -> $STABLE/bin/dev-ai"
    if applying; then mkdir -p "$(dirname "$BIN")"; ln -s "$STABLE/bin/dev-ai" "$BIN"; fi
fi

# 3. The skills, where Claude Code and codex look for their user skills, each asked on its own: an operator
# may keep his own copy. They come from the stable worktree, like the command itself: a skill read from the
# checkout being edited would drive every harness from a half-edited file.
# Asked of the commit, not of $STABLE: on a dry run that worktree does not exist yet, and a
# dry run that blames the commit for a file it does carry previews a lie.
install_skill() {  # <home: there, the harness is installed> <label> <where it reads user skills> <skill> <its file>
    local target="$3/skills/$4/SKILL.md"
    [ -d "$1" ] || { say "  $2 not installed, skipped"; return 0; }
    git -C "$REPO" cat-file -e "$REV:$5" 2>/dev/null || { say "  $2: $TAG carries no $5, land it on main first"; return 0; }
    # Compared against the commit, not against $STABLE: on a dry run that worktree still holds
    # the previous one, and "already current" would hide an upgrade the install would do.
    if [ -f "$target" ] && git -C "$REPO" show "$REV:$5" | cmp -s - "$target"; then
        say "  $2 $4 skill already current"
    else
        wants "Install the $4 skill for $2?" || { say "  $2 $4 skill skipped"; return 0; }
        act "copy $TAG's $5 to $target"
        if applying; then mkdir -p "$(dirname "$target")"; cp "$STABLE/$5" "$target"; fi
    fi
}
for skill in "dev-ai docs/skill.md" "frame-task skills/frame-task/SKILL.md"; do read -r name file <<< "$skill"
    install_skill "$HOME/.claude" "Claude Code" "$HOME/.claude" "$name" "$file"
    install_skill "$HOME/.codex" "codex" "$HOME/.agents" "$name" "$file"  # its docs, 2026-09-21: found as $dev-ai
done

RULES=""  # Claude Code's allow rules for six verbs and its sandbox exclusion (README, Permissions)
if [ -d "$HOME/.claude" ]; then wants "Add dev-ai's Claude Code rules?" && RULES=1 || say "  Claude Code rules skipped"; fi
[ -z "$RULES" ] || python3 -I - "$HOME/.claude/settings.json" "$APPLY" <<'PY' || { say "  Claude Code rules not written, the error above: fix it, then install again"; exit 1; }
import json, os, sys, tempfile
path, apply = os.path.realpath(sys.argv[1]), sys.argv[2] == "1"  # a link is kept: its target is written
verbs = ("status", "start", "check", "scope-add", "review", "land")  # never drop, clean nor init
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
