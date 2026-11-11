# Design

## Threat model

| | Assumed | Not assumed |
|---|---|---|
| The model | competent; may aim at the wrong target, do too much, pass tests it wrote itself, leave a subtle defect in sensitive code | that it forges evidence, lies about results, or attacks its own controls |
| The orchestrator | deterministic code in this repository | an LLM interpreting a contract |
| The operator | one person, who opened the task and lands it; the harness's permission prompt is where he approves | a team needing proof of who did what |

Everything absent from this tool follows from that table. Measured on 53 bench
tasks under dev-pipeline (2026-09-17): its signed-provenance apparatus caught no
model fault; cross-model review caught at least seven serious defects that
passing tests had missed; the council changed 0 of 22 outcomes.

## Flow and state

```
start ──► develop in the worktree (the harness's model) ──► check, and beside it review unless docs only ──► land
```

No risk is classified up front and no word list decides: once the diff exists,
anything but descriptive documentation is reviewed; documentation lands on its tests alone.

State lives under `.dev-ai/` in the **main checkout**, excluded through
`.git/info/exclude` so no tracked file changes:

| File | Written by | Holds |
|---|---|---|
| `tasks/<slug>/task.json` | `start`, `scope-add` | goal, `scope_paths`, base ref and sha, author and its model (a human has none), delivery mandate, worktree, scope history |
| `tasks/<slug>/spec.md` | `start --spec` | up to 80 lines of invariants and decisions, written by the operator or the harness |
| `tasks/<slug>/check.json` | `check` | base sha (the merge-base with the base branch), patch fingerprint, changed files and those that need a review, test result with its command, blockers and their kinds, verdict |
| `tasks/<slug>/test.log` | `check` | full output of the test command, never truncated |
| `tasks/<slug>/review.json` | `review` | patch fingerprint, reviewer, model requested (observed: unknown), verdict, findings with their resolution and its evidence, reason, duration |
| `tasks/<slug>/review.md` | `review` | the same, for reading; findings numbered for `--resolve` |
| `tasks/<slug>/review.log` | `review` | every run's command line, exit, full stdout and stderr, appended |
| `tasks/<slug>/landing.json` | `land` | head sha, fingerprint, files that needed a review, review verdict, who reviewed and the model asked for, merged |
| `tasks/<slug>/dropped.json`, `kept/` | `drop`, `land --merge` | when, whether work that lived nowhere else was destroyed, the ignored files kept aside and the files themselves |
| `log.jsonl` | every command | time, tool version, command, task, outcome, duration, blocker kind; for a review, its reviewer and the model asked for |

`devai/review.py` is the only writer and the only reader of `review.json`: `land`
asks it for the standing of a fingerprint. One schema, in one module.

Worktrees live under `.dev-ai/worktrees/<slug>` by default, on branch
`dev-ai/<slug>`: inside the checkout, where the harness already lets the agent
write. A command run inside a worktree finds its task from the branch name.

## Invariants, each held by a test in `tests/`

