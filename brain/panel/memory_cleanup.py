"""Memory clean-up — what brAIn knows that is wrong, useless or an error.

Memory only ever grows. The consolidator merges what it is handed, the facts
store keeps every line that passes through the inbox, and nothing ever
reads the whole of either and asks whether a line still deserves its place:
a device that was replaced, a guess that was wrong, a one-off evening filed
as a habit, a line about brAIn's own bookkeeping, the same fact three ways.
Every run is handed those lines as true.

One press reads both — the document's lines and the facts store's rows —
with Home Assistant's reading tools, and PROPOSES what to remove, each with
a reason. Nothing is removed until a person ticks it and presses Apply,
and four rules hold what comes back to the same standard as every other
proposal:

  * **Only what was offered may be named.** Every line carries an id this
    module handed out (`doc:<n>`, `fact:<id>`); a row naming anything else
    is dropped and counted, because "removed a line it invented" is not a
    clean-up.
  * **A reason from a closed set** (`REASONS`), and a sentence saying why.
    A removal with no reason is a removal nobody can check.
  * **What a person said is not offered.** Corrections, facts somebody
    typed, and the rules a Wrong press wrote (`exception:`, `judgement:`)
    stay out of the digest: the document is a summary, and a summary being
    tidied is not the person withdrawing what they said — `facts_store`'s
    `KEEP_SOURCES` reason, one module over.
  * **The document still has one writer.** A removed document line is a
    `FORGET:` line queued to the memory inbox and a consolidation pass —
    the consolidator removes it, as it does for `brain memory forget` — and
    a removed fact is `facts_store.forget_ids`. Nothing here writes
    `memory.md`.
"""
from __future__ import annotations

import json
import os
import re
import time

import atomic_write
import facts_store

STORE = os.environ.get("BRAIN_MEMORY_CLEANUP_FILE", "/data/memory-cleanup.json")

REASONS = ("wrong", "useless", "error", "duplicate", "stale")
REASON_WORDS = {
    "wrong": "Wrong",
    "useless": "No value",
    "error": "An error",
    "duplicate": "Said twice",
    "stale": "Out of date",
}
MAX_DOC_LINES = 400
MAX_FACTS = 300
MAX_ROWS = 80
MAX_WHY = 200
MAX_TEXT = 400
TIMEOUT_S = 480
JOB = "memory_cleanup"
# What a person said, and the rules a press wrote, are never offered.
KEEP_SOURCES = ("correction", "person", "you")
KEEP_PREDICATES = ("exception:", "judgement:")

_HEADING = re.compile(r"^\s*#")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def doc_lines(document: str) -> list[dict]:
    """The document's fact lines, numbered: every non-blank line that is not
    a heading. A heading is the document's structure, not a claim."""
    out = []
    for n, raw in enumerate((document or "").splitlines(), 1):
        line = raw.strip()
        if not line or _HEADING.match(line):
            continue
        text = _BULLET.sub("", line).strip()
        if len(text) < 3:
            continue
        out.append({"id": f"doc:{n}", "text": text[:MAX_TEXT], "line": raw})
        if len(out) >= MAX_DOC_LINES:
            break
    return out


def offerable_fact(row: dict) -> bool:
    if str(row.get("source") or "") in KEEP_SOURCES:
        return False
    predicate = str(row.get("predicate") or "")
    return not any(predicate.startswith(p) for p in KEEP_PREDICATES)


# The sentence a fact that has outlived its version is offered under. Code
# writes it, not the model: the version arithmetic is `facts_store`'s and a
# reason a person can check is the two version numbers.
OUTLIVED_WHY = ("A note about brAIn itself being broken, filed under brAIn "
                "{filed}; brAIn {running} is running now.")


def digest(document: str, facts: list[dict]) -> dict:
    """The lines a review may name.

    A fact about brAIn itself being broken that has outlived the version it
    was filed under (`facts_store.outlived`) is offered even when a person
    wrote it: a correction about brAIn's own code is not a fact about the
    house, and once a newer release runs it is the previous version's bug.
    It carries ``stale`` with the sentence that says so, and `parse` puts it
    on the table whether or not the model names it.
    """
    lines = doc_lines(document)
    rows = []
    for f in facts:
        if not (f.get("id") and f.get("text")):
            continue
        stale = facts_store.outlived(f)
        if not stale and not offerable_fact(f):
            continue
        row = {"id": f"fact:{f.get('id')}",
               "text": str(f.get("text") or "")[:MAX_TEXT],
               "subject": str(f.get("subject") or ""),
               "source": str(f.get("source") or ""),
               "observed": str(f.get("observed") or "")}
        if stale:
            row["stale"] = OUTLIVED_WHY.format(
                filed=str(f.get("version") or "?"),
                running=facts_store.current_version() or "?")[:MAX_WHY]
        rows.append(row)
    rows = rows[-MAX_FACTS:]
    return {"doc": lines, "facts": rows}


