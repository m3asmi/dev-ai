#!/usr/bin/env bash
# After a merge: drops the PostgreSQL databases a project's test runs left behind. A dry run
# unless --yes. Never a template, a --keep database, nor one a session is connected to.
set -euo pipefail
usage="usage: $0 --match REGEX [--keep NAME]... [--yes]" match="" keep="" apply=0 failed=0
while [ $# -gt 0 ]; do case "$1" in
  --match) match=${2:?$usage}; shift 2 ;; --keep) keep+="${keep:+$'\n'}${2:?$usage}"; shift 2 ;;
  --yes) apply=1; shift ;; *) echo "$usage" >&2; exit 2 ;; esac; done
[ -n "$match" ] || { echo "$usage: --match is required" >&2; exit 2; }
out=$(psql -d postgres -AtX -v match="$match" -v keep="$keep" <<'SQL'
SELECT pg_size_pretty(pg_database_size(datname)) || E'\t' || datname FROM pg_database d
WHERE NOT datistemplate AND datallowconn AND datname ~ :'match'
  AND datname <> ALL (string_to_array(:'keep', E'\n'))
  AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a WHERE a.datname = d.datname) ORDER BY 1;
SQL
)
[ -n "$out" ] || { echo "No database matches $match."; exit 0; } && echo "$out"
[ "$apply" = 1 ] || { echo "Dry run, nothing dropped: add --yes."; exit 0; }
while IFS=$'\t' read -r _ db; do dropdb --if-exists "$db" && echo "dropped $db" || failed=1; done <<< "$out"; exit "$failed"
