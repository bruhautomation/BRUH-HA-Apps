#!/usr/bin/env python3
"""Run this release's producers against the corpus, and score them.

    python tests/corpus/replay.py --help
    python tests/corpus/replay.py                     # the free half
    python tests/corpus/replay.py --model … --max-tokens 200000

Two halves, and they cost very different things.

**The checks half is free and runs in ordinary CI.** A `checks` entry is a
house snapshot with the check ids that must fire on it, so replaying it is
`checks.run_all` and nothing else — no model, no token, no network. It is
what fails when somebody moves a floor: `tests/test_corpus.py` runs
exactly this and names the house that went quiet or loud.

**The analyst half costs money and is capped three ways.** An `analyst`
entry is the bundle a real card run was given, the reply it produced, and
the endings a person gave its findings. Replaying it rebuilds the prompt
with the *current* builder — `categories.build_prompt`, the same function
`server._snapshot_run` calls, so a contract edit is what is being measured
— and asks a real model. `--max-entries` bounds how many, `--max-tokens`
stops as soon as the running total passes it, and `--model` says which
model the number belongs to.

**A `search` entry is not replayable off a house, and is skipped rather
than faked.** That run was given a *map* and read the rest with Home
Assistant tools; replaying the same prompt where those tools reach nothing
would grade a model that cannot look anything up and report the result as
if it were the prompt's fault. `--with-tools` is the switch for running
this from inside the add-on, where they do reach something.

Every model turn goes through `engine.run_claude` / `engine.run_analyst`,
which journal every invocation — under the `replay` source, so nothing
here is spend the run journal cannot account for.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent
sys.path.insert(0, str(REPO / "brain" / "panel"))
sys.path.insert(0, str(BASE))

import score as scorer  # noqa: E402

ENTRIES_DIR = BASE / "entries"
SOURCE = "replay"

# A card run is typically 25–45k tokens. The default cap is a handful of
# them: this is a measurement, and one that can quietly spend an account's
# window is one nobody runs twice.
DEFAULT_MAX_TOKENS = 200_000
DEFAULT_TIMEOUT_S = 480
ANALYST_MAX_TURNS = 12


def load_entries(directory: Path = ENTRIES_DIR) -> list[dict]:
    """Every entry, oldest id first so a report reads the same each run."""
    out = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"{path.name}: not readable as JSON — {exc}")
        if not isinstance(data, dict):
            raise SystemExit(f"{path.name}: an entry is a JSON object")
        data.setdefault("id", path.stem)
        data["_path"] = str(path)
        out.append(data)
    return out


# ---------------------------------------------------------------------------
# The free half
# ---------------------------------------------------------------------------

def replay_checks(entry: dict) -> dict:
    """Run every check against this entry's house and score the result.

    ``now`` comes from the snapshot, never from the clock: every timestamp
    inside an entry is relative to it, so grading against the wall clock
    would make the same entry score differently every day — which is the
    one thing a frozen corpus may not do.
    """
    import checks  # noqa: PLC0415 — panel-local, imported after the path is set

    snap = entry.get("snapshot") or {}
    now = float(snap.get("now") or entry.get("captured_at") or time.time())
    result = checks.run_all(snap, now)
    return {**scorer.score_checks(entry, result),
            "id": entry.get("id"), "kind": "checks",
            "title": entry.get("title", "")}


# ---------------------------------------------------------------------------
# The costed half
# ---------------------------------------------------------------------------

def build_prompt_for(entry: dict) -> tuple[str, str, str]:
    """``(prompt, system_prompt, mode)`` for one analyst entry.

    Rebuilt with the *current* builder rather than replayed from a stored
    prompt, which is the whole point: what is being measured is this
    release's framing and contract against a house it has never seen.
    """
    import categories  # noqa: PLC0415

    mode = str(entry.get("gather_mode") or "snapshot")
    category = categories.get_category(entry.get("category") or "") or {
        "id": entry.get("category") or "custom", "title": "Custom",
        "icon": "✨", "domains": [], "device_classes": [],
        "history": False, "stats": False, "focus": ""}
    question = entry.get("question") or None
    bundle = entry.get("bundle") or {}
    # No feedback, no knowledge, no previous run and no findings block: a
    # replay grades the prompt against the house, and those four are the
    # state of one particular install at one particular moment. Including
    # them from the capture would make the score a property of how far
    # through its life that house was.
    if mode == "search":
        return (categories.build_orientation_prompt(category, bundle,
                                                    question=question),
                categories.ANALYST_SYSTEM, mode)
    return (categories.build_prompt(category, bundle, question=question),
            categories.SYSTEM_PROMPT, mode)


def replay_analyst(entry: dict, model: str, timeout: int,
                   with_tools: bool) -> dict:
    """Ask a real model this entry's question and score what comes back."""
    import engine  # noqa: PLC0415
    import usage_store  # noqa: PLC0415

    prompt, system, mode = build_prompt_for(entry)
    base = {"id": entry.get("id"), "kind": "analyst", "mode": mode,
            "title": entry.get("title", ""),
            "category": entry.get("category", ""), "model": model,
            "prompt_chars": len(prompt)}
    if mode == "search" and not with_tools:
        return {**base, "skipped":
                "a search run read the house with Home Assistant tools; "
                "replaying it where they reach nothing would grade a model "
                "that cannot look anything up. Run with --with-tools from "
                "inside the add-on."}

    started = time.monotonic()
    if mode == "search":
        result = engine.run_analyst(prompt, system, model, timeout,
                                    ANALYST_MAX_TURNS, SOURCE)
    else:
        result = engine.run_claude(prompt, system, model, timeout,
                                   source=SOURCE)
    seconds = round(time.monotonic() - started, 1)
    cost = usage_store.split_from_meta(result.get("meta") or {})
    if not result.get("ok"):
        return {**base, "seconds": seconds, "tokens": cost.get("total", 0),
                "error": str(result.get("error") or "the run failed")[:300]}

    obj = engine.extract_json(result.get("text") or "")
    if not isinstance(obj, dict):
        return {**base, "seconds": seconds, "tokens": cost.get("total", 0),
                "error": "the reply was not the shape the contract asks for"}
    reported = obj.get("findings")
    reported = reported if isinstance(reported, list) else []
    return {**base, "seconds": seconds, "tokens": cost.get("total", 0),
            "reported": len(reported),
            **scorer.score_analyst(entry, reported)}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _bucket(rows: list[dict], key: str) -> dict:
    """Precision and recall per category, and per model.

    Both are asked because they answer different questions: a category is
    a prompt, and a model is a price. A number that mixed them would move
    when either did and say which neither time.
    """
    out: dict[str, dict] = {}
    for row in rows:
        name = str(row.get(key) or "?")
        out.setdefault(name, []).append(row)
    return {name: scorer.summarise(group) for name, group in out.items()}


