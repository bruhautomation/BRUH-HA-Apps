"""What each stream reports, as rows the queue can file.

A row is ``{"where", "what", "detail", "body"}`` and optionally a ``key``:
the fingerprint is computed from ``where|what`` unless a key is given,
which is how a ROLLING stream (one issue rewritten each pass) names its
one issue. Everything here is pure over what it is handed, so the panel
decides what to read and a test decides what to hand in.

Nothing here aliases or redacts. That happens once, in `upstream.compose`,
over the whole composed issue, because a redaction applied section by
section is the one that misses the day a section changes.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import reports

from . import STREAMS

# --------------------------------------------------------------- faults

SKIP_WHERE = frozenset({"This list"})


def faults(diagnostics: dict) -> list[dict]:
    rows = []
    for row in reports.faults(diagnostics):
        where, what = str(row.get("where") or ""), str(row.get("what") or "")
        if what and where not in SKIP_WHERE:
            rows.append({"where": where, "what": what,
                         "detail": str(row.get("detail") or "")})
    return rows


# ------------------------------------------------------------- scorecard

def scorecard(score_rows: list[dict], diagnostics: dict, version: str) -> list[dict]:
    """One rolling issue per release: how right each producer was and how
    the runs went. Counts only — nothing in it names the house."""
    journal = (diagnostics or {}).get("journal") or {}
    health = (diagnostics or {}).get("health") or {}
    lines = ["| Producer | Confirmed | Wrong | Share right |", "|---|---|---|---|"]
    rows = sorted(score_rows or [], key=lambda r: -int(r.get("total") or 0))
    for r in rows[:40]:
        total = int(r.get("total") or 0)
        share = f"{100 * int(r.get('confirmed') or 0) // total}%" if total else "—"
        lines.append(f"| `{r.get('source', '?')}` | {r.get('confirmed', 0)} | "
                     f"{r.get('wrong', 0)} | {share} |")
    body = "\n".join([
        f"Release **{version}**. Rewritten on every pass; compare it with the "
        "issue for the release before.",
        "",
        f"* Health: {health.get('state') or '?'}",
        f"* Runs in the last day: {journal.get('runs', '?')} "
        f"(by outcome: {json.dumps(journal.get('by_outcome') or {}, sort_keys=True)})",
        "",
        "### How right each producer was",
        "",
        *lines,
    ])
    return [{"key": f"scorecard|{version}", "where": "Scorecard",
             "what": f"brAIn {version}", "detail": "", "body": body}]


# ---------------------------------------------------------------- wrongs

WRONG_MIN = 3
WRONG_SHARE = 0.5
MAX_REASONS = 6


def wrongs(score_rows: list[dict], settled: list[dict]) -> list[dict]:
    """A producer marked Wrong at least WRONG_MIN times and at least half
    the time is a rule that is wrong about this house — the strongest
    evidence a check's CODE needs changing, and until now it never left
    the house. The reasons people typed come with it."""
    reasons: dict[str, list[str]] = {}
    for e in settled or []:
        if e.get("kind") == "ignored" and e.get("note"):
            reasons.setdefault(str(e.get("source") or ""), []).append(
                str(e["note"])[:200])
    out = []
    for r in score_rows or []:
        wrong, total = int(r.get("wrong") or 0), int(r.get("total") or 0)
        if wrong < WRONG_MIN or not total or wrong / total < WRONG_SHARE:
            continue
        src = str(r.get("source") or "?")
        said = reasons.get(src, [])[-MAX_REASONS:]
        body = "\n".join(["Reasons given:", ""] + [f"> {s}" for s in said]) \
            if said else "No reasons were typed."
        out.append({"where": f"Rule {src}",
                    "what": f"marked Wrong {wrong} of {total} times",
                    "detail": str(r.get("title") or ""), "body": body})
    return out


# ---------------------------------------------------------------- unmet

# How the assistant says it could not do something. Matched on the reply
# that follows a person's message, never on the person's own words.
_CANT_RE = re.compile(
    r"\b(I (?:can(?:no|')t|cannot|am unable to|'m unable to|don'?t have (?:a|any) "
    r"(?:way|tool))|there(?:'s| is) no (?:tool|way) (?:to|for)|not (?:able|possible) to)\b",
    re.IGNORECASE)
UNMET_DAYS = 14
MAX_UNMET = 10


def unmet(transcript_dir: Path, now: float | None = None) -> list[dict]:
    """Things a person asked the chat for that brAIn said it could not do.

    Read from the panel's own chat transcripts (the person's conversations,
    never a machine's), the last UNMET_DAYS of them. The person's words
    are the row; the reply's sentence is the detail. Both are aliased and
    scrubbed on their way out like everything else."""
    now = now or time.time()
    rows: list[dict] = []
    try:
        files = sorted(Path(transcript_dir).glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return rows
    for path in files:
        try:
            if now - path.stat().st_mtime > UNMET_DAYS * 86400:
                continue
            events = json.loads(path.read_text(encoding="utf-8")).get("events") or []
        except (OSError, ValueError, AttributeError):
            continue
        asked = ""
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "user":
                asked = str(ev.get("text") or "").strip()
            elif ev.get("type") == "text" and asked:
                text = str(ev.get("text") or "")
                m = _CANT_RE.search(text)
                if m:
                    sentence = text[max(0, m.start() - 80): m.end() + 160]
                    rows.append({"where": "Chat", "what": asked[:200],
                                 "detail": " ".join(sentence.split())})
                    asked = ""
            if len(rows) >= MAX_UNMET:
                return rows
    return rows


# -------------------------------------------------------------- snapshot

def snapshot(names: dict, diagnostics: dict, version: str) -> list[dict]:
    """The shape of the house, for an audit that cannot visit it: how many
    of each kind of thing, how many rooms, which features are on. Counts
    and flags — no name, id or state leaves in it."""
    domains: dict[str, int] = {}
    areas = set()
    for eid, row in (names or {}).items():
        domains[eid.split(".", 1)[0]] = domains.get(eid.split(".", 1)[0], 0) + 1
        if isinstance(row, dict) and row.get("area"):
            areas.add(row["area"])
    options = (diagnostics or {}).get("options") or {}
    flags = {k: v for k, v in options.items() if isinstance(v, bool)}
    shape = {"version": version, "entities": sum(domains.values()),
             "rooms": len(areas), "domains": dict(sorted(domains.items())),
             "options": flags,
             "settings": (diagnostics or {}).get("settings") or {}}
    body = "```json\n" + json.dumps(shape, indent=1, sort_keys=True,
                                    default=str) + "\n```"
    return [{"key": "snapshot", "where": "House shape",
             "what": "an aliased outline of this house", "detail": "",
             "body": body}]


# --------------------------------------------- the streams Claude runs

ANALYST_SYSTEM = """You are reviewing brAIn, a Home Assistant add-on, from inside one
house that runs it. You are looking for what to improve in brAIn ITSELF —
its code, its checks, its screens, its features — not for problems in
the house. You have read-only Home Assistant tools and brAIn's own
get_findings and get_health tools.

