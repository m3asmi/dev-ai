---
name: frame-task
description: "Frames a dev-ai task before `dev-ai start` and returns a card ready for `/dev-ai`: verifiable criteria for \"done\", scope, split, an invariants spec where it pays off, mandate, and what stays the operator's job. Use this skill when the user asks to frame, define, prepare or split a task in a repository migrated to dev-ai (a `dev-ai.json` at its root), when they hesitate over which task to start, when a review finding falls outside the goal of the current task, and for any defect found after a merge: its goal must then begin with `Fixes-task: <slug>`, and this skill is what sets it. A work request whose goal is already clear goes straight to `/dev-ai`, without framing. It launches nothing."
---

# Framing a dev-ai task

dev-ai proves that the patch stays on its target, that it is tested and that another model reviewed it. It does not prove that the target is the right one: framing fixes it, and that is where the operator weighs most. Hand him a clean card, taking as little of his time as possible; `/dev-ai` then executes.

Three rules hold the rest:

- **You launch nothing.** No `dev-ai start`, no commit, no write in the repository outside `.dev-ai/`, which git ignores; reading and `dev-ai status`, which writes only one log line, are allowed. The only file you write is the spec draft, under `.dev-ai/frames/`.
- **One series of questions.** The tool that preceded dev-ai stopped the operator dozens of times per task. Here, you decide everything that is not his and write it on the card; you ask him only what is his (step 6), in a single message.
- **You classify no risk and block nothing.** dev-ai has every patch reviewed except documentation, whatever happens. Framing only serves to aim the tests and the review correctly.

## 1. Locate the request

| Source | What it changes |
|---|---|
| A clear, bounded request | No framing: say so and send to `/dev-ai`. A stop before every task is what dev-ai ruled out. |
| A need | The goal says what "done" means. |
| A defect found after the merge of a dev-ai task | The goal begins with `Fixes-task: <original slug>`, followed by what "done" means: this is how the twenty-task routine counts post-merge defects. Find the slug below. |
| A review finding within the goal of the current task | No new task: it is confirmed or refuted in `/dev-ai`. Say so and stop. |
| A review finding outside that goal (existing code, another module) | A new task, never a `scope-add` that would absorb it. If the targeted code comes from a merged task, it is a defect: `Fixes-task`. |

**Finding a defect's original task**, from the faulty line; without a precise line, find it first, from the symptom to the code that produces it. The merge that brought in a commit is the oldest merge of a `dev-ai/…` branch descending from that commit whose first parent did not yet contain it. Without this last test, a commit made directly on the base branch would be attributed to the first task merged after it.

```bash
c=$(git log -1 -s --format=%H -L <line>,<line>:<file>)
test -n "$c" || echo "line not found"
o=""
# git log goes from newest to oldest: the last assignment keeps the oldest.
for m in $(git log --merges --ancestry-path --format=%H "$c"..HEAD); do
  s=$(git log -1 --format=%s "$m")
  [[ $s == "merge dev-ai/"* || $s == "Merge branch 'dev-ai/"* ]] && ! git merge-base --is-ancestor "$c" "$m^1" && o="$s"
done
echo "$o"
```

The output is `merge dev-ai/<slug>: <goal>`, the message `land --merge` sets, or `Merge branch 'dev-ai/<slug>'`, the one git sets when a task delivered as `commit` is merged by hand without `-m`. Empty: no task merge brought in the commit. A task delivered as `commit` and then fast-forward merged leaves none: look for it among the `committed` tasks of `dev-ai status`. It is the one whose `head_sha` in `.dev-ai/tasks/<slug>/landing.json` contains the commit, and whose `base_sha` in `check.json`, in the same folder, does not; `git merge-base --is-ancestor <commit> <sha>` tells. None: no `Fixes-task`, and the card says the origin was not found. "line not found": the file was renamed or the line moved; ask for it in the current version rather than conclude. If the operator's hook blocks a command, do not work around it: rephrase it with git's formats (`--format`), without column extraction or `${…}` expansion. This block passes.

## 2. Read the terrain

- The repository is migrated: `dev-ai.json` at the root and the "Working with dev-ai" note in `AGENTS.md`. Otherwise, say so and stop: there is no dev-ai task to frame.
- Read `test_command` in `dev-ai.json`: it is the only thing dev-ai guarantees. Note what it runs and what it does not run (e2e, ACL tests, scanners, module update); step 3 depends on it.
- Read `AGENTS.md` and the decision documents it points to (roadmap, design, what is "not planned"): their conventions take precedence over this skill's thresholds. A request that contradicts a decision already taken is flagged at the top of your message, before the card.
- If `AGENTS.md` sets a numeric budget (lines of code, suite duration), measure where it stands: it is often the budget, more than the 600 lines of step 4, that bounds the task.
- `dev-ai status`: an open task that already covers the request is resumed, not duplicated.
- Explore just enough to name the files touched, their callers and the existing tests. The implementation plan is `/dev-ai`'s work, not yours.

## 3. Write "done" as verifiable criteria

A criterion is an observable behaviour, such an input giving such a result, not an activity: "refactor X" is not one. For each, say what will prove it:

- **a test**, written first, that `test_command` will run: this is guaranteed;
- **the operator's acceptance check**, when `test_command` cannot prove it (a path through the interface, the rendering of a report, performance on real volumes, a migration on a copy of production): this is his job, and the card says so.

A test that only pins a text or a value, with no behaviour behind it, proves nothing: it is acceptance check material. A criterion that no test and no acceptance check can prove is vague: rephrase it before going further. It is the surest sign that a request is not ripe.

## 4. Scope and split

