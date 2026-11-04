"""Memory clean-up — what brAIn knows that is wrong, useless or an error.

Memory only ever grows. The consolidator merges what it is handed, the facts
store keeps every line that passes through the inbox, and nothing ever
reads the whole of either and asks whether a line still deserves its place:
a device that was replaced, a guess that was wrong, a one-off evening filed
as a habit, a line about brAIn's own bookkeeping, the same fact three ways.
Every run is handed those lines as true.

One run reads both — the document's lines and the facts store's rows —
with Home Assistant's reading tools, and names what to remove, each with a
reason. Since the owner took the person out of the loop (plan section 0,
`docs/design/self-learning-plan-2026-11.md`), a removal whose reason is
`wrong`, `duplicate` or `stale` is APPLIED at once (`auto_apply`), as one
checked, undoable memory version; `useless` and `error` stay on the list
for a press. Four rules hold what comes back to the same standard as every
other proposal:

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
    `KEEP_SOURCES` reason, one module over. The document's own lines a
    person gave (`memory_history.person_keys`: the provenance ledger, and
    any line typed into memory.md by hand) are left out the same way.
  * **The document still has one writer.** An applied document line goes
    through the consolidator's `--remove` (deterministic, under its lock,
    checked, kept as a version that `brain memory undo` reverses); a line
    ticked by a person is a `FORGET:` line queued to the memory inbox and a
    consolidation pass, as it does for `brain memory forget`; a removed
    fact is `facts_store.forget_ids`. Nothing here writes `memory.md`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time

import atomic_write
import facts_store
import memory_history
import prompt_kit

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


def person_lines(document: str) -> set[str]:
    """The document's lines a person gave, by `memory_history.norm` key.
    Read-only, and empty when the provenance ledger cannot be read."""
    try:
        return memory_history.person_keys(document or "")
    except (OSError, ValueError):
        return set()


def doc_lines(document: str, protected=None) -> list[dict]:
    """The document's fact lines, numbered: every non-blank line that is not
    a heading, and not a line a person gave (``protected``, by
    `memory_history.norm` key). A heading is the document's structure, not
    a claim; a person's line is not the review's to offer."""
    out = []
    protected = protected or set()
    for n, raw in enumerate((document or "").splitlines(), 1):
        line = raw.strip()
        if not line or _HEADING.match(line):
            continue
        if memory_history.norm(raw) in protected:
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
    lines = doc_lines(document, person_lines(document))
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


# Person-facing: every `why` is a row somebody ticks or leaves. A schema
# run with reading tools; SCHEMA holds the shape. The memory lines are
# text other runs and people wrote, so they are fenced like any other.
SYSTEM = prompt_kit.assemble(
    "You review what brAIn has remembered about one home and find the "
    "lines that should go. A line you call wrong, duplicate or stale is "
    "removed at once (it can be undone); useless and error lines wait for "
    "a person.",
    inputs=(
        "You are given the lines of the memory document (ids doc:N) and the "
        "facts brAIn has stored (ids fact:...)."),
    tools=(
        "You have Home Assistant's reading tools: states, the registries, "
        "history, the logbook. CHECK a line before you call it wrong — a "
        "device that no longer exists, an entity id not in the registry, a "
        "room it is not in, a schedule the automations do not have."),
    good=(
        "Proposes a line only when it is one of these, with a `why` a "
        "person can check. wrong — untrue of this house, and you checked "
        "(say what you read). useless — true but worth nothing to any "
        "future run: a one-off event, a transient state, trivia, something "
        "any house would say. error — garbled, truncated, a test or "
        "diagnostic marker, a note about brAIn's own bookkeeping. "
        "duplicate — the same fact as another line; name the one you keep "
        "and remove the weaker copy, never both. stale — true once and "
        "replaced since (an old device, a moved schedule)."),
    example=(
        "doc:12 \"The lounge lamp was on at 21:00 on Tuesday\" → useless, "
        "why \"One evening's state, not a fact about the house.\""),
    rules="""\
- When in doubt, keep it. A removal nobody can check is worse than a line
  that stays.
- Never propose a line about safety equipment (smoke, CO, leak, gas
  sensors, shutoff valves, alarms) as useless.