Answer with JSON only: {"rows": [{"title": "...", "what": "...", "why": "..."}]}
with at most %(cap)d rows. "title" is under 80 characters and names the part
of brAIn; "what" is one sentence saying what is wrong or missing; "why" is
up to three sentences of evidence from this house. No row is better than a
vague one. Never include a secret, a code or a person's whereabouts.

Every report this house has already filed is listed under
ALREADY REPORTED. Never file one of those again, in the same words or new ones:
a second issue about a problem already filed costs whoever fixes brAIn
a duplicate to close and adds nothing. A row is only worth filing when
it is a different problem."""

PROMPTS = {
    "gaps": ("Where does brAIn fall short on this house? Read the faults, the "
             "rules marked wrong and the requests it could not answer below, "
             "and look at the house with your tools. Each row is one gap in "
             "brAIn's code or capabilities."),
    "ideas": ("What would make brAIn more useful in THIS house? Ground every "
              "idea in something you can see here. Each row is one feature."),
    "look": ("The owner asked you to look into this, as a developer of brAIn "
             "would: %(topic)s\nInvestigate it with your tools and report what "
             "you find wrong or improvable in brAIn."),
}
MAX_ROWS = 6


# What a Claude stream is shown of what it has already filed. Its own
# budget, so a long fault list can never cut the one block that stops a
# rewording being filed as a new issue.
MAX_REPORTED = 60
REPORTED_CHARS = 6000


def reported_block(listing: list[dict]) -> str:
    """Everything this house has filed or queued, one line each, newest
    first: `upstream.listing()`'s rows. A rolling issue is evidence rather
    than a report, and is left out.

    The Claude streams write free text, and the fingerprint folds digits,
    not wording — so "findings are not merged across sources" and "the same
    problem is filed twice by different cards" were two issues, and on the
    first real house six of them were the same report (the fixer closed
    thirteen duplicates in one run). The run cannot avoid what it is not
    shown."""
    rows = [r for r in listing or [] if isinstance(r, dict)
            and not STREAMS.get(str(r.get("stream")), {}).get("rolling")
            and r.get("what")]
    rows.sort(key=lambda r: -float(r.get("last_seen") or 0))
    lines = []
    for r in rows[:MAX_REPORTED]:
        note = " (the homeowner said never to report this)" \
            if r.get("state") == "discarded" else ""
        lines.append(f"- {str(r.get('where') or '')[:120]}: "
                     f"{str(r.get('what') or '')[:200]}{note}")
    return "\n".join(lines)[:REPORTED_CHARS]


def analyst_prompt(stream: str, context: str, topic: str = "",
                   reported: str = "") -> str:
    head = PROMPTS[stream] % {"topic": topic[:500]} if stream == "look" \
        else PROMPTS[stream]
    tail = (f"\n\nALREADY REPORTED (do not file these again):\n{reported}"
            if reported else "\n\nALREADY REPORTED: nothing yet.")
    return f"{head}\n\nWHAT BRAIN ALREADY KNOWS:\n{context[:12000]}{tail}"


def analyst_system() -> str:
    return ANALYST_SYSTEM % {"cap": MAX_ROWS}


def parse_rows(text: str, stream: str, topic: str = "") -> list[dict]:
    """The reply as rows, or [] for anything unreadable."""
    raw = str(text or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return []
    out = []
    for r in (data.get("rows") if isinstance(data, dict) else None) or []:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "").strip()[:120]
        what = str(r.get("what") or "").strip()[:300]
        if not title or not what:
            continue
        where = {"gaps": "Gap", "ideas": "Idea", "look": "Look"}[stream]
        body = str(r.get("why") or "").strip()[:2000]
        if stream == "look" and topic:
            body = f"Asked: *{topic[:300]}*\n\n{body}"
        out.append({"where": f"{where}: {title}", "what": what,
                    "detail": "", "body": body})
        if len(out) >= MAX_ROWS:
            break
    return out


def context_block(diagnostics: dict, score_rows: list, unmet_rows: list) -> str:
    """What a Claude stream is handed: the fault list, the scorecard, and
    what the chat could not do."""
    parts = ["FAULTS:", reports.faults_text(reports.faults(diagnostics))]
    parts += ["", "SCORECARD (source: confirmed/wrong):"]
    parts += [f"- {r.get('source')}: {r.get('confirmed', 0)}/{r.get('wrong', 0)}"
              for r in (score_rows or [])[:30]]
    if unmet_rows:
        parts += ["", "ASKED FOR AND NOT DONE:"]
        parts += [f"- {r['what']}" for r in unmet_rows[:10]]
    return "\n".join(parts)