- `--paths`: the narrowest that holds the change, the tests that prove it, and the existing tests, comments and docs that state or describe the changed behaviour: look for them before handing back the card (`rg` on the method, field or message name). On an Odoo repository, 98 of the 209 files added by `scope-add` were tests, and 5 additions only fixed comments. Leave out the configuration of the scanners and of the suite: a patch must not be able to loosen what judges it. Unless changing it is the goal of the task: the card then says so, so that the review reads it.
- Split beyond the threshold `AGENTS.md` sets; failing that, beyond about 600 changed lines, the measure the twenty-task routine tracks. Also split when the criteria separate into behaviours that can be delivered alone. A large diff is reviewed less well, and beyond one million characters codex refuses the review. One task per piece, in dependency order: the card frames the first and names the following ones.
- A fix whose code also lives on another maintained branch of the repository (for example `main` and `20.0`): frame its twin task in the same message, its `start` command with `--base '<that branch>'` (without it, the task starts from the base in `dev-ai.json` or from the current branch), or say why the defect is not there. On an Odoo repository, 14 of the 89 `Fixes-task` carried a defect already fixed on the other branch.
- Slug: lowercase letters, digits, `.`, `_` or `-`, 64 characters at most, starting with a letter or a digit.

## 5. The spec, where it pays off

The most serious catches of the cross-review were violations of declared invariants: without a spec, the reviewer does not know what must remain true. Propose a spec when the task touches:

- rights: ACL, record rules, `sudo()`, groups, multi-company;
- money: accounting, taxes, rounding, payments, stock valuation;
- persistent data: migrations, schema, deletions, mass imports, recomputed stored fields;
- external effects: emails, API calls, payments, crons, anything that cannot be replayed without damage;
- a public API or a contract between modules.

Elsewhere, no spec, unless the project asks for it. It fits in 80 lines at most, `dev-ai start` refuses more: invariants, preconditions and postconditions, what must not change, decisions already taken. No plan. Write it in the main checkout, never in a task's worktree, under `.dev-ai/frames/<slug>-spec.md`: `dev-ai init` excludes `.dev-ai/` from git, and the draft stays in the repository. Pass its absolute path to `--spec`: `start` resolves a relative path from the folder where it is launched, then copies the spec along with the task.

**Re-read the goal, and the spec if there is one, against the code before handing back the card.** `start` freezes them, and the reviewer reads them word for word, without the conversation that produced them: a wrong word can only be fixed by restarting the task, after lost review cycles. Read once each sentence of the goal, each invariant, decision and case of the spec against the code, and fix everything in one pass:

- a word broader or narrower than what the code does: national or not, batch or alert, prefill or send, empty or absent. "Address without a city", without "national", cost two cycles on a regulatory recall;
- a property the code lacks: a field the spec uses as a measure, filter or grouping must be stored;
- a mechanism and a bound that it does not hold: check the mechanism in its documentation, and write as contract only one of the two, unless one follows from the other;
- an existing behaviour the spec is silent on: write it down;
- a fact about the data (a user's groups, companies, parameters, existing records): read it on a copy of the real database before handing back the `start` command. With no copy accessible, put it to the operator among his decisions (section 6): the card does not go out on an unread fact. An acceptance test relied on the project managers' groups as the spec described them, wrong on the copy of the real database: the task was reviewed on a fact the database contradicted.

## 6. The operator's decisions, in a single message

Ask only what is his, and only what the request does not already settle:

1. If the criteria or the spec go beyond what he said: do they represent the business need? You cannot know.
2. The mandate: `merge` only if he says so, in his own words; otherwise `commit`, and he merges himself.
3. The split, if there is one.
4. For a client repository whose `AGENTS.md` does not settle the question: does his contract allow sending the code to a second provider for the review?

Put them under the draft card, in the same message. After his answers, hand back the final card. With no question to ask, hand it back directly. With no answer on the mandate, it is `commit`.

## 7. The card

Hand back this template, every line filled in:

```
Task       <slug>
Source     need | Fixes-task: <original slug> | finding outside the goal of <task>
Kind       product | proof and tooling
Goal       <what "done" means, in one sentence>
Criteria   1. <behaviour> → test: <what it asserts>          guaranteed
           2. <behaviour> → acceptance check: <what the operator verifies>
Scope      <paths>
Mandate    merge | commit
Spec       <absolute path> | none: <why>
Split      <following tasks, in order> | none
After the merge, on you: <acceptance check, migration on a prod copy, deployment>
```

Goal and criteria are written in the repository's language, that of its commits: the goal becomes the merge message, `merge dev-ai/<slug>: <goal>`.

Then the command, which `/dev-ai` will launch:

```
dev-ai start <slug> --goal "<goal>" --paths '<path>' ['<path>'…] --author <harness> --author-model <model> --delivery <mandate> [--spec '<absolute path>'] [--base '<branch>']
```

The goal goes in double quotes: it contains no backtick, `$`, `\`, `"` or `!`, which the shell would execute or interpret there. Name the code in plain words or between apostrophes. Each path, of `--paths` as of `--spec`, and the branch of `--base` go between apostrophes: a space does not split it, and dev-ai receives a glob pattern as is, not the files it designates today.

`--author` and `--author-model` are those of the session that will write the patch, not yours: leave them as `<…>`, `/dev-ai` fills them in.

"Kind" exists because a drift was measured on an Odoo repository: far more proof and tooling tasks than product code. You do not judge it and you cite no figure; you fill in the line, it makes the drift visible.

End with one line: what you decided without being asked (thresholds, scope, split), so that the operator sees it before launching `/dev-ai`.
