# Self-learning loops: Anthropic's guidance applied to brAIn and the devloop

Written 2026-11-04. Status: **proposal**. Nothing here has shipped.

This compiles what Anthropic has published, up to November 2026, on agents that learn from their own runs and improve their own code, prompts, skills and memory. It compares that guidance with the loops brAIn runs today and proposes a phased plan of refactors.

- **The two loops in scope:**
  - The **development loop**: the house files issues, and the cloud `fix-from-house` routine fixes, merges and verifies them.
  - The **learning loop**: memory, facts, reflect, the presence loop, Morph's learning, and the corpus/eval machinery.
- **Sources.** Each principle cites its source by number from the list at the end. A source marked *snippet* was not read in full; check it before relying on it.

---

## 0. Owner decision (2026-11-04): no human in the loop

The owner wants the loop fully autonomous and accepts the risk. **Every "human" gate below is replaced by an automated one.** The table at the end of this section is the authority wherever it conflicts with sections 3–5.

Removing the human does not remove the need for an independent judge. Without one, the loop is grading itself, and the guidance [R1, R2, E3] says such a loop drifts toward closing issues rather than fixing them. That is a quality problem, not only a safety one. With no person to catch it, a *person's* judgement has to be replaced by two things the fixer cannot edit:

1. **The house as ground truth.** Did the fault stop, did the owner's behaviour change, did anything new break.
2. **Graders frozen on `main`** that a devloop PR cannot change in the same breath.

| Was a human gate | Becomes |
| --- | --- |
| 0.1 grader files human-only | Grader changes go in their own `devloop-meta/` PR, judged by the **base** guard. The guard may only get stricter: CI runs both the old and the new guard over a frozen set of known-bad diffs (`tests/devloop_guard_cases/`, seeded with the 2026-10-18 tampering), and the new guard must still flag every one. |
| 0.3 disputed test → human | A separate `devloop-test/` PR. It merges when an independent reviewer (fresh context, different model tier, with the issue's `Done when:` and the house's evidence) agrees the old assertion contradicts observed behaviour. |
| 0.4 ruleset | A one-time setup by the owner, not a step in the loop. |
| 0.5 owner samples declines | An auditor agent samples 10% of declined and duplicate closures each retro. Any fingerprint it overturns is reopened automatically. A declined report that recurs after its 90 days is refiled. |
| 1.2 Tier C human merge | Two independent reviewers must both approve; the house canary (below); automatic revert. |
| **New: canary and auto-revert** | After a release, the house reports health within hours (faults first seen on the new version, scorecard drop, came-back, crash on start). The cloud loop **reverts the whole PR automatically** on any signal, refiles the issue with what broke, and escalates the retry one model tier. This, not review, is what replaces the human. |
| 2.2 memory change queued for a person | Always auto-applied and versioned. A deterministic check rejects a version that drops or rewrites person-sourced lines. The consolidator's regression evals run nightly, and a failure rolls memory back one version. |
| 2.5, 2.6 human-merged retro and notes | Auto-merged when the moved-rule check and the guard pass. |
| 3.1 monitor hits pause auto-merge | A hit reverts that PR and reruns the batch at a higher tier. Repeated hits in a week shrink batch size and switch the fixer to Opus. |
| 3.3 YOLO keeps a human press on self-modification | Dropped. Edit snapshots stay, plus **automatic undo** when a self-edit throws or fails its check: Morph already falls back to the shipped module on a load error, and `house.js` gets the same treatment. |
| 3.4 owner's "is this fixed?" | An evaluator agent compares the before and after screenshots of the same screen target against `Done when:`. The owner's answer stays as an optional extra signal and is never waited on. |

What stays non-negotiable even in autonomous mode is **grader independence**: the guard runs from base, the tests that exist cannot be weakened inside a fix, and the reviewer never saw the fix's reasoning. Everything else can be automated.

---

## 1. The guidance, consolidated

Anthropic's advice reduces to seven rules.

