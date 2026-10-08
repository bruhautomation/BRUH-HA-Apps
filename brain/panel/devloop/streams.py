"""What each stream reports, as rows the queue can file.

A row is ``{"where", "what", "detail", "body"}`` and optionally a ``key``:
the fingerprint is computed from ``where|what`` unless a key is given,
which is how a ROLLING stream (one issue rewritten each pass) names its
one issue, and how an unmet capability is one report however it was
worded. A row may also carry ``impact`` — counts only (how often, over
how many days, what the house did) — which `upstream` renders and ranks by. Everything here is pure over what it is handed, so the panel
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
                    "detail": str(r.get("title") or ""), "body": body,
                    "impact": {"wrong": wrong, "endings": total,
                               "confirmed": int(r.get("confirmed") or 0)}})
    return out


# ---------------------------------------------------------------- unmet

# How the assistant says it could not do something. Matched on the reply
# that follows a person's message, never on the person's own words.
_CANT_RE = re.compile(
    r"\b(I (?:can(?:no|')t|cannot|am unable to|'m unable to|don'?t have (?:a|any) "
    r"(?:way|tool))|there(?:'s| is) no (?:tool|way) (?:to|for)|not (?:able|possible) to)\b",
    re.IGNORECASE)
# Where a refusal's sentence ends.
_SENTENCE_END_RE = re.compile(r"[.!?\n]")
# One spelling for the same refusal, so "I can't" and "I cannot" are one
# capability. A short fixed table, applied in order, never a fuzzy match.
_SAME_WORDS = (
    (re.compile(r"\bcan ?not\b|\bcan'?t\b"), "cannot"),
    (re.compile(r"\b(?:am|'m) unable to\b"), "cannot"),
    (re.compile(r"\bthere'?s\b"), "there is"),
    (re.compile(r"\bdon'?t\b"), "do not"),
)
UNMET_DAYS = 14
MAX_UNMET = 10
# A capability is a pattern once brAIn has said it could not do it in this
# many separate conversations. One conversation asking twice is one need.
UNMET_MIN_CONVERSATIONS = 2


def capability(text: str, match: re.Match) -> str:
    """The sentence brAIn said it could not do something in, from the
    refusal on — "Sorry," and whatever led up to it are not the capability."""
    rest = text[match.start():]
    end = _SENTENCE_END_RE.search(rest)
    return " ".join((rest[:end.start()] if end else rest).split())[:200]


def capability_key(sentence: str) -> str:
    """The capability, normalised: case, apostrophes, punctuation and the
    refusal's own wording folded, so the same thing said twice is one key."""
    text = str(sentence or "").lower().replace("’", "'")
    for pattern, word in _SAME_WORDS:
        text = pattern.sub(word, text)
    text = re.sub(r"\d+", "#", text)
    return " ".join(re.sub(r"[^a-z# ]+", " ", text).split())[:160]


def unmet(transcript_dir: Path, now: float | None = None) -> list[dict]:
    """What brAIn told somebody in the chat it could not do, as
    capabilities rather than conversations.

    Read from the panel's own chat transcripts (the person's conversations,
    never a machine's), the last UNMET_DAYS of them. The ROW is the
    sentence brAIn answered with, keyed on its normalised form: what the
    person typed is not read into it, so it never leaves. A capability is
    filed once it has come up in UNMET_MIN_CONVERSATIONS conversations,
    with how many times, in how many conversations, over how many days."""
    now = now or time.time()
    seen: dict[str, dict] = {}
    try:
        files = sorted(Path(transcript_dir).glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    for path in files:
        try:
            mtime = path.stat().st_mtime
            if now - mtime > UNMET_DAYS * 86400:
                continue
            events = json.loads(path.read_text(encoding="utf-8")).get("events") or []
        except (OSError, ValueError, AttributeError):
            continue
        asked = False
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "user":
                asked = True
            elif ev.get("type") == "text" and asked:
                text = str(ev.get("text") or "")
                m = _CANT_RE.search(text)
                if not m:
                    continue
                asked = False
                sentence = capability(text, m)
                key = capability_key(sentence)
                if not key:
                    continue
                when = ev.get("ts") if isinstance(ev.get("ts"), (int, float)) \
                    and not isinstance(ev.get("ts"), bool) else mtime
                row = seen.setdefault(key, {"sentence": sentence, "count": 0,
                                            "conversations": set(),
                                            "days": set(), "last": 0.0})
                row["count"] += 1
                row["conversations"].add(path.name)
                row["days"].add(time.strftime("%Y-%m-%d", time.localtime(when)))
                if when >= row["last"]:
                    row["last"], row["sentence"] = float(when), sentence
    rows = []
    for key, row in seen.items():
        convs = len(row["conversations"])
        if convs < UNMET_MIN_CONVERSATIONS:
            continue
        last = time.strftime("%Y-%m-%d", time.localtime(row["last"]))
        rows.append({
            "key": key, "where": "Chat", "what": row["sentence"],
            "detail": (f"Said {row['count']} times in {convs} conversations "
                       f"over {len(row['days'])} days; last on {last}"),
            "impact": {"count": row["count"], "conversations": convs,
                       "days": len(row["days"])},
            "_last": row["last"]})
    rows.sort(key=lambda r: (-r["impact"]["count"], -r["_last"], r["key"]))
    for r in rows:
        r.pop("_last")
    return rows[:MAX_UNMET]


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
vague one. Never include a secret, a code or a person's whereabouts."""

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


def analyst_prompt(stream: str, context: str, topic: str = "") -> str:
    head = PROMPTS[stream] % {"topic": topic[:500]} if stream == "look" \
        else PROMPTS[stream]
    return f"{head}\n\nWHAT BRAIN ALREADY KNOWS:\n{context[:12000]}"


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
        parts += ["", "WHAT BRAIN SAID IT COULD NOT DO, IN MORE THAN ONE CHAT:"]
        parts += [f"- {r['what']}" for r in unmet_rows[:10]]
    return "\n".join(parts)