- Only use ids exactly as given. Never invent one.
- An empty list is a fine answer.""",
)

SCHEMA = {
    "type": "object",
    "properties": {
        "remove": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description":
                           "doc:N or fact:..., exactly as given."},
                    "reason": {"type": "string", "enum": list(REASONS)},
                    "why": {"type": "string", "description":
                            "One short sentence a person can check."},
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
    if parsed.get("applied"):
        proposal["applied"] = list(parsed["applied"])[:MAX_ROWS]
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


# ---------------------------------------------------------------------------
# Applied without a press (plan section 0)
# ---------------------------------------------------------------------------

# The reasons a removal is applied on: each is a claim the review checked
# against the house (wrong), against the document (duplicate) or against
# time (stale). `useless` and `error` are judgement calls about value and
# stay on the list for a press.
AUTO_REASONS = ("wrong", "duplicate", "stale")
# A duplicate is applied only while a copy stays: another line, not being
# removed, carrying this share of its words. "Name the one you keep, never
# both" is a sentence in the prompt; this is the same rule in code.
DUPLICATE_SHARE = 0.6
REMOVE_TIMEOUT_S = 120
CONSOLIDATE_SCRIPT = os.environ.get(
    "BRAIN_CONSOLIDATE_SCRIPT", "/opt/scripts/brain-memory-consolidate.sh")


def _keeps_a_copy(row: dict, dig: dict, going: set[str]) -> bool:
    mine = memory_history.tokens(row.get("text"))
    pool = list(dig.get("doc") or []) + list(dig.get("facts") or [])
    for other in pool:
        if other["id"] == row["id"] or other["id"] in going:
            continue
        theirs = memory_history.tokens(other.get("text"))
        if memory_history.share(mine, theirs) >= DUPLICATE_SHARE:
            return True
    return False


def auto_rows(parsed: dict, dig: dict) -> list[dict]:
    """The rows to apply without a press: an auto reason, and for a
    duplicate a copy that stays. Two rows calling each other duplicates
    keep the first-offered line."""
    chosen: list[dict] = []
    going: set[str] = set()
    for row in parsed.get("rows") or []:
        if row.get("reason") not in AUTO_REASONS:
            continue
        if row.get("reason") == "duplicate" and \
                not _keeps_a_copy(row, dig, going | {row["id"]}):
            continue
        chosen.append(row)
        going.add(row["id"])
    return chosen


def _line_number(row_id) -> int | None:
    """`doc:7` → 7: which copy of a repeated line a removal means."""
    try:
        return int(str(row_id).split(":", 1)[1])
    except (IndexError, ValueError):
        return None


def remove_document_lines(rows: list[dict], *, script: str | None = None,
                          timeout: float = REMOVE_TIMEOUT_S) -> set[str]:
    """Take document lines out through the consolidator's `--remove`.

    Returns the ids of the rows removed. The consolidator runs it under its
    own lock (a short wait: a pass in flight leaves the rows on the list
    for the next review rather than holding the panel), refuses a person's
    line whatever asked, and keeps the result as a version.
    """
    script = script or CONSOLIDATE_SCRIPT
    if not rows or not os.path.isfile(script):
        return set()
    payload = [{"text": r.get("text") or "",
                "line": _line_number(r.get("id")),
                "why": f"{r.get('reason')}: {r.get('why') or ''}"[:200]}
               for r in rows]
    fd, path = tempfile.mkstemp(prefix="brain-cleanup-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        try:
            proc = subprocess.run(
                ["bash", script, "--remove", path], capture_output=True,
                text=True, timeout=timeout,
                env={**os.environ, "BRAIN_MEMORY_LOCK_WAIT": "30"})
        except (OSError, subprocess.SubprocessError):
            return set()
    finally:
        try:
            os.unlink(path)
        except OSError:
            # A temp file already gone is the cleanup done; nothing to say.
            pass
    removed: list[str] = []
    for line in reversed((proc.stdout or "").splitlines()):
        try:
            out = json.loads(line)
        except ValueError:
            continue
        if isinstance(out, dict):
            removed = [memory_history.norm(x) for x in out.get("removed") or []]
            break
    done = set()
    for r in rows:
        body = memory_history.norm(r.get("text"))
        for k in removed:
            if body and (k == body or k.endswith(body) or
                         (len(body) >= 40 and body[:40] in k)):
                done.add(r["id"])
                removed.remove(k)       # one removed line answers one row
                break
    return done


def auto_apply(parsed: dict, dig: dict, *, script: str | None = None) -> list[dict]:
    """Apply what may be applied without a press, and take it off the list.

    Facts leave the store (`facts_store.forget_ids`); document lines leave
    memory.md as one memory version. What could not be applied — the
    consolidator busy or missing, a line it refused — stays on the list.
    Returns the applied rows; ``parsed`` is changed in place (its ``rows``
    lose them, its ``applied`` gains them).
    """
    chosen = auto_rows(parsed, dig)
    if not chosen:
        return []
    done: set[str] = set()
    fact_rows = [r for r in chosen if r.get("kind") == "fact"]
    if fact_rows:
        ids = [r["id"].split(":", 1)[1] for r in fact_rows]
        try:
            facts_store.forget_ids(ids)
            done |= {r["id"] for r in fact_rows}
        except OSError:
            # An unwritable store leaves the rows on the list for a press,
            # which is the answer a failed removal should have.
            pass
    doc_rows = [r for r in chosen if r.get("kind") == "doc"]
    done |= remove_document_lines(doc_rows, script=script)
    applied = [{**r, "applied": True} for r in chosen if r["id"] in done]
    parsed["rows"] = [r for r in parsed.get("rows") or [] if r["id"] not in done]
    parsed["applied"] = list(parsed.get("applied") or []) + applied
    return applied


def note(left: int, applied) -> str:
    """The review's one line: what it took out by itself, what it left."""
    n = len(applied or [])
    if n and left:
        return f"Removed {n} line(s) it was sure of; {left} to review"
    if n:
        return f"Removed {n} line(s) it was sure of"
    return (f"{left} line(s) to review" if left else
            "Nothing in memory looks wrong or useless.")


def forget_line(text: str) -> str:
    """The inbox line that asks the consolidator to strike a document line."""
    return "FORGET: " + " ".join(str(text or "").split())[:MAX_TEXT]


__all__ = [
    "AUTO_REASONS", "JOB", "KEEP_SOURCES", "MAX_ROWS", "REASONS",
    "REASON_WORDS", "SCHEMA", "SYSTEM", "TIMEOUT_S", "auto_apply",
    "auto_rows", "digest", "discard", "doc_lines", "forget_line", "frame",
    "load", "note", "parse", "person_lines", "remove_document_lines",
    "save", "take",
]