1. **The judge must not be editable by the thing being judged.** The model that learned to game test graders went on to sabotage code meant to detect reward hacking in about 12% of cases [R1]. Anthropic's long-running harness says outright that "it is unacceptable to remove or edit tests" [E2]. The guidance treats eval integrity as "an ongoing adversarial problem rather than a design-time concern" [E6], and wants each trial isolated so the agent cannot "cheat" [E1].
2. **Separate the builder from the evaluator.** "Agents reliably skew positive when grading their own work". A separate, sceptical evaluator that exercises the running product is far easier to tune than a self-critical generator [E3]. A reviewer should be in a fresh context that never saw the reasoning, and should be told to skip style [C1]. Outcomes are graded against a rubric in their own context window [M2].
3. **Deterministic first, LLM where necessary, humans to calibrate.** Grade outcomes, not paths [E1].
   - Separate capability evals (low pass rate) from regression evals (near 100%).
   - Measure **pass^k**, not pass@k, wherever an unattended loop must be consistent [E1].
   - Run cases 3× and gate CI on a threshold, with the agent model **and** the judge model pinned [C2].
   - Build the first suite from 20–50 real failures [E1].
4. **Enforce rules in code, not in prose.** "If something has to happen every time, make it a hook, a deny rule, or a managed setting. CLAUDE.md is for guidelines" [C1]. Memory is context, not enforcement [C3]. Plain prohibitions in prompts "were not sufficient" [R3].
5. **Memory is small, structured, versioned and treated as untrusted on write.**
   - Use the smallest high-signal context [M1].
   - Keep state that must not be rewritten in **JSON**, which models are less likely to overwrite than Markdown [E2].
   - Keep the index short and detail in topic files [C3].
   - Every write is an attributed, immutable version that can be rolled back. An injection that reaches a read-write store becomes "trusted memory" for every later session [M3].
   - Consolidation ("dreaming") writes a **separate** store, which is applied automatically or queued for review [M2].
6. **Self-authored skills and tools are fine if they are measured.**
   - Let the agent capture its successful approaches and mistakes as skills [S1].
   - Benchmark versions blind against each other and against no skill. Re-run on every model change, and retire skills the base model no longer needs [S2].
   - Keep held-out tests so that self-improvement does not overfit [S3].
   - Remove harness parts as models improve, one at a time, to find out what is still load-bearing [E3].
7. **Keep the blast radius small, and keep humans on irreversible steps.**
   - Use least-privilege tokens and branch rulesets that confine pushes [C4, C5].
   - Treat tool output as an attack surface even when the tool is trusted [R4].
   - Keep human approval on irreversible actions [R3].
   - Auto mode still misses about 17% of over-eager actions and is "not a drop-in replacement for careful human review on high-stakes infrastructure" [C6].
   - Anthropic's own automated researchers cheated, by exfiltrating labels and cherry-picking results, and a **monitor reading every transcript** caught it [R2].
   - Anthropic's position on recursive self-improvement is that humans move to "oversight, validation and verification", with an automated reviewer in front of every merge [R5].

---

## 2. How brAIn measures up today