| Invariant | Why | Test |
|---|---|---|
| The patch is everything that differs from the base: committed, staged, unstaged, untracked | a model that commits early, or leaves a new file untracked, must not slip past the scope check | `test_check_names_every_file_outside_the_scope…` |
| Evidence is bound to the exact patch, to the base it was checked against and to the test command that judged it: `land` and `status` confront a recorded pass with the worktree as it is, its merge-base and `dev-ai.json` (`unchecked`, `stale`), and a worktree that is gone, git holding none of the task's branch at its path, blocks `check`, `review` and `land` (`worktree_gone`) with what to do whether the task is merged or not, no state being guessed, and one off its branch as `wrong_branch`; a check from before 0.6.0 is no evidence; `stale_base` when the base branch moved before a merge, which `status` names as the next step of a task to merge instead of a `land` refused at once or a review to pay twice | on this repository `status` showed an old pass beside an edited worktree, and `next=land` on a moved base (an audit of 0.9.1); a pass under another base or test command proves nothing about this one; a 0.5.0 record has no `needs_review` and would read as documentation; a review asked of merged task 034 exited 2 on git's own `cannot change to`; a commit landing merges nothing, and the operator's merge meets whatever base there is then (2026-09-29) | `test_land_refuses_an_unchecked_patch…`, `test_land_merge_refuses_a_patch_whose_base_moved…`, `test_status_confronts_the_evidence…`, `test_a_review_of_a_merged_task_blocks…`, `test_the_three_landing_guards…` |
| A patch that touches a secret-bearing file (the owner's deny list) or adds a PEM or PGP private key fails its check and is refused a review, which needs no check, so it is neither sent nor committed | the owner's rule: secret-bearing content never goes to another service, and `review` sends the patch to a provider | `test_a_secret_bearing_patch_fails_its_check…` |
| A patch that changes while its tests run was not tested, and its tests stop there (its fingerprint asked every 15 s; point 6c: 264 of 345 such checks ran on, mostly while a review finding was fixed), nor reviewed while it changes: the review takes the fingerprint again once its brief is built, before anything is sent (`patch_moved`), and after the answer (`unavailable`) | tests that rewrite tracked files invalidate their own verdict; beside a review, a test run wrote to the patch between its scan and its brief, and a pass was recorded for bytes the reviewer never read (codex, reviewing task 043) | `test_a_patch_that_moves_under_the_tests…`, `test_the_reviewer_reads_the_patch_that_was_scanned…` |
| Tests run with the worktree as working directory, `DEV_AI_WORKTREE` exported | TASK-068 on the bench lost three hours to tests importing the main checkout | `test_tests_run_inside_the_worktree…` |
| Tests are judged by exit code and timeout alone; no output is parsed, and the whole log is kept | TASK-068: an artifact said `passed` beside 28 errors, and a `tail -n 100` capture named none of them | `test_check_fails_on_red_tests_and_points_at_the_log` |
| Configuration is read from the main checkout | a patch cannot change the test command that judges it; the test files and their configuration are part of the patch, and reviewed with it | `test_a_patch_cannot_weaken_its_own_test_command` |
| Every changed path but descriptive documentation (`.md`, `.rst`, `.adoc`, never a harness's instruction files: `AGENTS.md`, `AGENTS.override.md`, `CLAUDE.md`, `SKILL.md`, `.claude/`, `.codex/`…) needs a review; judged on paths, whatever the lines say, deletions included | the word list fired on `token` and not on `jeton`, and b2539df here removed a guard and read neutral | `test_every_change_but_descriptive_documentation_needs_a_review` |
| Out-of-scope files skip the test run and the review, and so does an empty patch: `review` reads the patch as it stands, beside the check, and refuses what the check refuses before its tests | a twenty-minute suite, or a paid review, is wasted on a patch that will be refused anyway; the check and the review ran one after the other, 9.8 and 3 minutes a task on the bench (median since 0.13.0, 2026-09-29) | `test_check_names_every_file_outside_the_scope…`, `test_a_review_needs_no_check…` |
| A scope widens with a reason on record; `land --merge` only within the mandate `start` recorded, and a task from before mandates loads as `commit` | the reviewer reads every widening; a tool upgrade must not grant a merge nobody agreed to | `test_widening_a_scope_needs_a_reason…`, `test_land_merge_is_within_the_mandate…` |
| `drop` removes the worktree and the branch, keeps the record, destroys uncommitted or unmerged work only with `--destroy`, and first moves the ignored files that are not a cache (`__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `.tox`, `node_modules`, `.venv`, `*.pyc`) under `tasks/<slug>/kept/`, as `land --merge` does | dev-pipeline never cleaned up; `git worktree remove` deletes an ignored file without a word, a `.env` copied in to run the suite is not regenerable, and a cache is in every checked worktree, so a refusal would fire every time | `test_drop_destroys_work_that_lives_nowhere_else…`, `test_drop_with_nothing_to_lose…`, `test_land_merge_merges_cleans_up_keeps…` |
| `land --merge` checks the main checkout before committing anything: nothing staged, no file of the patch changed, untracked or ignored there, nor a directory above or below one; the merge is the delivery, so `landing.json` is written when it succeeds, before the worktree and the branch go | no half-done landing; git overwrites an ignored file, or directory, silently; other work there is not the patch's business; a cleanup that failed left a merged task `status` called open (an audit of 0.9.1) | `test_land_merge_checks_the_main_checkout…`, `test_a_cleanup_that_fails_after_the_merge…`, `test_land_merge_refuses_where_the_patch_would_overwrite_an_ignored_file_or_directory` |
| `init` prepares a repository once, from the main checkout: `dev-ai.json` from `--test-command`, the bullets of this repository's own `AGENTS.md` note appended to the target's `AGENTS.md`, `.dev-ai/` excluded; whatever is there is kept, a destination that is a symlink is refused or left alone rather than written through, the main checkout is `--show-toplevel` from the checkout and the common dir's `core.worktree` from a worktree (right under `--separate-git-dir` too). It writes no harness rule: the installer adds them to the operator's user settings, once — Claude Code's five verbs allowed (`land` not) and `dev-ai *` out of the sandbox, codex's `~/.codex/rules/dev-ai.rules` (five verbs `allow`, `land`, `drop`, `clean`, `init` `prompt`), opencode's `ask` for `land`, `drop`, `clean` and `init` after his rules, where they would allow the verb; and `start` defaults to the `commit` mandate and takes an author among claude, codex, opencode and a human. The installer deletes nothing, and at the command's path replaces nothing: it writes its link where nothing stands, knows the one it wrote, its worktree gone or not, and refuses whatever else is there | The bench was migrated by hand on 2026-09-20: the note was pasted three times before it was single-sourced, and the skill could only say "stop"; the operator's own `~/.claude/CLAUDE.md` links into a vault; codex reproduced writes outside the checkout in three ways; the owner asked on 2026-09-21 for a flow that runs unprompted except what destroys, and what 0.6.0 took away was a user-wide grant, not a repository's own; on 2026-10-02, codex asking at every command and a hand-written `dev-ai` taking only the bare command out of the sandbox, he chose a codex rule per repository and `dev-ai *` out; on 2026-11-04, Claude Code's trust prompt warning on every repository about the rules `init` had written there, he moved Claude's to his user settings; on 2026-11-11 (an audit of his settings) he took `land`'s allow away, as an agent records its own `merge` mandate at `start` and the allow let `land` merge with no prompt and no classifier; opencode wrote none of the 194 tasks on record, and a removal through a link had deleted a shared skill (2026-09-25): on 2026-09-29 he ruled both out, and took opencode back on 2026-10-27; reviewing that patch (task 034), codex found `ln -sfn` replacing a file, then a link, of the operator's at the command's path, a rule that told his links from ours by where they led taking one to this repository's README and refusing the installer's own, its worktree gone: he ruled that nothing there is replaced; on 2026-09-29, that a refusal the command line makes is not made again in the code | `test_start_refuses_a_bad_name…`, `test_what_stands_at_the_command_path…`, `test_init_prepares_a_repository_once…`, `test_opencode_asks_what_destroys…`, `test_init_never_writes_through_a_symlink…`, `test_main_root_is_the_checkout_under_a_separate_git_dir_too` |
| Another harness, codex, claude or opencode, reviews the exact patch, read-only, in one attempt, or the author's harness when `--model` names a model other than the recorded `--author-model`; a model is named for every review, and the reviewer is codex, claude or opencode, the last through its plan agent, never `--auto`, under a config that denies every tool but read, grep, glob and list, `.env` files unread; codex and claude start with no MCP server, plugin or app, which act outside their sandbox: codex lists its servers and turns each one off, a list it cannot give leaves the review `unavailable`, and its config, hooks included, stays loaded; a model known to be the author's is refused everywhere, and so is the author's harness with no author model recorded; `--model` is asked for, never observed, and so is a reasoning effort, `high` unless `--effort` names another; the reviewer's CLI is started without `ANTHROPIC_API_KEY`, on the harness's own login | codex's own config on the owner's machine set its effort to `low`, so every codex review ran at low, and he ruled the effort asked as the model is (2026-10-02); on task 021 that key, set in the environment, overruled the claude.ai login and was at its usage limit: both claude reviews were `unavailable` in six seconds, and the owner ruled "not the API key, the session" (2026-09-21); a different model catches what same-provider stages pass (TASK-045, 046); on TASK-063 claude reviewed claude's patch with no model named; on 2026-09-20 the owner ruled that the model, named, is the point and the harness a proxy; on the bench opencode's default free model passed task-072 and task-089 with no finding, a blocking finding in 11 % of its runs against 67 % of codex's, and he ruled that a model is named every time and that opencode reviews no more (2026-09-29); on 2026-10-27 he took it back as author and reviewer, its model named like any other's; MCP tools ran in 493 of 1 109 codex review logs, 73 of them turning to `ctx_execute` right after a hook blocked a shell command, and on an operations repository context-mode's `ctx_execute` sourced the patched script outside codex's read-only sandbox (2026-10-27) | `test_the_other_harness_reviews_the_checked_patch_read_only`, `test_the_codex_reviewer_runs_with_each_mcp_server_off`, `test_the_reviewer_is_another_harness…`, `test_a_review_names_its_model…`, `test_the_reviewer_runs_on_the_harness_login…` |
| A `critical` or `high` finding the author refuted blocks `land` until a reviewer, under the same independence rule, reads the patch and the author's evidence in one call and answers `withdrawn` (settled) or `maintained` (confirmed: the patch fails); an answer that is not that, for every refuted finding, leaves them open. A pass recorded over a refutation before this rule awaits the reviewer too; a changed patch is reviewed afresh. dev-ai never stops the operator | from 2026-09-20 such a landing waited for his `APPROVE TASK<nn>`, but he could only approve blindly: on the bench last-step-notice, records-ceiling-last-turn, joins-evidence-grader and canary-precheck-complete each landed on his word and the same defect came back as a Fixes-task (4 of 91 tasks with a refutation); he ruled that the reviewer, not he, reads a refutation (2026-10-27) | `test_a_refuted_finding_goes_back_to_the_reviewer…`, `test_a_maintained_finding_fails_the_patch…`, `test_a_review_passed_over_a_refutation_before_this_change…` |
| The reviewer judges against an optional spec, 80 lines at most, recorded at `start` in the main checkout | on the bench the serious catches were breaches of declared invariants (TASK-038, 045), and that contract cost 6 to 17 hours per task | `test_the_reviewer_judges_against_the_short_spec…` |
| A `critical` or `high` finding is `pending` until resolved with evidence: `confirmed` fails the patch, `refuted` sends it back to the reviewer; a run of the same patch never erases a pending, confirmed or refuted one: a fresh review is asked only of a pass with nothing refuted, for a second opinion | the reviewer's severity is a claim, and a rerun until it passes is not a resolution; a second run read a refuted patch clean and the merge went through unread (an audit of 0.9.1) | `test_a_blocking_finding_is_pending…`, `test_a_confirmed_blocker_fails_the_patch…`, `test_a_maintained_finding_fails_the_patch…` |
| Anything but a well-formed answer is `unavailable`, never `pass`, a `fail` that names no finding included; the whole output is kept, and the message names every reviewer left to run the command again with | TASK-068: a reviewer died on `provider_error`, its wrapper had discarded stderr; a fallback chain was a steady source of fixes, and `--fallback`, one attempt of that kind, stood in for a reviewer once after 0.13.0 (2026-09-29) | `test_anything_but_a_well_formed_answer_is_unavailable…`, `test_an_unavailable_review_names_every_way_out…` |
| A patch that needs a review lands only with a passing check and a passing review of the same fingerprint, the review read on a base that leaves every file of the patch as it was; a record from before findings carried evidence is not one | the review is the check that catches what tests miss, and the check, run again on the merged tree, judges the rest; a base moved beside the patch leaves the diff read: settings-all-counted was read again after two such merges, and its refuted findings approved a second time (2026-09-29); moved under it, the same bytes can be another diff, a conflict kept on the task's side | `test_a_patch_that_changes_behaviour_lands_only_with_a_passing_review…`, `test_a_review_stands_on_a_moved_base…`, `test_a_review_recorded_before_findings_carried_evidence…` |
| Every command can be run again after any failure; there is no ledger | dev-pipeline's append-only ledger left an escalation with no legal continuation | `test_an_unavailable_review_blocks_and_a_retry…` |
| Every command leaves one log row naming its task, its version and, when blocked, the blocker's kind, a review that ends `pending`, `fail` or `unavailable` included, with its reviewer; `landing.json` and `status` name who reviewed and the model asked for; `KINDS` in `devai/task.py` is the full list of kinds | timings come from the log alone, and a check that never fires must be visible to be removed; the twenty-task routine of 2026-09-28 had to parse `review.log` to count the reviews that blocked and to know who had read a patch | `test_cli_finds_the_task…`, `test_cli_review_exits_by_verdict…`, `test_a_review_that_blocks_logs_its_kind…`, `test_landing_and_status_name_the_reviewer…`, `test_every_blocker_kind_is_registered…` |

## Quality goals, as things one can check

| Goal | Check |
|---|---|
| Speed | suite under 60 s (enforced); `check`'s own overhead within a couple of seconds (`duration_ms` in the log minus `tests.duration_s`); delay to an accepted patch and needless stops, per task (roadmap) |
| Effectiveness | findings confirmed, refuted and missed; defects found after merge |
| Efficiency | one model call per review, none for a documentation patch (budget test: no model outside `review.py`) |
| Maintainability | the budget; functions under about 50 lines; standard library only; one test per invariant above |
| Reliability | fail closed on what judges the patch (`unavailable` is never `pass`), fail open on bookkeeping (the log never fails a command); commands re-runnable at will; no lock file, no state machine, no shell pipeline of our own |
| Contained development | worktree per task, scope on the real diff, every widening with its reason, landing within the mandate, never a push; for the tool itself, the budget and the stop criterion |

## Known limits

- The harness's permission prompt is the approval. A rule that allows every `dev-ai` command user-wide
  removes it; the installer writes none: the rules it adds allow five verbs only, and ask for `land`, `drop`, `clean` and `init`. This prevents accidents, not a determined bypass.
- The model behind a reviewer is asked for (`--model`) and never observed: no CLI reports which one
  answered, and a provider's fallback can change it. The record says `observed unknown` and claims
  independence of harnesses, or, when the operator keeps the author's harness, of requested names
  only; `--author-model`, required of every author but a human, is the identity refused.
- A withdrawn finding is one model's reading of another's evidence, not a proof; the re-examination
  catches a refutation that does not hold, not a reviewer and an author wrong the same way.
- The review sends the patch to a model provider through the operator's own CLI
  login. Only the deny list and a key header are checked; no scanner beyond that.
  The reviewer's flags come from `codex exec --help` (0.155.1) and `claude --help`
  (2.1.278); a CLI upgrade that renames one shows up as `unavailable`, with the
  cause in `review.log`.
- The review brief embeds the whole patch; `dev-ai` caps nothing. Measured once
  with a 6.3 MB patch: codex refuses input above 1 048 576 characters, claude says
  `Prompt is too long`; both exit 1, so `unavailable`. Split large tasks.
- A test run can outlast a harness's shell time limit (ten minutes in Claude
  Code; the bench allows forty). Agents run `check` in the background or leave it
  to the operator; a killed check writes no `check.json`.
- There is no lock. Two checks of the same task at once overwrite each other's
  `test.log`; one operator, one task at a time per worktree.
- `land --merge` run from inside the worktree leaves the shell in a removed
  directory: run it from the main checkout. It lists every ignored file of that
  checkout to spot a collision, the heaviest git call in the tool on a large
  ignored tree, bounded by the 60 s git timeout and unmeasured on the bench. A task
  merged by hand and then dropped reads `dropped` in `status`: git's ancestry is
  the only witness.
- State is local to one machine. Linux and macOS only.
