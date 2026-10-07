# The development loop

brAIn learns a house. This is the loop that lets brAIn **learn about itself**:
it uses the add-on the way its owner does, notices what is broken, awkward or
missing, and turns that into evidence a fix can be built from. It is opt-in,
off by default, and documented to users in [`brain/DEVLOOP.md`](../../brain/DEVLOOP.md).

```
  the house (add-on)               private repo            fork + Routine
  ──────────────────               ────────────            ──────────────
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
   its own access, against a fork, through pull requests and CI.
6. **Nothing promotes itself.** A stream reports and a Routine proposes. A
   person, or a merge policy that person chose for a narrow class of change,
   decides what ships.

## Streams

| Stream | What it reports | Costs | Status |
|---|---|---|---|
| `faults` | The `reports.faults` sweep: dead loops and daemons, failing runs, checks that could not look, producers marked Wrong most of the time, the health verdict | nothing | **built (2.17.0)** |
| `outcomes` | Resident verdicts the household contradicted (missed, put back, undone) aggregated per check or scope, so "the first look keeps ignoring leak rows" is an issue, not a hunch | nothing | planned |
| `ux_audit` | A nightly Playwright pass over the real panel on loopback (no ingress login) at phone and desktop widths, running scripted jobs: answer a card, plan a fix, find a fact, discuss a finding. Each `tests/manual/measure-*.mjs` invariant is checked against live data, plus a model's judgement of each screen against `docs/design/ui-redesign-2026-10.md` (confusing copy, dead ends, a control under the floor, a number that disagrees with another) | Claude runs | planned |
| `screenshots` | Attachments for `ux_audit` findings. **Aliased by default**: the panel renders in an audit mode that swaps every name for its alias before painting, so layout and wording bugs survive and the floor plan does not. An "unaliased" sub-option is offered only for the private repository and says so | repo Contents: write | planned |
| `code_gaps` | A read-only Claude run over the add-on's own source *as installed* plus the fault and outcome history: a feature this house would use that the code cannot express, an error path that swallows a reason, a check whose floor this house keeps hitting | Claude runs | planned |
| `ideas` | Suggestions for capabilities and features, grounded in this house's data ("Z-Wave statistics are read every night and nothing charts them"). Filed as `idea`-labelled issues, rate-limited to a few a week | Claude runs | planned |

Every Claude-spending stream answers to `_resident_gate` (credential,
`auto_enabled`, the usage budget) and takes a SCHEDULED seat on `run_queue`,
like any other unattended producer.

## The cloud half

A Routine (`create_trigger`, a fresh session per run) watches the private
repository for new issues and works each one the way this repository's
`CLAUDE.md` demands:

1. Turn the evidence into a test, and **see it fail** on the current code.
2. Fix it, extend a measure script for UI work, and open a PR that links the
   issue.
3. CI, Claude Code Review and Claude Approvals run as on any PR.

Merge policy, suggested:

- **Auto-merge:** CSS, copy and pure-display changes.
- **A person approves:** the action gate, `protected_entities`, the MCP
  chokepoint, credentials, permissions, `automation_writer` and healing.

The skill that holds those instructions will live at
`.claude/skills/fix-from-house/SKILL.md`.