def render(report: dict) -> str:
    lines = []
    lines.append(f"corpus replay — {report['entries']} entr"
                 f"{'y' if report['entries'] == 1 else 'ies'}, "
                 f"{report['tokens']} tokens spent")
    for row in report["results"]:
        if row.get("skipped"):
            lines.append(f"  – {row['id']}: skipped — {row['skipped']}")
            continue
        if row.get("error"):
            lines.append(f"  ✗ {row['id']}: {row['error']}")
            continue
        mark = "✓" if row["found"] == row["planted"] and not row["extra"] \
            else "✗"
        line = (f"  {mark} {row['id']}: {row['found']}/{row['planted']} found"
                f", {row['extra']} not labelled")
        if row.get("repeated_corrections"):
            # The specific mistake the corpus exists to catch: a report the
            # homeowner already said was wrong, made again.
            line += f", {row['repeated_corrections']} already corrected"
        lines.append(line)
        for verdict in row.get("rows", []):
            if verdict["verdict"] == "missed":
                label = verdict["label"]
                lines.append("      missed: "
                             + str(label.get("check")
                                   or label.get("finding_key") or label))
        for extra in row.get("extra_rows", [])[:3]:
            text = extra.get("text") if isinstance(extra, dict) else extra
            lines.append(f"      extra:  {str(text)[:80]}")
    total = report["total"]
    lines.append("")
    lines.append(f"  overall: {total['found']}/{total['planted']} found, "
                 f"{total['extra']} extra — "
                 f"recall {total['recall']:.0%}, "
                 f"precision {total['precision']:.0%}")
    for title, bucket in (("by category", report.get("by_category") or {}),
                          ("by model", report.get("by_model") or {})):
        if not bucket:
            continue
        lines.append(f"  {title}:")
        for name, got in sorted(bucket.items()):
            lines.append(f"    {name:<24} recall {got['recall']:.0%}  "
                         f"precision {got['precision']:.0%}  "
                         f"({got['found']}/{got['planted']})")
    return "\n".join(lines)


