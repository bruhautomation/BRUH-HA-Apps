"""Loop two: Morph's own problems, handed to brAIn's development loop.

Some of what goes wrong cannot be fixed by changing this house's dashboard:
a card type that throws when it draws, a layout that lets two sections
overlap, a request brAIn could not carry out because Morph has no way to
express it. Those need a change to MORPH's code, in this repository — and
brAIn already has the whole machinery for that: an opt-in loop that files
reports in the owner's private repository, aliased and redacted, one issue
per fingerprint, and a cloud routine (`.claude/skills/fix-from-house`) that
fixes them and closes them.

So Morph does not grow a second copy of any of it. It keeps a small ledger
of its own faults here and publishes it as rows in the shape brAIn's
streams use (``{where, what, detail, body, impact}``) to
``/config/.morph/devloop/outbox.json``; brAIn's ``morph`` stream reads that
file on its own schedule and does everything else — the token, the review
queue, the daily cap, the verdicts. Every row's ``where`` begins "Morph",
which is how the cloud routine knows the fix belongs under ``morph/``.

Nothing leaves this box through Morph. With ``report_code_issues`` off the
outbox is written EMPTY, so turning it off stops the next pass rather than
leaving last week's rows to be filed.
"""
from __future__ import annotations

import hashlib
import re
import time

import paths
import settings

KEEP_S = 14 * 86400
MAX_ROWS = 40
_DIGITS = re.compile(r"\d+")


def _file():
    return paths.DATA / "faults.json"


def _fp(where: str, what: str) -> str:
    return hashlib.sha1(_DIGITS.sub("#", f"{where}|{what}".lower()).encode()).hexdigest()[:16]


def _load() -> dict:
    data = paths.read_json(_file(), {}) or {}
    return data if isinstance(data, dict) else {}


def note_fault(area: str, what: str, detail: str = "", *, source: str = "morph",
               now: float | None = None) -> None:
    now = now or time.time()
    where = f"Morph · {area}"[:80]
    what = str(what or "").strip()[:160]
    if not what:
        return
    data = _load()
    fp = _fp(where, what)
    row = data.get(fp) or {"where": where, "what": what, "first": now, "count": 0,
                           "days": [], "source": source}
    row["count"] = int(row.get("count") or 0) + 1
    row["last"] = now
    row["detail"] = str(detail or row.get("detail") or "")[:2000]
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if day not in row["days"]:
        row["days"] = (row["days"] + [day])[-60:]
    data[fp] = row
    paths.write_json(_file(), data)


def ingest_errors() -> int:
    """Fold what the panel reported (``errors.jsonl``, appended by the
    integration) into the ledger, then empty the file."""
    rows = paths.read_jsonl(paths.ERRORS, limit=2000)
    for r in rows:
        kind = str(r.get("kind") or "panel")
        area = {"card": "Cards", "layout": "Layout", "panel": "Panel",
                "history": "History"}.get(kind, "Panel")
        what = str(r.get("message") or "").strip()
        if kind == "card" and r.get("card_type"):
            what = f"A {r['card_type']} card failed to draw: {what}"
        note_fault(area, what, str(r.get("detail") or ""), now=float(r.get("ts") or time.time()))
    if rows:
        try:
            paths.write_text(paths.ERRORS, "")
        except OSError:
            pass  # the rows are in the ledger; a second fold of them only re-counts
    return len(rows)


def rows(now: float | None = None) -> list[dict]:
    now = now or time.time()
    out = []
    for fp, r in sorted(_load().items(), key=lambda kv: -float(kv[1].get("last") or 0)):
        if now - float(r.get("last") or 0) > KEEP_S:
            continue
        body = "\n".join([
            f"Morph reported this {r['count']} time{'s' if r['count'] != 1 else ''} "
            f"over {len(r.get('days') or [])} day(s).",
            "",
            "Detail:",
            "",
            "```",
            (r.get("detail") or "(none)")[:1800],
            "```",
            "",
            "Fix it in the repository's `morph/` add-on (see morph/AGENTS.md for how Morph is built).",
        ])
        out.append({"where": r["where"], "what": r["what"], "detail": r.get("detail", "")[:400],
                    "body": body, "impact": {"times": r["count"], "days": len(r.get("days") or [])}})
        if len(out) >= MAX_ROWS:
            break
    return out


def publish(version: str = "", now: float | None = None) -> dict:
    on = settings.load()["report_code_issues"]
    payload = {"version": version, "at": time.time(), "enabled": on,
               "rows": rows(now) if on else []}
    paths.write_json(paths.DEVLOOP_OUTBOX, payload)
    return payload


def status() -> dict:
    ack = paths.read_json(paths.DEVLOOP_ACK, {}) or {}
    outbox = paths.read_json(paths.DEVLOOP_OUTBOX, {}) or {}
    return {"enabled": settings.load()["report_code_issues"],
            "waiting": len(outbox.get("rows") or []),
            "picked_up_at": ack.get("at"), "filed": ack.get("filed"),
            "brain_loop_on": ack.get("loop_on")}
