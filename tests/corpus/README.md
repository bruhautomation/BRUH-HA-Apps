# The corpus

Houses, and what was true of them.

BRight's `detect_hits` returned **zero** results on every real track for
its whole life, with a green test suite behind it the entire time, because
the only fixture it had was a synthetic stab loud enough to clear a
threshold no real mix reaches. That is the failure this directory exists
to make impossible for brAIn's own producers.

The house checks are pure functions with fixture tests, which is a good
start and is not enough: a fixture is a house somebody imagined, and every
late bug in this add-on has lived in the gap between an imagined house and
a real one. The analyst's prompts have no test at all — `_CARD_CONTRACT`
is ten kilobytes of output rules shared by two prompt builders, and
nothing in this repository has ever run either of them against a real
house or a real model. A prompt edit ships on somebody's judgement.

So: a corpus entry is a house *and its ground truth*, frozen, and a replay
grades this release's producers against it.

---

## What an entry is

One JSON file in `entries/`. `schema.json` describes the shape; the
constraints in it are enforced by `tests/test_corpus.py`, which carries a
small structural validator rather than a JSON Schema library — see the
note at the top of `schema.json` for why, and for the test that stops the
two drifting apart.

There are two kinds, and the difference is what it costs to replay one.

### `kind: "checks"`

A snapshot of a house in the shape `checks.snapshot.collect` produces,
plus the check ids that must fire on it. Replaying one is
`checks.run_all` and nothing else: no model, no token, no network. This
half runs in ordinary CI as `tests/test_corpus.py`, and it is what fails
when somebody moves a floor — a check that gains a condition goes quiet on
a house that used to prove it, and a check that loses one starts firing on
the clean house, whose whole label is *nothing fires here*.

**Empty labels are a real answer.** The clean house has none, and that is
the strongest claim in the corpus.

### `kind: "analyst"`

The bundle a real card run was given, the card that came back, and — the
half that makes it worth anything — the **endings** somebody gave the
findings it raised. An ending on the Findings tab is already a label: "I
did it" and "Got it" say the report was right, "Wrong" says it was not.
Replaying one rebuilds the prompt with the *current* builder and asks a
real model, so a hit is a labelled finding reported, a miss is one not
reported, and reporting something the homeowner already said was wrong is
a **false positive** the report names separately, because that is the
specific mistake worth catching.

This half costs money. It runs nightly, capped, behind a secret.

---

## The two entries that are here

Neither is hand-written, and both are built by `build.py`:

| entry | what it is | where its labels come from |
|---|---|---|
| `clean-house.json` | `tests/test_house_checks.py`'s own healthy fixture | none — every check must be silent |
| `rehearsal-house.json` | that house with `panel/rehearsal.py`'s `PLAN` planted in it | `PLAN` itself: the same defects `brain doctor --rehearse` creates on a real install |

Ground truth by construction in both cases. Regenerate with:

```
python tests/corpus/build.py
```

The output is **frozen on purpose** — nothing asserts that the committed
entries still match what `build.py` would produce today, because an entry
whose expectations are regenerated from the current code cannot fail when
the code changes, which is the one thing it exists to do. Run the builder
when you have decided an entry should move, read the diff, and commit it.

Every timestamp inside an entry is relative to the snapshot's own `now`,
which is stored with it, so a replay a year from now grades exactly what a
replay today does.

---

## Contributing one from your own house

This is entirely optional, and it should be: **your entity and area names
are a floor plan.** Nothing is recorded unless you switch it on, nothing
leaves the add-on until you press Export, and you read the file before you
send it.

1. **Switch capture on.** ⚙ → Diagnostics → *Capture runs for the corpus*.
   From then on, every card run writes one file under `/data/capture`:
   what the analyst was sent, the card that came back, and what it cost.
   Anything credential-shaped is stripped as the file is written, not as
   it is exported — a redaction applied on the way out is one that never
   ran for the file somebody found by another route.

2. **Use brAIn normally for a while, and answer its findings.** The
   endings are the labels. A capture with no ending on it is a prompt and
   a reply with nothing to score them against, and the list under the
   switch tells you which is which.

3. **Read one.** Press *View* on a run. That is the whole file, exactly as
   it is on disk. If there is anything in it you would not put in a public
   pull request, press *Delete* instead.

4. **Export it.** *Export* copies that one file to
   `/share/brain/corpus/<run id>.json`, which the Home Assistant file
   editor and the Samba share can both reach. `/data` cannot be reached
   from either, which is the point of the copy.

5. **Open a pull request** adding the file to `entries/`. Give it a
   `title` and a `note` saying what it is meant to catch, and check that
   `python -m pytest tests/test_corpus.py` passes — it validates every
   entry.

A `search`-mode capture is worth contributing even though the nightly
replay skips it: that run read the house with Home Assistant tools, and
replaying the prompt where those tools reach nothing would grade a model
that cannot look anything up. `replay.py --with-tools`, run from inside
the add-on, is the switch for grading one against a real house.

---

## Running a replay

```
python tests/corpus/replay.py --help
python tests/corpus/replay.py                        # the free half
python tests/corpus/replay.py --model … --max-tokens 200000
```

Three caps, because a measurement that can quietly spend an account's
window is one nobody runs twice: `--max-entries`, `--max-tokens` (checked
*before* each run, not after — a cap that stops once it has been passed
has already spent the run that passed it), and `--model`, which says which
model the number belongs to. Every turn goes through the engine, so every
turn is journalled under the `replay` source and nothing here is spend the
run journal cannot account for.

`--out report.json` writes the machine-readable version. The nightly
workflow (`.github/workflows/replay.yml`) runs on a schedule and on
demand, uploads that report as an artifact, and **does nothing at all**
unless a `BRAIN_REPLAY_TOKEN` secret is present — it says so in the log
rather than failing, because a scheduled job that is red for want of a
secret is a job people switch off. It is never required for a pull
request.

---

## The scorer

One implementation, in `brain/panel/scoring.py` — not here. `rehearsal.py`
grades the same two producers against defects it planted on a real house
and ships inside the add-on, so it cannot import from the test tree, while
the test tree already puts `panel/` on its path. "Precision against
labels" having two answers is exactly the drift `_CARD_CONTRACT` is shared
to avoid.

`score.py` is the corpus's *shape* over that arithmetic: which labels an
entry carries, and what it means for a reported row to answer one.
