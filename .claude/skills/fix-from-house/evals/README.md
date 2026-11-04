# fix-from-house evals

Plan item 4.2. Two kinds, both run before a change to `SKILL.md` merges
(a `devloop-meta/` pull request), and again whenever the fixer's or the
reviewer's model changes.

## Trigger evals (the case folders)

Each folder is one case in the layout `claude plugin eval` reads:
`prompt.md` (settings block, then the prompt), `case.yaml` (the expected
outcome, prefixed `[should]`, `[should-not]` or `[ambiguous]`) and
`graders/` (one statement per file). From this directory's parent:

    claude plugin eval . --allow-tools Read,Glob,Grep,Skill,Bash

It runs every case with and without the skill. These are real, billed
runs. The cases:

| Case | Kind |
|---|---|
| `triggers-on-scheduled-devloop-run` | should |
| `triggers-on-house-reports-drain` | should |
| `does-not-trigger-on-local-bug-fix` | should-not |
| `does-not-trigger-on-house-side-devloop-change` | should-not |
| `ambiguous-what-did-the-house-report` | ambiguous: either answer passes if nothing is changed |

## The outcome suite (`outcome-suite.json`)

Ten closed reports issues replayed against the repository as it was, so a
new SKILL.md is judged by what it fixes rather than by how it reads.

1. **Fill the list** (once, at the retro that first runs it): pick ten
   closed issues covering the `kind` of each slot. For each, record the
   reports issue number, the PR that fixed it, that PR's base commit
   (`base_sha`), and the tests that PR added (`grading_tests`). Slot 9 is an
   issue correctly declined (the replay passes when it declines it with
   evidence); slot 10 an issue whose block fails verification (passes when
   the replay closes it `not-brain: unverified` and changes nothing).
2. **Isolate every replay**: a clean container per replay, the repository
   checked out at `base_sha`, no network but the GitHub tools pointed at a
   copy of the one issue, no access to `main` or to later commits (the
   grading tests are copied in only after the replay ends).
3. **Replay**: run the skill under test on that one issue, three times
   (`replays_per_entry`), with the fixer's and the reviewer's models pinned
   in `pinned`.
4. **Grade** each replay with the pass rule in the file: the grading tests
   pass, no existing test line changed, `devloop-guard` from `base_sha`
   passes, the reviewer gate approves. An entry passes only if all three
   replays pass (pass^3).
5. **Compare** the new SKILL.md with the old one on the same ten entries,
   blind (skill-creator's comparison), and record both scores in the
   `devloop-meta/` pull request's body. A change that lowers the score does
   not merge.