SYSTEM = """You review what brAIn has remembered about one home and find the lines that should go.

You are given the lines of the memory document (ids doc:N) and the facts
brAIn has stored (ids fact:...). You have Home Assistant's reading tools:
states, the registries, history, the logbook. Use them to CHECK a line
before you call it wrong — a device that no longer exists, an entity id
that is not in the registry, a room it is not in, a schedule the
automations do not have.

Propose a line for removal only when it is one of these:
- "wrong" — it says something about this house that is not true, and you
  checked (say what you read).
- "useless" — true but worth nothing to any future run: a one-off event, a
  transient state ("the lamp was on at 9pm"), trivia, something any house
  would say.
- "error" — garbled, truncated, a test or diagnostic marker, a note about
  brAIn's own bookkeeping rather than the house, a line that is plainly a
  mistake in the writing.
- "duplicate" — the same fact as another line. Name the line you keep in
  "why" and remove the weaker copy, never both.
- "stale" — true once and replaced since (an old device, a moved schedule).

Rules:
- When in doubt, keep it. A removal nobody can check is worse than a line
  that stays.
- Never propose a line about safety equipment (smoke, CO, leak, gas
  sensors, shutoff valves, alarms) as useless.
- Only use ids exactly as given. Never invent one.
- "why" is one short sentence a person can check.
- An empty list is a fine answer.

Answer with JSON only: {"remove": [{"id": "doc:12", "reason": "wrong", "why": "..."}]}
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "remove": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "reason": {"type": "string", "enum": list(REASONS)},
                    "why": {"type": "string"},
                },
                "required": ["id", "reason", "why"],
            },
        },
    },
    "required": ["remove"],
}


def frame(dig: dict) -> str:
    parts = ["THE MEMORY DOCUMENT:"]
    parts += [f"{r['id']}: {r['text']}" for r in dig.get("doc") or []] or ["(empty)"]
    parts.append("\nTHE STORED FACTS:")
    for r in dig.get("facts") or []:
        meta = ", ".join(x for x in (r.get("subject"), r.get("source"),
                                     r.get("observed")) if x)
        line = f"{r['id']}: {r['text']}" + (f"  [{meta}]" if meta else "")
        if r.get("stale"):
            line += "  [already proposed as stale: " + r["stale"] + "]"
        parts.append(line)
    if not dig.get("facts"):
        parts.append("(none)")
    parts.append("\nReply with the JSON contract and nothing else.")
    return "\n".join(parts)


def parse(answer: dict | None, dig: dict) -> dict:
    """`{rows, dropped}` — only a removal that names an offered line, with a
    reason from the closed set, becomes a row. One row per line."""
    offered = {r["id"]: ("doc", r) for r in dig.get("doc") or []}
    offered.update({r["id"]: ("fact", r) for r in dig.get("facts") or []})
    items = (answer or {}).get("remove") if isinstance(answer, dict) else None
    rows: list[dict] = []
    seen: set[str] = set()
    dropped = 0
    for raw in items if isinstance(items, list) else []:
        if len(rows) >= MAX_ROWS:
            break
        if not isinstance(raw, dict):
            dropped += 1
            continue
        rid = str(raw.get("id") or "").strip()
        reason = str(raw.get("reason") or "").strip()
        why = " ".join(str(raw.get("why") or "").split())[:MAX_WHY]
        if rid not in offered or reason not in REASONS or not why or rid in seen:
            dropped += 1
            continue
        seen.add(rid)
        kind, line = offered[rid]
        rows.append({"id": rid, "kind": kind, "text": line["text"],
                     "reason": reason, "why": why})
    # What has outlived its version is on the table whatever the model
    # said about it: the arithmetic decided, and a review that happened to
    # skip it must not leave a dead bug report being read to every run.
    for line in dig.get("facts") or []:
        if line.get("stale") and line["id"] not in seen \
                and len(rows) < MAX_ROWS:
            seen.add(line["id"])
            rows.append({"id": line["id"], "kind": "fact",
                         "text": line["text"], "reason": "stale",
                         "why": line["stale"]})
    return {"rows": rows, "dropped": dropped}


def load(path: str | None = None) -> dict:
    """`{proposal, unreadable}` — never raises."""
    try:
        with open(path or STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"proposal": None, "unreadable": False}
    except (OSError, ValueError):
        return {"proposal": None, "unreadable": True}
    proposal = data.get("proposal") if isinstance(data, dict) else None
    return {"proposal": proposal if isinstance(proposal, dict) else None,
            "unreadable": False}


def save(parsed: dict, *, run_id: str = "", now: float | None = None,
         path: str | None = None) -> dict:
    proposal = {"at": int(now if now is not None else time.time()),
                "run_id": str(run_id or "")[:64],
                "rows": parsed.get("rows") or [],
                "dropped": int(parsed.get("dropped") or 0)}
    atomic_write.write_json(path or STORE, {"proposal": proposal})
    return proposal


def take(ids, path: str | None = None) -> list[dict]:
    """The ticked rows, removed from the proposal. Returns what was taken.

    Rows not ticked stay to be looked at; a proposal with nothing left is
    cleared, because an empty table is not a proposal.
    """
    wanted = {str(i) for i in ids or ()}
    data = load(path)
    proposal = data.get("proposal") or {}
    rows = proposal.get("rows") or []
    taken = [r for r in rows if r.get("id") in wanted]
    left = [r for r in rows if r.get("id") not in wanted]
    if taken:
        proposal["rows"] = left
        atomic_write.write_json(path or STORE,
                                {"proposal": proposal if left else None})
    return taken


def discard(path: str | None = None) -> None:
    atomic_write.write_json(path or STORE, {"proposal": None})


def forget_line(text: str) -> str:
    """The inbox line that asks the consolidator to strike a document line."""
    return "FORGET: " + " ".join(str(text or "").split())[:MAX_TEXT]


__all__ = [
    "JOB", "KEEP_SOURCES", "MAX_ROWS", "REASONS", "REASON_WORDS", "SCHEMA",
    "SYSTEM", "TIMEOUT_S", "digest", "discard", "doc_lines", "forget_line",
    "frame", "load", "parse", "save", "take",
]