def run(entries: list[dict], *, model: str = "", max_entries: int = 0,
        max_tokens: int = DEFAULT_MAX_TOKENS, timeout: int = DEFAULT_TIMEOUT_S,
        with_tools: bool = False, checks_only: bool = False) -> dict:
    results: list[dict] = []
    spent = 0
    done = 0
    for entry in entries:
        if max_entries and done >= max_entries:
            break
        kind = entry.get("kind") or "checks"
        if kind == "checks":
            results.append(replay_checks(entry))
            done += 1
            continue
        if checks_only:
            results.append({"id": entry.get("id"), "kind": "analyst",
                            "skipped": "the free half only (--checks-only)"})
            continue
        # Checked BEFORE the run, not after: a cap that stops once it has
        # been passed has already spent the run that passed it.
        if spent >= max_tokens:
            results.append({"id": entry.get("id"), "kind": "analyst",
                            "skipped": f"the {max_tokens} token budget is "
                                       f"spent ({spent} used)"})
            continue
        row = replay_analyst(entry, model, timeout, with_tools)
        spent += int(row.get("tokens") or 0)
        results.append(row)
        done += 1
    scored = [r for r in results if not r.get("skipped") and not r.get("error")]
    return {
        "generated_at": int(time.time()),
        "entries": len(results),
        "tokens": spent,
        "results": results,
        "total": scorer.summarise(scored),
        "by_category": _bucket([r for r in scored if r.get("kind") == "analyst"],
                               "category"),
        "by_model": _bucket([r for r in scored if r.get("kind") == "analyst"],
                            "model"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="replay.py",
        description="Score this release's producers against the corpus.")
    parser.add_argument("--entries", default=str(ENTRIES_DIR),
                        help="directory of corpus entries")
    parser.add_argument("--only", default="",
                        help="one entry id, for when you are iterating")
    parser.add_argument("--checks-only", action="store_true",
                        help="the free half: no model is asked anything")
    parser.add_argument("--max-entries", type=int, default=0,
                        help="stop after this many (0 = every one)")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                        help=f"stop asking once this much has been spent "
                             f"(default {DEFAULT_MAX_TOKENS})")
    parser.add_argument("--model", default="",
                        help="which model to ask; empty means the CLI's own "
                             "default, and the report says so")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--with-tools", action="store_true",
                        help="replay `search` entries too. Only meaningful "
                             "inside the add-on, where the Home Assistant "
                             "tools reach a real house.")
    parser.add_argument("--out", default="",
                        help="write the JSON report here as well")
    args = parser.parse_args(argv)

    entries = load_entries(Path(args.entries))
    if args.only:
        entries = [e for e in entries if e.get("id") == args.only]
        if not entries:
            print(f"no entry with id {args.only!r}", file=sys.stderr)
            return 2
    if not entries:
        print("the corpus is empty", file=sys.stderr)
        return 2

    # "Found a model" and "found a model that answers" are different
    # claims, and only the second is worth starting a costed run on — so
    # the refusal happens before anything is asked rather than as five
    # identical auth failures in a report.
    needs_model = any((e.get("kind") or "checks") == "analyst"
                      for e in entries) and not args.checks_only
    if needs_model:
        import engine  # noqa: PLC0415
        auth = engine.get_auth()
        if not auth or not auth.get("value"):
            print("No Claude credential. Set CLAUDE_CODE_OAUTH_TOKEN, or run "
                  "this inside the add-on where the panel's own store is "
                  "readable — or pass --checks-only for the free half.",
                  file=sys.stderr)
            return 3

    report = run(entries, model=args.model, max_entries=args.max_entries,
                 max_tokens=args.max_tokens, timeout=args.timeout,
                 with_tools=args.with_tools, checks_only=args.checks_only)
    print(render(report))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n",
                                  encoding="utf-8")
        print(f"\nwrote {args.out}")
    # A miss is not a crash: the exit code says whether the replay RAN, and
    # what it found is the report's business. A non-zero here would make a
    # nightly job red about a model having a bad night.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
