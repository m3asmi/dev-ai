#!/usr/bin/env bash
# After a merge, from the repository: removes each worktree under DIR whose task has TASKS/<name>/landing.json,
# whose HEAD is in BRANCH and whose every changed, untracked or ignored file held that content in BRANCH once.
# A GLOB matched against <worktree name>/<path> excuses a file git ignores (a cache, a build). Dry run unless --yes.
set -euo pipefail
usage="usage: $0 --base BRANCH --under DIR --tasks DIR [--ignore GLOB]... [--yes]" apply=0 ignore=() gone=()
while [ $# -gt 0 ]; do case "$1" in
  --base) base=${2:?$usage}; shift 2 ;; --under) under=$(realpath "${2:?$usage}"); shift 2 ;;
  --tasks) tasks=${2:?$usage}; shift 2 ;; --ignore) ignore+=("${2:?$usage}"); shift 2 ;; --yes) apply=1; shift ;;
  *) echo "$usage" >&2; exit 2 ;; esac; done
[ -n "${base:-}" ] && [ -n "${under:-}" ] && [ -n "${tasks:-}" ] || { echo "$usage: all three are required" >&2; exit 2; }
kept_by() { local wt=$1 path glob  # prints why worktree $1 stays, nothing when its work landed
  [ -f "$tasks/${wt##*/}/landing.json" ] || { echo "its task has not landed"; return; }  # open, no commit: 347, 176, 177 (10-19)
  git merge-base --is-ancestor "$(git -C "$wt" rev-parse HEAD)" "$base" || { echo "HEAD not in $base"; return; }
  [ -z "$(git -C "$wt" diff --summary HEAD | grep -v '^ create mode ')" ] || { echo "a deletion, rename or mode change"; return; }
  while IFS= read -r -d '' path; do
    [ -f "$wt/$path" ] || continue
    for glob in "${ignore[@]}"; do [[ "${wt##*/}/$path" == $glob ]] && git -C "$wt" check-ignore -q -- "$path" && continue 2; done
    [[ "$(git log --raw --no-abbrev --format= "$base" -- "$path")" == *" $(git hash-object "$wt/$path") "* ]] ||
      { echo "$path never in $base"; return; }
  done < <(git -C "$wt" diff -z --name-only HEAD; git -C "$wt" ls-files -z -o)
}
while read -r wt; do
  [[ "$wt" == "$under"/* ]] || continue; why=$(kept_by "$wt")
  if [ -n "$why" ]; then echo "keeps ${wt##*/}: $why"; else echo "landed ${wt##*/}"; gone+=("$wt"); fi
done < <(git worktree list --porcelain | sed -n 's/^worktree //p')
[ "${#gone[@]}" -gt 0 ] || { echo "No worktree under $under to remove."; exit 0; }
[ "$apply" = 1 ] || { echo "Dry run, nothing removed: add --yes."; exit 0; }
for wt in "${gone[@]}"; do b=$(git -C "$wt" branch --show-current) h=$(git -C "$wt" rev-parse HEAD)  # h: in $base
  git worktree remove --force "$wt" && echo "removed ${wt##*/}" && { [ -z "$b" ] || git update-ref -d "refs/heads/$b" "$h" ||
  echo "keeps branch $b: it moved past $base"; }; done; git worktree prune
