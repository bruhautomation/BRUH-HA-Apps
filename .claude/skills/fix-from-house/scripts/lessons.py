#!/usr/bin/env python3
"""The loop's lessons as data, and the short index rendered from them.

Plan item 2.5. ``lessons.json`` is the record; ``LESSONS.md`` is rendered
from it and never edited by hand (``tests/test_fix_from_house_lessons.py``
fails when the two differ). JSON because state that must not be rewritten
is safer as JSON than as Markdown, and because each lesson then says how it
is held:

    {"id": "2026-10-18-tests-changed-to-pass",
     "rule": "…one line…", "evidence": "…what happened, issue/PR numbers…",
     "enforced_by": "guard:<rule>" | "test:<path>" | "hook:<name>" | "prose",
     "first_seen": "2026-10-18", "last_relevant": "2026-11-03"}

A retired lesson moves to ``retired`` with the day and the reason.

The weekly retro (SKILL.md, step 3):

- ``stale --today D``: lessons not relevant for 60 days; ``retire`` them.
- ``promotable``: the ``prose`` lessons, oldest first, for the retro to
  turn into a guard rule, a test or a hook; ``promote ID --to test:path``
  records it once the check exists (a ``test:`` path must exist; a
  ``guard:`` rule goes through a ``devloop-meta/`` PR).
- ``touch ID --today D`` when a lesson mattered again this week.
- ``render --write`` after any change, so the index matches.

    lessons.py validate | render [--write] | check
    lessons.py add --id ID --rule R --evidence E [--enforced-by X] --today D
    lessons.py touch ID --today D
    lessons.py retire ID --today D --why W
    lessons.py stale --today D [--days 60]
    lessons.py promotable
    lessons.py promote ID --to KIND:REF [--today D]
    lessons.py dates [--retro D] [--ux-audit D] [--notes D] [--ablation D]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
REPO = SKILL_DIR.parent.parent.parent
JSON_PATH = SKILL_DIR / "lessons.json"
MD_PATH = SKILL_DIR / "LESSONS.md"
MAX_LINES = 150
STALE_DAYS = 60
ENFORCED = re.compile(r"^(?:prose|guard:[\w.-]+|test:[\w./-]+|hook:[\w.-]+)$")
ID = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+$")
# Dates the retro keeps beside the two every run reads: the monthly notes
# consolidation (2.6) and the quarterly ablation (4.1).
OPTIONAL_DATES = {"last_notes_consolidation": "Last notes consolidation",
                  "last_ablation": "Last ablation"}
FIELDS = ("id", "rule", "evidence", "enforced_by", "first_seen", "last_relevant")


class LessonError(ValueError):
    pass


def _day(value: str, what: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise LessonError(f"{what} must be a YYYY-MM-DD date") from exc


def load(path: Path = JSON_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(data: dict, path: Path = JSON_PATH) -> None:
    validate(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def validate(data: dict, repo: Path = REPO) -> dict:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise LessonError("lessons.json must be an object with version 1")
    for key in ("last_retro", "last_ux_audit"):
        _day(data.get(key), key)
    for key in OPTIONAL_DATES:
        if key in data:
            _day(data[key], key)
    lessons = data.get("lessons")
    if not isinstance(lessons, list):
        raise LessonError("lessons must be a list")
    seen = set()
    for item in lessons + list(data.get("retired") or []):
        if not isinstance(item, dict):
            raise LessonError("a lesson is an object")
        lid = item.get("id")
        if not isinstance(lid, str) or not ID.match(lid):
            raise LessonError(f"bad id {lid!r}: yyyy-mm-dd-slug")
        if lid in seen:
            raise LessonError(f"{lid} appears twice")
        seen.add(lid)
        for field in FIELDS:
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise LessonError(f"{lid}: {field} must be a non-empty string")
        if "\n" in item["rule"]:
            raise LessonError(f"{lid}: a rule is one line")
        if not ENFORCED.match(item["enforced_by"]):
            raise LessonError(f"{lid}: enforced_by must be guard:/test:/hook:/prose")
        if item["enforced_by"].startswith("test:"):
            ref = item["enforced_by"][5:]
            if not (repo / ref).exists():
                raise LessonError(f"{lid}: {ref} does not exist")
        first = _day(item["first_seen"], f"{lid} first_seen")
        last = _day(item["last_relevant"], f"{lid} last_relevant")
        if last < first:
            raise LessonError(f"{lid}: last_relevant is before first_seen")
    for item in data.get("retired") or []:
        if not isinstance(item.get("retired"), dict) or not item["retired"].get("why"):
            raise LessonError(f"{item['id']}: a retired lesson says when and why")
        _day(item["retired"].get("on"), f"{item['id']} retired.on")
    return data


def render(data: dict) -> str:
    validate(data)
    lines = [
        "# What the development loop has learned",
        "",
        "<!-- Rendered from lessons.json by scripts/lessons.py. Do not edit:",
        "     change lessons.json, then run `python3 scripts/lessons.py render --write`. -->",
        "",
        f"Last retro: {data['last_retro']}",
        f"Last UX audit: {data['last_ux_audit']}",
    ] + [f"{label}: {data[key]}" for key, label in OPTIONAL_DATES.items() if key in data] + [
        "",
        "The fixer reads this index at the start of every run. Each line is one",
        "lesson: its id, how it is held (a guard rule, a test, a hook, or only",
        "`prose`), and the rule. The evidence behind each is in `lessons.json`.",
        "The run record and the loop's health are `runs.jsonl` in the reports",
        "repository (`scripts/runs_record.py render`), not this file.",
        "",
        "## Lessons",
        "",
    ]
    for item in sorted(data["lessons"], key=lambda x: (x["first_seen"], x["id"])):
        lines.append(f"- `{item['id']}` ({item['enforced_by']}): {item['rule']}")
    retired = data.get("retired") or []
    if retired:
        lines += ["", f"{len(retired)} retired lesson(s) are kept in `lessons.json`."]
    text = "\n".join(lines) + "\n"
    count = text.count("\n")
    if count > MAX_LINES:
        raise LessonError(f"the index is {count} lines, over {MAX_LINES}: retire or "
                          "merge lessons")
    return text


def find(data: dict, lid: str) -> dict:
    for item in data["lessons"]:
        if item["id"] == lid:
            return item
    raise LessonError(f"no active lesson {lid}")


def stale(data: dict, today: date, days: int = STALE_DAYS) -> list[str]:
    cutoff = today - timedelta(days=days)
    return [x["id"] for x in data["lessons"]
            if date.fromisoformat(x["last_relevant"]) < cutoff]


def retire(data: dict, lid: str, today: date, why: str) -> None:
    item = find(data, lid)
    data["lessons"].remove(item)
    item = dict(item)
    item["retired"] = {"on": today.isoformat(), "why": why}
    data.setdefault("retired", []).append(item)


def promote(data: dict, lid: str, to: str, today: date, repo: Path = REPO) -> None:
    if not ENFORCED.match(to) or to == "prose":
        raise LessonError("promote to guard:<rule>, test:<path> or hook:<name>")
    if to.startswith("test:") and not (repo / to[5:]).exists():
        raise LessonError(f"{to[5:]} does not exist: write the test first")
    if to.startswith("hook:"):
        settings = repo / ".claude" / "settings.json"
        text = settings.read_text(encoding="utf-8") if settings.exists() else ""
        if to[5:] not in text:
            raise LessonError(f"no hook named {to[5:]} in .claude/settings.json")
    item = find(data, lid)
    item["enforced_by"] = to
    item["last_relevant"] = today.isoformat()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", default=str(JSON_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    r = sub.add_parser("render")
    r.add_argument("--write", action="store_true")
    sub.add_parser("check")
    a = sub.add_parser("add")
    a.add_argument("--id", required=True)
    a.add_argument("--rule", required=True)
    a.add_argument("--evidence", required=True)
    a.add_argument("--enforced-by", default="prose")
    a.add_argument("--today", required=True)
    t = sub.add_parser("touch")
    t.add_argument("id")
    t.add_argument("--today", required=True)
    rt = sub.add_parser("retire")
    rt.add_argument("id")
    rt.add_argument("--today", required=True)
    rt.add_argument("--why", required=True)
    st = sub.add_parser("stale")
    st.add_argument("--today", required=True)
    st.add_argument("--days", type=int, default=STALE_DAYS)
    sub.add_parser("promotable")
    pr = sub.add_parser("promote")
    pr.add_argument("id")
    pr.add_argument("--to", required=True)
    pr.add_argument("--today", default=date.today().isoformat())
    d = sub.add_parser("dates")
    d.add_argument("--retro", default=None)
    d.add_argument("--ux-audit", default=None)
    d.add_argument("--notes", default=None)
    d.add_argument("--ablation", default=None)
    args = ap.parse_args(argv)
    path = Path(args.file)
    md = path.parent / "LESSONS.md"
    try:
        data = load(path)
        if args.cmd == "validate":
            validate(data)
            print("ok")
        elif args.cmd == "render":
            text = render(data)
            if args.write:
                md.write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
        elif args.cmd == "check":
            if md.read_text(encoding="utf-8") != render(data):
                print("LESSONS.md is not the rendering of lessons.json: run "
                      "`lessons.py render --write`", file=sys.stderr)
                return 1
            print("ok")
        elif args.cmd == "stale":
            print(json.dumps(stale(data, _day(args.today, "--today"), args.days)))
        elif args.cmd == "promotable":
            rows = sorted((x for x in data["lessons"] if x["enforced_by"] == "prose"),
                          key=lambda x: x["first_seen"])
            print(json.dumps([{"id": x["id"], "rule": x["rule"]} for x in rows],
                             indent=1, ensure_ascii=False))
        else:
            if args.cmd == "add":
                today = _day(args.today, "--today").isoformat()
                data["lessons"].append({
                    "id": args.id, "rule": args.rule, "evidence": args.evidence,
                    "enforced_by": args.enforced_by, "first_seen": today,
                    "last_relevant": today})
            elif args.cmd == "touch":
                find(data, args.id)["last_relevant"] = _day(args.today, "--today").isoformat()
            elif args.cmd == "retire":
                retire(data, args.id, _day(args.today, "--today"), args.why)
            elif args.cmd == "promote":
                promote(data, args.id, args.to, _day(args.today, "--today"))
            elif args.cmd == "dates":
                if args.retro:
                    data["last_retro"] = _day(args.retro, "--retro").isoformat()
                if args.ux_audit:
                    data["last_ux_audit"] = _day(args.ux_audit, "--ux-audit").isoformat()
                if args.notes:
                    data["last_notes_consolidation"] = _day(args.notes, "--notes").isoformat()
                if args.ablation:
                    data["last_ablation"] = _day(args.ablation, "--ablation").isoformat()
            save(data, path)
            md.write_text(render(data), encoding="utf-8")
            print("ok")
    except LessonError as exc:
        print(f"lessons: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
