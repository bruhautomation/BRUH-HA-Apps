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


DETAIL_MAX = 5200


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
    # Room for the patch a person chose to send (tell.answer_issue); brAIn's
    # stream reads at most 6000 characters of a row's body.
    row["detail"] = str(detail or row.get("detail") or "")[:DETAIL_MAX]
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if day not in row["days"]:
        row["days"] = (row["days"] + [day])[-60:]
    data[fp] = row
    paths.write_json(_file(), data)


REQUEST_MAX = 4000


def note_request(words: str, ui: bool = False, context: str = "", *,
                 now: float | None = None) -> dict:
    """What somebody typed into Settings → "What do you want to fix in
    Morph?" — brAIn's own "What do you want to fix?" box, for Morph.

    A person who lives with Morph has already found the problem, so the
    words go as they are: quoted, never rewritten, under ``where`` "Morph ·
    Looks" when it is about how Morph looks (the cloud routine opens the
    pane) and "Morph · From you" otherwise. The title is the first sentence
    of what was said. It rides the same ledger and outbox as Morph's own
    faults, so it reaches brAIn's development loop by the one route there
    is — and nothing leaves this box while ``report_code_issues`` is off."""
    words = " ".join(str(words or "").split())[:REQUEST_MAX]
    if len(words) < 4:
        return {"ok": False, "error": "Say what should be fixed."}
    if not settings.load()["report_code_issues"]:
        return {"ok": False, "error": "“Report Morph’s own problems” is off above, so nothing would "
                                      "reach brAIn’s development loop. Turn it on and press Send again."}
    first = re.split(r"(?<=[.!?])\s", words, maxsplit=1)[0]
    what = first if len(first) <= 140 else first[:139].rsplit(" ", 1)[0] + "…"
    area = "Looks" if ui else "From you"
    detail = "\n".join([
        "The owner typed this into Morph's Settings → What do you want to fix in Morph?",
        "",
        *(f"> {line}" for line in words.splitlines() or [words]),
        "",
        "It is about how Morph LOOKS: open the pane it names, on the fixture and in the house's "
        "own screens, before and after the fix." if ui else
        "Find what is behind these words in Morph's code, and fix that.",
        *(["", "Context:", context[:1000]] if context else []),
    ])
    note_fault(area, what, detail, source="person", now=now)
    return {"ok": True, "fp": _fp(f"Morph · {area}"[:80], what)}


def mine(now: float | None = None) -> list[dict]:
    """What somebody sent from Settings and is still in the ledger, newest
    first, with whether brAIn has picked the outbox up since."""
    now = now or time.time()
    ack = paths.read_json(paths.DEVLOOP_ACK, {}) or {}
    picked = float(ack.get("at") or 0)
    out = []
    for fp, r in sorted(_load().items(), key=lambda kv: -float(kv[1].get("last") or 0)):
        if r.get("source") != "person" or r.get("where") not in ("Morph · Looks", "Morph · From you"):
            continue
        if now - float(r.get("last") or 0) > KEEP_S:
            continue
        out.append({"fp": fp, "what": r.get("what"), "ui": r.get("where") == "Morph · Looks",
                    "at": r.get("last"), "picked": picked > float(r.get("last") or 0)})
    return out[:20]


def withdraw(fp: str) -> dict:
    """Take back something sent from Settings before brAIn files it. Only a
    person's own report: a fault Morph noted is not theirs to drop."""
    data = _load()
    row = data.get(str(fp or ""))
    if not row or row.get("source") != "person":
        return {"ok": False, "error": "There is nothing to take back."}
    del data[fp]
    paths.write_json(_file(), data)
    return {"ok": True}


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


# Where the developer who picks the issue up starts. It named
# `morph/AGENTS.md`, which does not exist in the repository: the AGENTS.md
# Morph ships is the guide brAIn reads on a house, under `defaults/`.
FIX_WHERE = ("Fix it in the repository's `morph/` add-on. How Morph is built: "
             "CLAUDE.md's \"Morph specifics\" and docs/design/morph-ui.md; what "
             "brAIn is told on a house: morph/defaults/AGENTS.md. Check a change "
             "with tests/manual/measure-morph.mjs (the fake house is "
             "tests/manual/morph-fixture.mjs).")


def rows(now: float | None = None) -> list[dict]:
    now = now or time.time()
    out = []
    for fp, r in sorted(_load().items(), key=lambda kv: -float(kv[1].get("last") or 0)):
        if now - float(r.get("last") or 0) > KEEP_S:
            continue
        detail = (r.get("detail") or "(none)")[:DETAIL_MAX]
        if r.get("source") == "person" and r.get("where") in ("Morph · Looks", "Morph · From you"):
            # Somebody's own words: quoted as they are, not dressed as a
            # count of something Morph noticed.
            out.append({"where": r["where"], "what": r["what"], "detail": detail[:400],
                        "body": detail + "\n\n" + FIX_WHERE,
                        "impact": {"times": r["count"], "days": len(r.get("days") or [])}})
            if len(out) >= MAX_ROWS:
                break
            continue
        # A detail that carries its own fenced patch is markdown already; a
        # second fence around it would print the patch as text.
        fenced = ["```", detail, "```"] if "```" not in detail else [detail]
        body = "\n".join([
            f"Morph reported this {r['count']} time{'s' if r['count'] != 1 else ''} "
            f"over {len(r.get('days') or [])} day(s).",
            "",
            "Detail:",
            "",
            *fenced,
            "",
            FIX_WHERE,
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
            "mine": mine(),
            "picked_up_at": ack.get("at"), "filed": ack.get("filed"),
            "brain_loop_on": ack.get("loop_on")}
