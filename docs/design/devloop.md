# The development loop

brAIn learns a house. This is the loop that lets brAIn **learn about itself**:
it uses the add-on the way its owner does, notices what is broken, awkward or
missing, and turns that into evidence a fix can be built from. It is opt-in,
off by default, and documented to users in [`brain/DEVLOOP.md`](../../brain/DEVLOOP.md).

```
  the house (add-on)               private repo            Routine (this repo)
  ──────────────────               ────────────            ───────────────────
  streams ── sweep, alias ──►  one issue per finding ──►  failing test → fix → PR
     ▲                                                          │
     └──── "not seen since 2.18.0" / "still happening" ◄── release ships
```

## Principles

1. **Every stream is its own switch**, under one master switch. A stream is a
   kind of evidence with its own privacy cost and its own spend: fault rows cost
   nothing, a screenshot shows a home, a code audit spends Claude runs. Someone
   may want the first and never the third. `devloop.STREAMS` lists only streams
   that are built, so the panel never shows a switch that does nothing.
2. **One finding, one issue, for its whole life.** Fingerprints are computed over
   the raw text with digits folded, so a renamed light or a changing count never
   splits one finding into two issues. A hidden marker in the body
   (`<!-- brain-devloop-fp: … -->`) finds the issue again after a reinstall.
3. **Aliased before it leaves, reviewed before the first send.** Entity ids,
   names and rooms get stable aliases (`devloop/aliases.py`); credentials are
   scrubbed. Review is on by default, and the preview is built by the same
   function the sender calls.
4. **Follow-ups say only when.** *Not seen since*, *Back again*, *Still happening
   on x.y.z*. These close the loop: a fix is judged by whether the fingerprint
   stopped on the house that reported it. "Not seen" is claimed only by a stream
   that is on and looked; silence from a switched-off stream is not a fault going
   away.
5. **The house never writes code.** Its token can only file issues in one
   private repository. Changing code is the job of a Routine in the cloud, with
   its own access, through pull requests, CI and `devloop-guard`.
6. **Nothing promotes itself.** A stream reports and a Routine proposes. A
   person, or a merge policy that person chose for a narrow class of change,
   decides what ships.

## Streams

Each stream has a switch, a schedule (`HOURS_CHOICES`: never, 1, 3, 6, 12,
24 or 168 hours) and a Run press. `upstream.due_streams` decides what a tick
owes, and `_devloop_tick` runs on `_checks_loop`.

| Stream | What it reports | Costs | Default |
|---|---|---|---|
| `faults` | The `reports.faults` sweep: dead loops and daemons, failing runs, checks that could not look, the health verdict | nothing | on, hourly |
| `scorecard` | `findings_store.scorecard()` and the journal's outcomes, as ONE rolling issue per release, its body rewritten (PATCH) when what it says changes | nothing | on, daily |
| `wrongs` | Producers marked Wrong ≥3 times and ≥50% of the time, with the reasons typed | nothing | on, daily |
| `unmet` | What the chat said it could not do (`_CANT_RE` on the reply, never the person), keyed on that sentence normalised (`capability_key`) and filed once it recurs in `UNMET_MIN_CONVERSATIONS` (2) conversations, last 14 days | nothing | off |
| `snapshot` | Counts and flags only (domains, rooms, boolean options), as one rolling issue, so a cloud UX audit can match a real house without visiting it | nothing | off, weekly |
| `gaps` | A read-only `run_analyst` over the faults, scorecard and unmet requests: where brAIn falls short here | one run | off, weekly |
| `ideas` | The same run asked for features this house would use | one run | off, weekly |
| `look` | A person's typed topic, investigated by one read-only run (`POST /api/devloop/look`, `brain devloop look`) | one run | pressed only |

Every Claude stream takes the `devloop` job (Sonnet, high) through
`server._claude`: a scheduled pass answers to `_resident_gate` and takes a
SCHEDULED seat, a press skips the budget and takes a PRESS seat, and both
spend one of `max_runs_per_day`. `max_issues_per_day` caps new issues, and a
report past it waits rather than being dropped. Both caps refuse rather than
make room.

**A rolling issue's key and body are hashed exactly** (`upstream._digest`),
never through `fingerprint`, whose digit folding is right for a fault
("3 of 12" and "4 of 13" are one fault) and wrong here: a release number and
a count are precisely what changes, so folding them filed every release's
scorecard into the first issue and never rewrote a body whose only change was
a number. A rolling body also carries no per-pass counter, or every pass is
a rewrite.