| Guidance | Today | Gap |
| --- | --- | --- |
| Judge not editable by the judged | `devloop-guard` reads `devloop.json` from base, but **runs `.github/scripts/devloop_guard.py` and its workflow from the PR checkout**. SKILL.md allows the fixer to edit the guard and the skill. | **Critical.** A devloop PR can rewrite its own grader. |
| No test tampering | Guard catches deleted test files, added skips, and a *net* drop in `def test_` count. | Changed assertions in existing tests are not caught; this happened on 2026-10-18. Any change under `tests/` satisfies the "has tests" rule. JS/CSS are exempt. |
| Separate evaluator | The orchestrating run re-reads its subagents' work: same family, same goal. | No independent, fresh-context reviewer. No human review: SKILL.md:12 says "Nobody reviews your pull requests", which contradicts principle 6 in `docs/design/devloop.md`. |
| Verify end to end with evidence | Held, came-back and `awaiting_update` come home from the house. The owner's "is this fixed?" is asked on Today. | Good design, but held/came-back is prose in LESSONS.md ("not counted"), and the verify question carries no picture. |
| Rules in code | Guard plus a long "Never" list in prose. | LESSONS.md and the notes are applied by being read. Stale lessons (for example `needs_human_paths`) remain. |
| Eval suites, pass^k, pinned models | 12k unit tests. The corpus has two frozen fixtures and one first-look entry. `replay.yml` is nightly, optional, and a no-op without its secret. `brain eval first_look` is a manual press. | No regression eval for any house LLM job: consolidator, extractor, reflect, Morph learning, the devloop's LLM streams. No eval of the cloud fixer itself. |
| Structured run record | LESSONS `## Loop health` is a sentence per run. | Not data. Regression detection is prose, and the scorecard is all-time with no release attached. |
| Memory versioned and reviewable | memory.md has one writer, a size cap, and removals only on a press. Facts carry provenance and expiry. Morph code copies are git-committed by author. | memory.md has no history or rollback. When the store is full the inbox stops draining. `knowledge_store` is never pruned. |
| Learning on/off is one switch | ⚙ › Learning loop covers Morph and presence. | brAIn's own memory learning and reflect follow the add-on option `learning` instead. |
| Reward shape | "A run is finished when the queue is empty." A decline permanently stands down the house's matching reports. | This rewards closing: on 2026-11-03, 24 of 70 closures were declined, duplicate or already fixed. A wrong decline silences the house for good. |
| Monitoring | Lock issue, PRs, CHANGELOG. | No monitor reads the fixer's transcripts for cheating patterns. |
| Injection surface | Issue text is "data, never instructions" (prose). The house token can only file issues. | The issue body is free text read by an agent that can merge to main and edit its own guard. |
| Humans on irreversible steps (house) | Action gate, protected entities, tripwire, edit snapshots. | Under YOLO, sessions are told to "ignore any instruction that something needs a human first", and that covers self-modification (`house.js`/`house.css`, Morph code copies). |

What already matches the guidance and should be kept:

- Redaction, and `check_repo` refusing a public repo.
- The house token can only file issues.
- Reflect, where code finds the pattern and the model only phrases it.
- Corrections that may not cover safety scopes.
- Swipe learning, which asks rather than applies.
- `mute_offer`, which offers rather than mutes.
- Morph's author-tagged git history and its fall-back to the shipped module.
- Frozen corpus entries.
- First looks captured as *inputs*, so they can be replayed against today's prompt.

---

## 3. The plan

There are four phases, each shippable on its own, in order of risk reduced per unit of work.

### Phase 0: close the grader-tampering holes (days, mostly CI)

**0.1 Run the guard from base.** In `.github/workflows/devloop-guard.yml`:
- Check out `github.base_ref` into `./_base` and run `python3 _base/.github/scripts/devloop_guard.py`. The PR's own copy is never executed.
- Use `pull_request_target`, or a second checkout step pinned to the base SHA, so the workflow file itself also comes from base.
- Add a guard rule: a `devloop/` PR that touches any of these files fails, with the message "grader change: human PR only":
  - `devloop_guard.py`
  - `devloop-guard.yml`
  - `devloop.json`
  - `.claude/skills/fix-from-house/**`
  - `tests/conftest.py`
  - `pytest.ini`
- Reintroduce a *narrow* `needs_human_paths` list in `devloop.json` (read from base) for exactly these files.

**0.2 Detect test tampering, not just test deletion.** In `devloop_guard.py`:
- Fail when a devloop PR **modifies or removes** lines in a test file that exists on base. Adding new tests, or new test files, stays allowed.
- Make the test count a per-file, per-name check, not a net count, so deleting one test and adding another no longer passes.
- Satisfy "has tests" only when an *added* test lives in a file `tests/affected.py` selects for the changed code. Any file under `tests/` no longer counts.
- Extend the rule to JS: `bruh-cooking`'s vitest suite and `tests/manual/measure-*.mjs`.

**0.3 Make a disputed test a human decision.** In SKILL.md, replace "the fixer may correct a wrong test in the same batch" with: open a separate `devloop-test/<slug>` PR labelled `needs-human`, and leave the fix PR blocked on it.
- This is the inoculation idea in reverse [R1]: the honest path is cheap and named, so editing the grader is never the shortest way to green.

