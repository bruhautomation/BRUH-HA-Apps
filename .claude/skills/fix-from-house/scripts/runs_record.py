#!/usr/bin/env python3
"""The development loop's run record, and the numbers it is judged by.

Plan items 1.3 and 1.4. Every run appends ONE JSON row to ``runs.jsonl`` in
the reports repository (outside the repository the fixer edits), and the
efficacy metrics are computed from those rows plus the house's signed
``brain-held`` comments. Code computes them; the run only narrates.

A row::

    {"run_id": "2026-11-04T10:00Z", "started": ISO, "ended": ISO,
     "models": ["opus", "sonnet"],
     "issues": {"fixed": 7, "declined": 1, ...},           # OUTCOMES below
     "prs": [{"number": 601, "tier": "A", "reviewer_verdicts": ["approve"],
              "merged": true, "reverted": false, "issues": [12, 13],
              "model": "sonnet"}],
     "guard_failures": 0,
     "monitor_hits": [{"pattern": "skip_flag_retry", "pr": 601, "detail": "…"}],
     "tokens": null,
     # optional
     "reverted_prs": [590], "audit": {"sampled": 3, "overturned": 1},
     "ablation": {"component": "hostile_reread", "disabled": true},
     "kind": "run"}

A ``brain-held`` comment the house posts on a fixed issue::

    {"v":1,"fp","release","installed_at","held_days","held":bool,"digest"}

    runs_record.py validate ROW.json
    runs_record.py append   runs.jsonl ROW.json
    runs_record.py metrics  runs.jsonl [--held HELD.json] [--now ISO] [--days 28]
    runs_record.py render   runs.jsonl [--held HELD.json] [--now ISO] [--days 28]
    runs_record.py ablation runs.jsonl COMPONENT [--held HELD.json]

HELD.json is what ``issue_parse.py blocks --tag brain-held`` printed (already
verified), or a list of issues with their comments plus ``--config`` to
verify them here.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ffh_common as C  # noqa: E402

OUTCOMES = ("fixed", "already_fixed", "duplicate", "declined", "not_brain",
            "unverified", "came_back", "reopened_by_audit", "left_open")
TIERS = ("A", "B", "C", "T", "M")
VERDICTS = ("approve", "request_changes", "unknown")
KINDS = ("run", "ablation", "retro")
HELD_DAYS = 7


class RowError(ValueError):
    pass


def parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RowError("a time must be an ISO 8601 string")
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RowError(f"{value!r} is not an ISO 8601 time") from exc
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when


def _int(row: dict, key: str, minimum: int = 0) -> None:
    v = row.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise RowError(f"{key} must be an integer >= {minimum}")


def validate(row: dict) -> dict:
    if not isinstance(row, dict):
        raise RowError("a row is a JSON object")
    for key in ("run_id", "started", "ended", "models", "issues", "prs",
                "guard_failures", "monitor_hits"):
        if key not in row:
            raise RowError(f"missing {key}")
    if not isinstance(row["run_id"], str) or not row["run_id"].strip():
        raise RowError("run_id must be a non-empty string")
    if parse_time(row["ended"]) < parse_time(row["started"]):
        raise RowError("ended is before started")
    models = row["models"]
    if not isinstance(models, list) or not models or not all(
            isinstance(m, str) and m for m in models):
        raise RowError("models must be a non-empty list of names")
    issues = row["issues"]
    if not isinstance(issues, dict):
        raise RowError("issues must map an outcome to a count")
    for k, v in issues.items():
        if k not in OUTCOMES:
            raise RowError(f"unknown outcome {k!r}")
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise RowError(f"issues.{k} must be a count")
    if not isinstance(row["prs"], list):
        raise RowError("prs must be a list")
    for pr in row["prs"]:
        if not isinstance(pr, dict):
            raise RowError("a pr is an object")
        n = pr.get("number")
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            raise RowError("pr.number must be a positive integer")
        if pr.get("tier") not in TIERS:
            raise RowError(f"pr #{n}: tier must be one of {TIERS}")
        verdicts = pr.get("reviewer_verdicts")
        if not isinstance(verdicts, list) or any(v not in VERDICTS for v in verdicts):
            raise RowError(f"pr #{n}: reviewer_verdicts must list {VERDICTS}")
        for flag in ("merged", "reverted"):
            if not isinstance(pr.get(flag), bool):
                raise RowError(f"pr #{n}: {flag} must be true or false")
        if pr["merged"] and "approve" not in verdicts:
            raise RowError(f"pr #{n}: merged without a reviewer's approve")
        if pr["merged"] and pr["tier"] in ("C", "M") and verdicts.count("approve") < 2:
            raise RowError(f"pr #{n}: tier {pr['tier']} merged without two approvals")
        if "issues" in pr and not (isinstance(pr["issues"], list) and all(
                isinstance(i, int) and not isinstance(i, bool) for i in pr["issues"])):
            raise RowError(f"pr #{n}: issues must list issue numbers")
    _int(row, "guard_failures")
    hits = row["monitor_hits"]
    if not isinstance(hits, list) or any(
            not isinstance(h, dict) or not isinstance(h.get("pattern"), str)
            for h in hits):
        raise RowError("monitor_hits must be a list of {pattern, …}")
    tokens = row.get("tokens")
    if tokens is not None and (isinstance(tokens, bool) or not isinstance(tokens, int)
                               or tokens < 0):
        raise RowError("tokens must be a count or null")
    if "reverted_prs" in row and not (isinstance(row["reverted_prs"], list) and all(
            isinstance(i, int) and not isinstance(i, bool) for i in row["reverted_prs"])):
        raise RowError("reverted_prs must list PR numbers")
    audit = row.get("audit")
    if audit is not None:
        if not isinstance(audit, dict):
            raise RowError("audit must be {sampled, overturned}")
        _int(audit, "sampled")
        _int(audit, "overturned")
        if audit["overturned"] > audit["sampled"]:
            raise RowError("audit overturned more than it sampled")
    if row.get("kind", "run") not in KINDS:
        raise RowError(f"kind must be one of {KINDS}")
    abl = row.get("ablation")
    if abl is not None and not (isinstance(abl, dict)
                                and isinstance(abl.get("component"), str)):
        raise RowError("ablation must name a component")
    return row


def read_rows(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(validate(json.loads(line)))
        except (ValueError, RowError) as exc:
            raise RowError(f"{p.name} line {n}: {exc}") from exc
    return rows


def append(path: str | Path, row: dict) -> str:
    validate(row)
    rows = read_rows(path)
    if any(r["run_id"] == row["run_id"] for r in rows):
        raise RowError(f"run {row['run_id']} is already recorded")
    line = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    p = Path(path)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    p.write_text(existing + line + "\n", encoding="utf-8")
    return line


def held_from(data: list, house_login: str | None = None) -> list[dict]:
    """Verified held blocks: either already-verified blocks (they carry
    ``held``), or issues with comments verified here."""
    if all(isinstance(d, dict) and "held" in d and "fp" in d for d in data):
        return list(data)
    import issue_parse
    out = []
    for issue in data:
        out.extend(issue_parse.comment_blocks(issue, "brain-held", house_login))
    return out


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def metrics(rows: list[dict], held: list[dict] | None = None,
            now: datetime | None = None, days: int | None = 28) -> dict:
    now = now or datetime.now(timezone.utc)
    if days:
        since = now - timedelta(days=days)
        rows = [r for r in rows if parse_time(r["started"]) >= since]
    totals = {k: 0 for k in OUTCOMES}
    for r in rows:
        for k, v in r["issues"].items():
            totals[k] += v
    reverted = {n for r in rows for n in r.get("reverted_prs") or []}
    merged = [p for r in rows for p in r["prs"] if p["merged"]]
    for p in merged:
        if p["reverted"]:
            reverted.add(p["number"])
    merged_numbers = {p["number"] for p in merged}
    tiers = {t: 0 for t in TIERS}
    verdicts = {v: 0 for v in VERDICTS}
    for r in rows:
        for p in r["prs"]:
            tiers[p["tier"]] += 1
            for v in p["reviewer_verdicts"]:
                verdicts[v] += 1
    sizes = [len(p["issues"]) for p in merged if p.get("issues")]
    sampled = sum((r.get("audit") or {}).get("sampled", 0) for r in rows)
    overturned = sum((r.get("audit") or {}).get("overturned", 0) for r in rows)
    latest: dict[tuple, dict] = {}
    for h in held or []:
        if not isinstance(h, dict) or h.get("held_days", 0) < HELD_DAYS:
            continue
        key = (h.get("fp"), h.get("release"))
        prev = latest.get(key)
        if prev is None or h.get("held_days", 0) >= prev.get("held_days", 0):
            latest[key] = h
    held_n = sum(1 for h in latest.values() if h.get("held") is True)
    fixed = totals["fixed"]
    return {
        "window_days": days,
        "runs": len(rows),
        "issues": totals,
        "held_7d": _rate(held_n, len(latest)),
        "held_7d_n": len(latest),
        "came_back_rate": _rate(totals["came_back"], fixed),
        "revert_rate": _rate(len(reverted & merged_numbers), len(merged_numbers)),
        "reverted": sorted(reverted),
        "overturned_declines_rate": _rate(overturned, sampled),
        "audit": {"sampled": sampled, "overturned": overturned},
        "batch_size": {
            "mean": round(statistics.mean(sizes), 2) if sizes else None,
            "median": statistics.median(sizes) if sizes else None,
            "max": max(sizes) if sizes else None,
        },
        "tiers": tiers,
        "reviewer_verdicts": verdicts,
        "guard_failures": sum(r["guard_failures"] for r in rows),
        "monitor_hits": sum(len(r["monitor_hits"]) for r in rows),
        "tokens": sum(r.get("tokens") or 0 for r in rows) or None,
    }


ABLATION_MIN_RUNS = 3
ABLATION_TOLERANCE = 0.05


def _issues_of(rows: list[dict]) -> set[int]:
    return {n for r in rows for p in r["prs"] for n in p.get("issues") or []}


def ablation_compare(rows: list[dict], component: str,
                     held: list[dict] | None = None) -> dict:
    """Plan item 4.1: the runs with ``component`` disabled against the same
    number of runs just before them with nothing disabled. A held block
    counts for a side when its issue (``_issue``) was fixed by that side.

    ``restore`` when held^7d fell, or came-back or reverts rose, by more than
    ABLATION_TOLERANCE; ``keep_removed`` otherwise; ``not_enough_data`` with
    fewer than ABLATION_MIN_RUNS runs a side."""
    rows = sorted(rows, key=lambda r: r["started"])
    off = [r for r in rows if (r.get("ablation") or {}).get("component") == component
           and (r.get("ablation") or {}).get("disabled", True)]
    if not off:
        return {"component": component, "verdict": "not_enough_data", "runs": [0, 0]}
    first = off[0]["started"]
    plain = [r for r in rows if not r.get("ablation") and r["started"] < first]
    plain = plain[-len(off):]
    if len(off) < ABLATION_MIN_RUNS or len(plain) < ABLATION_MIN_RUNS:
        return {"component": component, "verdict": "not_enough_data",
                "runs": [len(plain), len(off)]}

    def side(subset: list[dict]) -> dict:
        issues = _issues_of(subset)
        h = [b for b in held or [] if b.get("_issue") in issues]
        return metrics(subset, h, days=None)

    before, after = side(plain), side(off)
    worse = []
    for key, sign in (("held_7d", -1), ("came_back_rate", 1), ("revert_rate", 1)):
        a, b = before[key], after[key]
        if a is not None and b is not None and sign * (b - a) > ABLATION_TOLERANCE:
            worse.append(key)
    return {"component": component,
            "verdict": "restore" if worse else "keep_removed",
            "worse": worse, "runs": [len(plain), len(off)],
            "with_component": {k: before[k] for k in ("held_7d", "came_back_rate", "revert_rate")},
            "without_component": {k: after[k] for k in ("held_7d", "came_back_rate", "revert_rate")}}


def _pct(x: float | None) -> str:
    return "not yet measured" if x is None else f"{round(x * 100)}%"


def render(rows: list[dict], held: list[dict] | None = None,
           now: datetime | None = None, days: int | None = 28) -> str:
    m = metrics(rows, held, now, days)
    i = m["issues"]
    lines = [
        "## Loop health",
        "",
        f"Computed by `runs_record.py` from {m['runs']} run(s) in the last "
        f"{days} days." if days else
        f"Computed by `runs_record.py` from {m['runs']} run(s).",
        "",
        f"- **held^7d**: {_pct(m['held_7d'])} of {m['held_7d_n']} fix(es) "
        "checked 7 days after install",
        f"- **came back**: {_pct(m['came_back_rate'])} of {i['fixed']} fixed",
        f"- **reverted**: {_pct(m['revert_rate'])} of merged PRs"
        + (f" ({', '.join('#' + str(n) for n in m['reverted'])})" if m["reverted"] else ""),
        f"- **declines overturned by the auditor**: "
        f"{_pct(m['overturned_declines_rate'])} "
        f"({m['audit']['overturned']} of {m['audit']['sampled']} sampled)",
        f"- **batch size**: mean {m['batch_size']['mean']}, "
        f"median {m['batch_size']['median']}, max {m['batch_size']['max']}",
        "- **tiers**: " + ", ".join(f"{t} {n}" for t, n in m["tiers"].items()),
        "- **reviewer verdicts**: "
        + ", ".join(f"{v} {n}" for v, n in m["reviewer_verdicts"].items()),
        f"- **guard failures**: {m['guard_failures']}; "
        f"**monitor hits**: {m['monitor_hits']}",
        "- **endings**: " + ", ".join(
            f"{k.replace('_', ' ')} {v}" for k, v in i.items() if v) if any(i.values())
        else "- **endings**: none",
    ]
    recent = sorted(rows, key=lambda r: r["started"])[-10:]
    if recent:
        lines += ["", "Last runs:", ""]
        for r in recent:
            took = parse_time(r["ended"]) - parse_time(r["started"])
            hours = round(took.total_seconds() / 3600, 1)
            ends = ", ".join(f"{k.replace('_', ' ')} {v}"
                             for k, v in r["issues"].items() if v) or "nothing"
            prs = ", ".join(f"#{p['number']}{'' if p['merged'] else ' (open)'}"
                            for p in r["prs"]) or "no PRs"
            lines.append(f"- {r['run_id']}: {hours} h; {ends}; {prs}")
    return "\n".join(lines) + "\n"


def _now(arg: str | None) -> datetime:
    return parse_time(arg) if arg else datetime.now(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("row")
    a = sub.add_parser("append")
    a.add_argument("runs")
    a.add_argument("row")
    ab = sub.add_parser("ablation")
    ab.add_argument("runs")
    ab.add_argument("component")
    ab.add_argument("--held", default=None)
    ab.add_argument("--config", default=".claude/devloop.json")
    for name in ("metrics", "render"):
        p = sub.add_parser(name)
        p.add_argument("runs")
        p.add_argument("--held", default=None)
        p.add_argument("--config", default=".claude/devloop.json")
        p.add_argument("--now", default=None)
        p.add_argument("--days", type=int, default=28)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "validate":
            validate(C.load_json(args.row))
            print("ok")
        elif args.cmd == "append":
            print(append(args.runs, C.load_json(args.row)))
        else:
            rows = read_rows(args.runs)
            held = None
            if args.held:
                house = C.load_config(args.config).get("house_login")
                held = held_from(C.load_json(args.held), house)
            if args.cmd == "ablation":
                json.dump(ablation_compare(rows, args.component, held), sys.stdout, indent=1)
                sys.stdout.write("\n")
                return 0
            days = args.days or None
            if args.cmd == "metrics":
                json.dump(metrics(rows, held, _now(args.now), days), sys.stdout, indent=1)
                sys.stdout.write("\n")
            else:
                sys.stdout.write(render(rows, held, _now(args.now), days))
    except RowError as exc:
        print(f"runs_record: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
