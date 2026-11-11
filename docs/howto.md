# How dev-ai works, for the person who runs it

The other documents here are written for someone else: `README.md` is the
reference, `AGENTS.md` the rules an agent obeys in this repository, `docs/skill.md`
the instructions every harness reads, `docs/design.md` the invariants and what the
tool deliberately is not. This one walks you through a task. Where a rule is
already stated elsewhere, it is named, not repeated.

## What it is for

An agent writes a patch. You want three things before it reaches your branch: that
it stayed on target, that the tests ran on exactly that patch, and that a second
model read it. `dev-ai` holds those three and nothing else. It does not plan, pick
models or run anything itself.

## Preparing a repository, once

```
dev-ai init --test-command "<the repository's suite>"
```

It writes `dev-ai.json`, adds the `Working with dev-ai` note to `AGENTS.md`, and
keeps `.dev-ai/` out of git. Whatever is already there it keeps and says so. The
harness rules are the installer's, once in your user settings, so the flow runs without
asking you, except `land`, `drop`, `clean` and `init`; your own deny rules still win (README, Permissions).

## A task, from your side

You usually type nothing. You tell the agent what you want, it carries the task
through `/dev-ai` (`$dev-ai` in codex, `@dev-ai` in opencode), the one entry point, to the
end. Your harness asks you only what its rules do not cover;
`dev-ai` has no terminal of its own. Run `dev-ai status` yourself whenever you want
to see where every task stands.

At `start` the agent records who is writing, with which model, and what `land` will be
allowed to do: `--delivery merge` only if you said to merge, else `commit`. It cannot widen later.

## The refusals you will see, and how each one ends

Each says what, why and how to recover, in one message. The common ones:

- **out of scope** — the patch touched a file the task never claimed. The agent
  either reverts it or widens the scope with a recorded reason. Every widening is
  in the record and the reviewer reads it.
- **tests failed** or **tests timed out** — the log is kept whole, never trimmed.
- **secret in patch** — a secret-bearing file is in the diff. It comes out; the
  review would send it to a model provider.
- **stale base** — before a merge, your branch moved since the patch was checked. The agent merges
  it in the worktree and checks again.
- **no mandate** — `--merge` on a task opened for `commit` only. It lands on its
  branch and you merge it yourself.
- **review pending** — the reviewer raised a `critical` or `high` finding. It is a
  claim until the agent reproduces or refutes it, with evidence, on record.

## dev-ai never stops you

When the agent refutes a `critical` or `high` finding rather than fixing it, `land`
refuses until a reviewer has read the agent's evidence: the next `dev-ai review` sends
it back, and the reviewer withdraws the finding or maintains it, which fails the patch.
You are not asked to approve what you could only approve blindly: four such approvals
on the bench came back as Fixes-tasks. Your harness's permission prompt is the only stop.

## Who reviews

Another harness than the author's, or the author's own harness with `--model`
naming a model other than the one that wrote the patch. The model that answers is
never observed, only the one asked for: the record says `observed unknown`.

## What is on record

Under `.dev-ai/` in the main checkout, one directory per task: the goal and scope,
the check with its fingerprint, the whole test log, the review and its findings
with their resolutions, the landing. Plus `log.jsonl`, one row per command with its
duration and, when blocked, the kind. Nothing is written outside that directory and
your own `AGENTS.md`.