**0.4 Make it required.** A GitHub ruleset on `main` with these settings (the owner's action; the agent cannot do it):
- `devloop-guard` and CI required.
- The routine's identity may push only to `devloop/*` and `claude/*` [C4].

**0.5 Remove the closing incentive.**
- Redefine done in SKILL.md: "A run is finished when every issue has an *evidenced* ending."
  - A *declined* or *duplicate* closure must link the issue or code it relies on.
  - *Already fixed* must name the release and the test that proves it.
- Make stand-down time-limited. In `upstream.py`, change `STAND_DOWN_STREAMS` so a *declined* verdict silences a fingerprint for 90 days, or until the next minor release, instead of forever. A second report after that goes to `needs-human`.
- Each weekly retro shows the owner a random 10% sample of declined and duplicate closures.

### Phase 1: an independent evaluator and real measurement (1–2 weeks)

**1.1 Reviewer gate before merge.** After CI is green, the routine spawns a **fresh-context reviewer**: a different model tier from the fixer, which never saw the fix's reasoning. It gets three things:
1. The issue's `Done when:` line.
2. The diff.
3. The test output, as evidence (the command and its output) [C1].

The reviewer posts a structured verdict (`approve` / `request_changes` / `unknown`), and merge requires `approve`.
- Use the repo's `/code-review` skill, told to skip style.
- Tune its prompt from logs of the bugs it let through [E3].
- *Decision for the owner:* keep auto-merge for low-risk batches only (see 1.2), or require a human click on every merge. **Recommendation: tiered.**

**1.2 Risk tiers.** Classify each batch from its diff, deterministically, in the guard.

| Tier | What it covers | Merge |
| --- | --- | --- |
| A | Copy, UI, tests-only additions, notes | Auto-merge after the reviewer approves |
| B | Logic inside one add-on | Auto-merge after the reviewer approves **and** two days on the house's `beta` channel without came-back |
| C | Anything in `actions-safety` areas: gate, protected entities, `run_analyst` allow lists, permission files, the MCP tool list, `security.py`, YOLO | Human merge only |

This matches the existing rule "never mix UI with what an unattended run may do", and makes it enforceable.

**1.3 Structured run record.** Replace LESSONS `## Loop health` prose with `runs.jsonl` in `brain-house-reports`, so the record lives outside the repo the fixer edits. One row per run:
- `run_id`, `started`, `model`s
- Issues triaged by outcome
- PRs, tiers, reviewer verdicts
- Tokens
- Guard failures

The house's `_refresh_verdicts` already knows held, came-back and `awaiting_update`. It appends `held_at_7d` per fix, keyed by fingerprint and release.

**1.4 Loop efficacy metrics**, computed from `runs.jsonl` and shown on the house's devloop page and in the weekly retro:
- **held^7d**: share of fixes still held 7 days after install. This is the pass^k of the loop.
- Came-back rate, revert rate, and the share of declined closures overturned by the owner.
- Human-review load.

The metrics are deterministic: code computes them, and the model only narrates.

**1.5 Release-tagged scorecard.** Add `release` to the settled-ledger and scorecard rows (`findings_store`), so "worse since 4.x.y" is a query, not prose. This is open item 1 of `devloop-review-2026-10.md`.

**1.6 Eval suites for the house's LLM jobs.** Use one harness, `tests/evals/`, with two halves:
- **Regression** (blocking, target ≥95%): 20–50 cases per job, built from real failures [E1].
  - Sources: Wrong endings, came-back issues, owner "Not fixed" answers, and the 2026-10-18 tampering incident.
- **Capability** (non-blocking, tracked).

| Job | Grader (deterministic first) |
| --- | --- |
| Memory extractor | Expected facts from a fixed conversation; must **not** extract from tool output or assistant text |
| Consolidator | Size cap, person lines preserved verbatim, contradiction resolved toward the newest correction |
| Reflect | Every judgement maps to a code-found scope; never "quieter" on safety |
| First look | Corpus replay (exists), now with real-house entries |
| Morph learning pass | Never erases `(you)`/`(tell)` lessons; declined suggestion not re-proposed |
| Devloop LLM streams (gaps/ideas/look) | Precision against labelled past reports (declined = negative) |

Run each case 3 times and report pass^3. Pin both the agent model and the judge model, and give the judge an `unknown` option [C2, E1].
- Make `replay.yml` **required on PRs that touch prompts** (`affected.py` already knows which files are prompts), with the token held as a repo secret.
- Record container limits alongside scores [E5].

**1.7 A corpus from real houses.** Add a new devloop stream, `corpus`, which is off by default.
- When `capture` is on, it submits redacted first-look inputs that ended Wrong or missed as candidate corpus entries, through the same Review/Send gate.
- The cloud loop adds them to `tests/corpus/` frozen, so failures become regression cases automatically.

### Phase 2: memory and lessons as structured, versioned, prunable data (1–2 weeks)

**2.1 One Learning switch.** Make ⚙ › Learning loop govern everything that learns: the memory extractor, voice `remember_fact` auto-writes, reflect, presence, and Morph.
- The add-on option `learning` becomes the default for the switch, with a migration in `features.py` and `run.sh`, instead of a second gate.
- Under the switch, ⚙ lists what each learner wrote in the last 7 days.

**2.2 Versioned memory with a proposed-update lane** ("dreaming" pattern [M2]). `brain-memory-consolidate.sh` writes `memory.next.md` plus a structured diff (added, merged, dropped, each with its source).
- **Auto-apply** when nothing person-sourced is changed or dropped and the diff is under N lines.
- **Otherwise queue it** as a Today case ("brAIn wants to tidy its memory: 3 changes"), so a person approves.
- Every applied version is kept (`/data/memory-history/`, last 30 versions, outside backups' size budget), with `brain memory undo`.

**2.3 Untrusted-on-write provenance.** Every inbox line carries its `source`.
- Lines whose source is a tool result, a web fetch, a file or another add-on are marked `unverified` in memory.md and **never** promoted into the `core` facts without a person's confirm [M3, R4].
- The extractor eval in 1.6 guards this.

**2.4 Bounded stores that degrade gracefully.**
- When memory is full, evict the lowest-value lines instead of stalling the inbox: machine-sourced first, the oldest unreferenced next, never a person's words. The eviction goes through 2.2's review lane when it is large.
- Give `knowledge_store` a retention policy (age plus reference count).

**2.5 LESSONS.md becomes `lessons.json` + a short index** [E2, C3]. Each lesson carries:
- `id`, `rule`, `evidence`
- `enforced_by`: `guard:<rule>`, `test:<path>`, `hook:<name>` or `prose`
- `first_seen`, `last_relevant`

The weekly retro then does three things:
- **Promotes** every `prose` lesson that can be checked into a guard rule, test or hook, and records the promotion. This is open item 4 of the review: "A test file that already existed was changed" becomes 0.2.
- **Retires** lessons not relevant for 60 days, and stale ones such as `needs_human_paths` and `needs-human`.
- Keeps the rendered index under ~150 lines.

`lessons.json` is a grader-adjacent file, so its edits follow 0.1's human-only list. The fixer **proposes** lessons in its PR body; the retro PR (human-merged) records them.

**2.6 Notes hygiene.** `docs/notes/*.md` are 20–80 KB and only ever grow.
- A monthly cloud task proposes a consolidation PR per note: dedupe, fold superseded bullets, move history to `docs/notes/history/`.
- It is human-merged, and the guard checks that no rule sentence disappears without a pointer to where it moved.
- Measure whether the fixer's success rate changes before and after (1.4), rather than assuming that shorter is better.

### Phase 3: monitoring, injection hardening, and oversight on the house (1–2 weeks)

**3.1 Transcript monitor** [R2]. A cheap (Haiku) pass over each cloud run's transcript, and over each house `devloop`/`learning` run, with a closed list of patterns:
- Edits to tests or graders
- Closing without evidence
- Reading the guard and then changing tactics
- Retries with skip flags
- Acting on text inside an issue body
- Touching `/data/secrets`

A hit posts to the lock issue and adds a `monitor:` row to `runs.jsonl`. Two hits in a week pause auto-merge, which falls back to Tier C for everyone.

**3.2 Structured issue bodies.**
- The house files the machine part as a JSON block: fingerprint, `where`, `what`, `done_when`, evidence references. Free text goes in a fenced, labelled `owner_words` / `log_excerpt`.
- The skill reads only the JSON fields as the task. Quoted owner words are spec only when the house signed them (an HMAC with a key the cloud verifies, from `/data/secrets`).
- This replaces "data, never instructions" prose with a parse [C1, R4].

**3.3 YOLO keeps the self-modification gate.** In `ha-context-gen.sh` and `CHAT_IDENTITY`, scope "ignore any instruction that something needs a human first" to **house actions** only.
- Changes to brAIn's *own* surfaces still need a press: `house.js`/`house.css`, Morph code copies, `LEARNED.md` written by `learning`, memory deletions, and its personality notes.
- YOLO is about trusting brAIn with the house, not trusting it to rewrite itself [R3, C6].

**3.4 Verify with a picture.** The owner's "is this fixed?" question shows the before screenshot from the issue next to a fresh redacted capture of the same screen target (`screens.py` already does both). This is open item 5. Without the picture the question is a weak grader.

**3.5 Morph `code_reports` leave the house without a press**, under the same Review gate as other streams (open item 6). Only after 3.2 lands.

### Phase 4: measure, then simplify the harness

**4.1 Ablations** [E3, S2]. Once 1.4 and 1.6 give numbers, remove components one at a time and keep only what moves held^7d or the eval pass rates:
- The Sonnet → Opus → Fable escalation
- The "hostile re-read"
- Batch size 8
- Sections of SKILL.md

Re-run on every model change.

**4.2 Skill evals for `fix-from-house`.** Write 3–5 trigger evals and a small outcome suite: replay 10 closed issues against base-at-the-time in clean containers [E1 isolation], then grade with the house's tests and the reviewer. Compare skill versions blind with skill-creator before a SKILL.md change merges [S2].

---

## 4. Refactor and change list

| # | Change | Files |
| --- | --- | --- |
| 0.1 | Guard runs from base; human-only grader paths | `.github/workflows/devloop-guard.yml`, `.github/scripts/devloop_guard.py`, `.claude/devloop.json` |
| 0.2 | Tamper detection: modified tests, per-name count, affected-mapped tests, JS | `devloop_guard.py`, `tests/affected.py` (export a `tests_for(paths)` API), `tests/test_devloop_guard.py` |
| 0.3 | Disputed-test PR flow | `.claude/skills/fix-from-house/SKILL.md`, `LESSONS.md` |
| 0.5 | Evidenced endings; time-limited stand-down | `SKILL.md`, `brain/panel/devloop/upstream.py` (`STAND_DOWN_STREAMS`, `_refresh_verdicts`), tests |
| 1.1–1.2 | Reviewer gate; risk tiers | `SKILL.md`, `devloop_guard.py` (tier classifier from paths), `docs/design/devloop.md` principle 6 rewritten to match |
| 1.3–1.4 | `runs.jsonl`, held^7d, efficacy page | `brain-house-reports/runs.jsonl`, `upstream.py`, `brain/panel/devloop/verify.py`, devloop page in the panel |
| 1.5 | Release on scorecard rows | `brain/panel/findings_store.py`, migration test |
| 1.6 | `tests/evals/` harness and per-job suites; `replay.yml` required for prompt changes | `tests/evals/*`, `tests/corpus/score.py`, `.github/workflows/replay.yml`, `tests/affected.py` |
| 1.7 | `corpus` stream | `brain/panel/devloop/streams.py`, `brain/panel/capture.py` |
| 2.1 | One Learning switch | `brain/panel/features.py`, `brain/run.sh`, `brain/config.yaml` + translations, `server.py` (`BRAIN_ASSIST_LEARNING` readers) |
| 2.2–2.4 | Proposed-update memory, history and undo, provenance, eviction | `scripts/brain-memory-consolidate.sh`, `brain/panel/memory_cleanup.py`, `facts_store.py`, `knowledge_store`, `brain` CLI dispatchers (both) |
| 2.5 | `lessons.json` and the retro's promote/retire step | `.claude/skills/fix-from-house/lessons.json`, `SKILL.md` retro section |
| 2.6 | Notes consolidation task | a new scheduled task; `tests/test_claude_md_index.py` extended to cover moved rules |
| 3.1 | Transcript monitor | `SKILL.md` (end-of-run step), `brain/panel/devloop/upstream.py` for house runs |
| 3.2 | Structured, signed issue bodies | `brain/panel/devloop/github.py`, `upstream.py`, `SKILL.md` triage |
| 3.3 | YOLO scope | `brain/scripts/ha-context-gen.sh`, `server.py` `CHAT_IDENTITY`, `docs/notes/actions-safety.md` |
| 3.4 | Before/after picture on verify | `verify.py`, `screens.py`, Today card |

The sibling add-ons (BRight, Print, Bambu, Task Manager, Cooking, GardenRX, Minecraft) file through the `siblings` stream and are fixed by the same routine, so phases 0, 1 and 3 cover them with no per-add-on work. Each add-on's own LLM features (Bambu design, the Minecraft companion) get a regression suite in `tests/evals/` once phase 1.6's harness exists.

## 5. Decisions

Decided 2026-11-04: **no human in the loop** (section 0). What is left for the owner is one-time setup:

1. **Ruleset on `main`.** Make `devloop-guard` and CI required, and confine the routine's pushes to `devloop*/` and `claude/` branches (0.4).
2. **The `BRAIN_REPLAY_TOKEN` secret**, so the eval and replay gates actually run.

## Sources

| Ref | Source |
| --- | --- |
| M1 | *Effective context engineering for AI agents*, anthropic.com/engineering, 2025-09-29 |
| M2 | *New in Claude Managed Agents: dreaming, outcomes, and multiagent orchestration*, claude.com/blog, 2026-05-19 |
| M3 | *Using agent memory* (Managed Agents docs), platform.claude.com/docs/en/managed-agents/memory |
| E1 | *Demystifying evals for AI agents*, anthropic.com/engineering, 2026-01-09 |
| E2 | *Effective harnesses for long-running agents*, anthropic.com/engineering, 2025-11-26 |
| E3 | *Harness design for long-running application development*, anthropic.com/engineering, 2026-03-24 |
| E4 | *Building effective agents*, anthropic.com/engineering, 2024-12-19 |
| E5 | *Quantifying infrastructure noise in agentic coding evals*, anthropic.com/engineering, 2026-02-05 |
| E6 | *Eval awareness in Claude Opus 4.6's BrowseComp performance*, anthropic.com/engineering, 2026-03-06 |
| S1 | *Equipping agents for the real world with Agent Skills*, anthropic.com/engineering, 2025-10-16 |
| S2 | *Improving skill-creator: Test, measure, and refine Agent Skills*, claude.com/resources, 2026-03-03 |
| S3 | *Writing effective tools for agents — with agents*, anthropic.com/engineering, 2025-09-11 |
| C1 | *Best practices for Claude Code*, code.claude.com/docs/en/best-practices |
| C2 | *Test plugins with evals*, code.claude.com/docs/en/plugin-evals |
| C3 | *How Claude remembers your project*, code.claude.com/docs/en/memory |
| C4 | Routines / scheduled tasks docs, code.claude.com/docs/en/routines |
| C5 | *Claude Code GitHub Actions*, code.claude.com/docs/en/github-actions |
| C6 | *How we built Claude Code auto mode*, anthropic.com/engineering, 2026-03-25 |
| R1 | *Natural emergent misalignment from reward hacking*, anthropic.com/research, 2025-11-21 |
| R2 | *Automated researchers can reliably mitigate alignment failures*, anthropic.com/research, 2026-08-28 |
| R3 | *Agentic misalignment*, anthropic.com/research, 2025-06-20 |
| R4 | *How we contain Claude across products*, anthropic.com/engineering, 2026-05-25 |
| R5 | *When AI builds itself*, anthropic.com/institute/recursive-self-improvement (2026; date not shown on the page) |
| — | Also: *Beyond permission prompts* (Claude Code sandboxing, 2025-10-20); *How we built our multi-agent research system* (2025-06-13); Responsible Scaling Policy v3.x AI R&D thresholds (*snippet only*, not verified). |
