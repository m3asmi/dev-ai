# Roadmap

## State on 2026-09-20: complete docs are not a finished tool

| | |
|---|---|
| Built, tested, committed | `start` with its profile, mandate and `--spec`, `check` with the secret guard, `review` with `--model`, `--fallback` and `--resolve`, `land` within the mandate, `stale_base`, `drop --destroy`, `scope-add` with its reason, `status` confronting the evidence, the log with its registry of blocker kinds, the budget tests |
| Verified once, by hand | both real reviewers, on a throwaway patch; both refusing a 6.3 MB patch (`unavailable`); an end-to-end run as a real process, with a fake reviewer; the bench's unit suite from a `dev-ai` worktree (307 s, exit 0; its log names the worktree's addons, never the main checkout's) |
| Delivered on the bench, 2026-09-18 | four: DOC-GATE-V13 and TASK-063 merged by hand under `v0.1.0` (3 h 56, 3 h 48); TASK-061 by `land --merge` itself under `v0.3.0` (4 h 43, of which 3 h 43 waiting for a human, 22 min of tests, 8 s of `dev-ai`); DOC-GATE-061-063 landed then fast-forwarded by hand (58 min, the operator being at his desk). `stale_base` fired twice and `not_confirmed` once, all for real, all costing nothing |
| Changed on 2026-09-20 (task 003 here) | the terminal confirmation and the impact word list are gone: the harness's prompt and the recorded mandate approve, every change but documentation is reviewed, blocking findings are resolved with evidence, evidence goes stale with the patch or the test command, `drop` and `land --merge` spare ignored files, worktrees live under `.dev-ai/`, the installer grants nothing. Not yet measured on a real task |
| Done since, measured 2026-09-20 | the cross-model review, this tool's thesis: 86 runs gave a verdict across both repositories, 50 `pass`, 22 `fail`, 3 `pending`, 11 `unavailable`. codex reviewed 13 times (2 pass, 4 fail, 2 pending, 5 unavailable), so it works and fails intermittently rather than being out. `--resolve` answered its first real finding on 2026-09-20: codex, high, on `fingerprint`, confirmed by running it and fixed |
| Never done | a review by opencode: 5 attempts, 5 `unavailable`, never a verdict. At least 66 of the 86 runs are `claude` reading a `claude` patch, so the guarantee usually rests on the model named, not on the harness. Also a brief just under codex's cap |

## Step 3 — learn every twenty tasks

The bench is over. On 2026-09-28 the median from creation to merge is 0.64 h on
the bench (133 tasks), against 4.3 to 23.3 h under dev-pipeline: the success
criterion is met. What follows is a routine around the tool, never a feature in it.

Every twenty landed tasks of a repository, at most once a week, an agent takes the
measures below, read-only, as defined here. The owner decides at most one change per
repository; the values, the decision, its expected effect and its removal condition
go to that project's own status notes, wherever its owner keeps them. A change is a line in the project's
`AGENTS.md` or spec, never in `dev-ai`: a line added removes a line, and a rule whose
measure has not moved after two cycles goes.

| Measure | Taken from | 2026-09-28 |
|---|---|---|
| creation → merge, median and p75, capped at 24 h | `created_at` in `task.json` to the `merge dev-ai/<slug>` commit, else `landed_at` | the bench 0.64 h and 1.45 h |
| patches above 600 changed lines | `git diff --numstat` of that merge, every file | the bench 20 % |
| model reviews with a blocking finding | `review` rows of `log.jsonl` lasting 20 s or more, verdict `pending` or `fail` | the bench 37 % |
| of those, at least one confirmed | the `--resolve` rows (under 20 s) after a `pending` review end in `fail` | 67 %, every repository |
| review runs per task, median and p90 | answers carrying `findings` in `review.log` | the bench 2 and 6 |
| tasks on proof and paperwork against product code | the directory holding most of each merge's lines, as the project names them | the bench 44 against 12 since 09-18 |
| blocker kinds that fired, and those that never did | `blockers` and `kind` in `log.jsonl`, against `KINDS` in `devai/task.py` | 16 of 31 never fired: argument checks and the landing's safety nets |
| refutations withdrawn and maintained on re-examination | `resolution` of refuted findings in `review.json` | from 2026-10-27; before, 7 of 241 landings stopped for `APPROVE TASK<nn>` |
| fixes to this tool per task delivered with it | `fix:` commits here ÷ landings elsewhere | 0.09 |
| defects found after merge | goals starting with `Fixes-task: <slug>` in `task.json` | counted from 2026-09-28 |
| defect classes confirmed three times | the `--resolve … confirmed --evidence` commands in the harness's transcripts | a Next.js site: a configuration's identity and price |

**Owed from the bench:** a codex re-review, outside the tool, of each merged task only
its author's harness read, counted as defects found after merge.
**Stop:** a budget limit exceeded twice, or more than one fix commit to this tool
per delivered task; then work here stops and dev-pipeline's reduction plan resumes.

## Step 4 — 1.0, then one repository at a time

- **1.0** is the first Step 3 cycle whose twenty bench landings include no `Fixes-task`, no limit
  moved since 2026-09-28: the owner restated it on 2026-09-30, the limits having moved twice.
- **A repository is migrated** when its `dev-ai.json` declares its tests and its
  `AGENTS.md` carries the agent note (README). The bench first; tasks in flight
  under dev-pipeline finish there.
- **Another repository is not the bench.** Under dev-pipeline it saw 5 reviewer retries in 515
  tasks, against 9 in 53 here: validate it on its own tasks.
- **The owner's own files.** Since 2026-09-18 `~/.claude/CLAUDE.md` routes every
  non-trivial task in a migrated repository through `dev-ai`; `/dp-go` stays for
  the rest.
- **dev-pipeline** is frozen since 2026-09-17 (only fixes that unblock a task in
  flight), and archived after twenty tasks delivered here without a defect it
  would have caught.

## Not planned

Planner, task decomposition, waves, model catalogue, runner adapters, signed
provenance, retry budgets, council, design gate, readiness gate, approval briefs,
a `before_coding` stop, scanners (SCA, SAST, IaC), a permanent service, a
workflow engine, a vector memory, a risk score, tool interception — the harness
or the CI does these, or the measurements showed they changed nothing. Reopen one
only with a real failed case, as the installer was: 62 lines of skill living
outside the repository, unversioned, with two manual install steps beside them.
