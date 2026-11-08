# Roadmap

## Track your use: one line, then one decision every twenty tasks

`dev-ai status` ends with one line, nothing to set up:
`24 tasks: 20 landed, 3 open, 1 dropped; median start to landing 0.6 h; 2 Fixes-task`.
A `Fixes-task` is a task whose goal starts with `Fixes-task: <slug>`: a defect found after
`<slug>` landed. Glance at that line; it is the routine, never a feature to add.

Every twenty landed tasks of a repository, at most once a week, take the measures below,
read-only (an agent can). Decide at most one change; write the values, the decision, its
expected effect and when it goes, wherever you keep your notes. A change is a line in the
project's `AGENTS.md` or spec, never in `dev-ai`: a line added removes a line, and a rule
whose measure has not moved after two cycles goes.

| Measure | Taken from |
|---|---|
| start → landing, median and p75, capped at 24 h | `created_at` in `task.json` to `landed_at` in `landing.json` |
| patches above 600 changed lines | `git diff --numstat` of each landing: its merge commit, or its branch for a commit landing |
| model reviews with a blocking finding | `review` rows of `log.jsonl` lasting 20 s or more, verdict `pending` or `fail` |
| of those, at least one confirmed | the `--resolve` rows after a `pending` review that end in `fail` |
| review runs per task, median and p90 | answers carrying `findings` in `review.log` |
| blocker kinds that fired, and those that never did | `blockers` and `kind` in `log.jsonl`, against `KINDS` in `devai/task.py` |
| refutations withdrawn and maintained | `resolution` of refuted findings in `review.json` |
| defects found after landing | the `Fixes-task` count of `dev-ai status` |

What it measured where it was built, on the bench: start to merge fell from 4.3 to 23.3 h
under dev-pipeline to a median of 0.64 h over 133 tasks (2026-09-28); 37 % of model reviews
held a blocking finding, and two thirds of those were confirmed.

**Stop:** a budget limit exceeded twice, or more than one fix commit to this tool per
task delivered with it (`AGENTS.md`); then work on the tool stops.

## Not planned

Planner, task decomposition, waves, model catalogue, runner adapters, signed
provenance, retry budgets, council, design gate, readiness gate, approval briefs,
a `before_coding` stop, scanners (SCA, SAST, IaC), a permanent service, a
workflow engine, a vector memory, a risk score, tool interception — the harness
or the CI does these, or the measurements showed they changed nothing. Reopen one
only with a real failed case.