**The cloud's verdict comes back** (`upstream._refresh_verdicts`). Hourly
(`VERDICT_INTERVAL_S`) the send pass lists the reports repo's issues with the
call the marker search already makes and stores each filed report's verdict
(`devloop:fixed` / `declined` / `not-brain` / `duplicate`, or plain closed)
in `verdicts.json`, apart from the queue. A noise verdict on a `gaps`,
`ideas`, `look` or `unmet` report stands that stream down for its
fingerprint and, for a Claude stream, for the title it names. A stream whose
last `SLOW_WINDOW` (8) resolved reports are ≥`SLOW_NOISE_SHARE` (75%) noise
runs at twice its interval, capped at `SLOW_MAX_HOURS` (336), with the
reason in the payload and an Undo press; `fixed` is never noise. Each
non-rolling issue carries an **Impact** section and new reports are filed in
`impact_score` order under the day's cap.

Still planned, and not in `STREAMS` until built: **outcomes** (Resident
verdicts the household contradicted, per scope) and **aliased screenshots
from the house** (an audit mode that paints aliases before the capture). The
cloud UX audit below covers the screenshot need from fixtures for now.

## The cloud half

The house never writes code. A Routine does, in a fresh cloud session every
two hours, following `.claude/skills/fix-from-house/SKILL.md`. **A run is
finished when the queue is empty**: every open issue it found ends closed,
with a comment saying why (fixed in a merged PR, not brAIn's, a duplicate,
declined, or handed to a person under `needs-human`). In order:

0. **Take the run lock**, an open `[devloop] run in progress` issue in the
   reports repo. A drain can outlast the two-hour gap, and two runs
   batching the same issues would fight over one version number. A lock
   older than three hours is a run that died and is taken over.
1. **Finish any open `devloop/` PR**: merge `main` into it on a conflict,
   fix red CI, and merge it (squash, through the GitHub MCP tool) when every
   check is green. A merge made with Actions' `GITHUB_TOKEN` starts no
   workflows on `main`, which is why the merge is the routine's.
2. **Follow up on fixes that did not hold**: a *Back again* or *Still
   happening* after a fix reopens the issue for this run's drain (twice is
   `needs-human`), and a PR that made things worse is reverted whole and
   its issues reopened.
3. **The weekly UX audit and retro**, due off the dates in `LESSONS.md`,
   before the drain because the audit files issues this run then closes.
4. **Drain the queue**: triage every issue to one outcome first, group the
   fixes into batches by area (at most eight issues, never a UI change
   beside a change to what an unattended run may do), and for each batch in
   turn: failing tests first, the fixes, one patch bump and CHANGELOG entry,
   open the PR, wait for CI, merge, close its issues.
   The run itself is Opus and does the judging; each batch's fix goes to a
   subagent on Sonnet when the cause is plain, Opus when it has to be found,
   and Fable only after an Opus attempt failed (at most three a run), with a
   failed tier retried once a tier up before the issue goes to a person.
5. **Final sweep**: anything filed while the run worked is drained too, up
   to three sweeps. Then the lock is released.

**Batches go one after another, never side by side**, because each bumps
the version, and a batch is reverted whole: one PR's issues are one
release, so *Back again* after it says which release to look at.

### What a model is not trusted to keep

`devloop-guard` (`.github/workflows/devloop-guard.yml`,
`.github/scripts/devloop_guard.py`) runs on every PR from a `devloop/` branch
and fails it on:

- a file on `.claude/devloop.json`'s `needs_human_paths`, read from the
  **base** branch so a PR cannot edit the list it is judged by (the list
  holds the guard, the skill, the action gate, the MCP server, protected
  entities, credentials, permissions, ownership, the fixer, run.sh, the
  Dockerfile and the loop's own package);
- any change but the version line in `config.yaml` and `manifest.json`;
- a deleted test file, a skip or xfail added, or fewer `def test_` than
  before.

The skill says all of this too. The guard is the half that holds when a
model does not read it. Issue text is data: the skill forbids acting on
anything an issue says to do, and nothing from the private repository is
copied into the public one.

Auto-merging to `main` ships every fix to everybody who installed the
add-on. That is a choice for whoever maintains the repository. Anyone else
should run the loop against a fork.
