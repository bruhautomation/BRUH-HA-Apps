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
    "design": ("Here is what brAIn showed this household. Judge it as the "
               "person who lives here would, and file the changes that would "
               "make brAIn feel like one calm, coherent assistant.\n\n"
               "%(topic)s"),
    # "What do you want to fix?" — the owner's own words about brAIn, which
    # the run turns into the issue a developer would want. LOOK_SYSTEM says
    # how; this is only the opening.
    "look": ("The owner of this house uses brAIn every day and told you what "
             "they want fixed, in their own words:\n\n%(topic)s\n\n"
             "Work out what is really wrong behind it and file the one issue "
             "that would fix it."),
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
    if stream == "look":
        head = PROMPTS[stream] % {"topic": topic[:500]}
    elif stream == "design":
        head = PROMPTS[stream] % {"topic": topic[:DESIGN_CHARS]}
    else:
        head = PROMPTS[stream]
    tail = (f"\n\nALREADY REPORTED (do not file these again):\n{reported}"
            if reported else "\n\nALREADY REPORTED: nothing yet.")
    return f"{head}\n\nWHAT BRAIN ALREADY KNOWS:\n{context[:12000]}{tail}"


# "What do you want to fix?" is not a search for problems: somebody who
# lives with brAIn has already found one and said it in a sentence. What
# they need from the run is the issue a good product engineer would write
# after hearing it — the real problem rather than the complaint restated,
# what "fixed" looks like, and ONE of them, because a vague complaint
# turned into six speculative rows is the noise the cloud has to close.
LOOK_ROWS = 2
LOOK_SYSTEM = """You are a senior product engineer on brAIn, a Home Assistant add-on
that is meant to be the household's own brain: it watches the house, says
what matters, answers in a chat, and fixes things with permission. The
owner of one house that runs it has just told you, in their own words, what
they want fixed. They are the user; what they feel is the evidence.

Think like a person who uses brAIn every day, not like a code reviewer:
- Find the problem BEHIND the words. "The settings page is too crowded"
  is not an issue; "Settings opens on eight sections of controls most
  people never change, so the three they visit weekly are buried" is.
- Judge it against what brAIn is for: a screen should carry only what a
  decision needs; every control does one job and says what it is; nothing
  is shown twice; no sentence only a developer could understand; no
  number without what it is out of; nothing that sounds busy and tells the
  person nothing. Output that is generic, repetitive, wrong about this
  house or not worth reading is a bug, and saying so is the fix.
- Use your read-only tools where they help (get_health, get_findings and
  Home Assistant's own reads) to ground it in this house. You cannot see
  the panel: when the issue is about a screen, name the pane and what a
  person would see there. The developer looks at it in the house's own
  redacted screenshots and on a test fixture.
- If the words are vague, choose the most likely concrete problem and say
  in "why" what you assumed. Never answer with a question.
- The owner's request IS the issue. Never turn it into a report about a
  tool brAIn lacks, something you could not see or read, or a permission
  it does not have. "Rework the settings page" is a request to redesign
  the settings page, whether or not any tool can show it to you: file the
  redesign, title it after the screen, and let the developer look.

Answer with JSON only:
{"rows": [{"title": "...", "what": "...", "why": "...", "done_when": "...",
           "ui": true}]}
with ONE row, two only when the owner named two genuinely separate
problems. "title" is under 80 characters and names the part of brAIn;
"what" is one sentence stating the real problem; "why" is up to four
sentences: what the owner experiences and the evidence; "done_when" is one
to three sentences a developer could check the fix against; "ui" is true
when the fix is on a screen of the panel. Never include a secret, a code or
a person's whereabouts.

Every report this house has already filed is listed under
ALREADY REPORTED. If the owner's complaint IS one of those, still file it: their
words are new evidence, and saying it again is how they say it was not
fixed. Start "what" with "Still a problem:" in that case."""


# The design review: brAIn reading what it SHOWED this house, as the
# person who has to live with it. Not "is it correct" — faults, wrongs and
# the checks' scorecard answer that — but "is it worth reading, does it
# say one thing once, would a person know what to do". It sees the real
# text: card titles and summaries, the findings as worded, what a look
# concluded. It cannot see pixels; the Screens stream's pictures can.
DESIGN_ROWS = 4
DESIGN_CHARS = 9000
DESIGN_SYSTEM = """You are the design lead for brAIn, a Home Assistant add-on meant to be
the household's own brain: one calm place that understands the house,
says what matters, answers questions and fixes problems. You are reading
exactly what brAIn showed this household recently — its insight cards,
its findings as worded, and the conclusions it drew — the way the person
living here reads them on a phone.

Find what makes brAIn feel chaotic, generic or untrustworthy, and say how
it should be instead. Look for:
- cards or findings that say the same thing twice, or in two places;
- text that is accurate and not worth reading: generic advice, a number
  with nothing to compare it to, a claim that restates its own title;
- sentences only a developer would understand: ids, codes, internal names;
- a person left not knowing what to do, or asked something brAIn could
  have found out itself;
- a missing feeling of one coherent assistant: inconsistent tone, names
  or vocabulary between surfaces.
Every row is a change to brAIn's CODE or prompts that would fix the whole
class, not one card. Ground it in a quote from what you were shown.

Answer with JSON only:
{"rows": [{"title": "...", "what": "...", "why": "...", "done_when": "...",
           "ui": true}]}
with at most %(cap)d rows, the most important first. "title" under 80
characters names the surface; "what" is one sentence; "why" up to four
sentences quoting the evidence; "done_when" says what a developer checks;
"ui" is true when the fix is on a screen. No row beats a vague row. Never
include a secret, a code or a person's whereabouts. Never re-file
anything under ALREADY REPORTED."""


def design_context(insights: list, findings: list) -> str:
    """What the design review is shown: the words brAIn put in front of the
    household, newest first, bounded. Never the chart HTML — a card's
    words are what a person reads, and the HTML is the cloud's to look at."""
    parts = ["INSIGHT CARDS (title — summary):"]
    for ins in (insights or [])[:24]:
        if not isinstance(ins, dict):
            continue
        title = " ".join(str(ins.get("title") or "").split())[:140]
        summary = " ".join(str(ins.get("summary") or "").split())[:400]
        if title or summary:
            parts.append(f"- {title} — {summary}")
    parts += ["", "FINDINGS AS WORDED (text | detail | what to do | what a look said):"]
    for f in (findings or [])[:40]:
        if not isinstance(f, dict):
            continue
        tri = f.get("triage") if isinstance(f.get("triage"), dict) else {}
        bits = [" ".join(str(f.get(k) or "").split())[:300]
                for k in ("text", "detail", "fix")]
        bits.append(" ".join(str(tri.get("reason") or "").split())[:200])
        parts.append("- " + " | ".join(bits))
    return "\n".join(parts)[:DESIGN_CHARS]


def analyst_system(stream: str = "") -> str:
    if stream == "look":
        return LOOK_SYSTEM
    if stream == "design":
        return DESIGN_SYSTEM % {"cap": DESIGN_ROWS}
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
        where = {"gaps": "Gap", "ideas": "Idea", "look": "Fix",
                 "design": "Design"}[stream]
        body = str(r.get("why") or "").strip()[:2000]
        row = {"where": f"{where}: {title}", "what": what, "detail": "",
               "body": body}
        if stream == "design":
            done = str(r.get("done_when") or "").strip()[:800]
            if done:
                row["body"] = "\n\n".join(p for p in (body, f"**Done when:** {done}") if p)
            row["ux"] = r.get("ui") is True
        if stream == "look":
            done = str(r.get("done_when") or "").strip()[:800]
            parts = []
            if topic:
                parts.append("The owner said:\n\n> "
                             + topic[:500].replace("\n", "\n> "))
            if body:
                parts.append(body)
            if done:
                parts.append(f"**Done when:** {done}")
            row["body"] = "\n\n".join(parts)
            row["ux"] = r.get("ui") is True
        out.append(row)
        if len(out) >= (LOOK_ROWS if stream == "look"
                        else DESIGN_ROWS if stream == "design" else MAX_ROWS):
            break
    return out


def verbatim_rows(topic: str) -> list[dict]:
    """The owner's words as the issue, for when the run that was meant to
    write it up failed or wrote nothing. A request somebody typed and sent
    is never dropped on the floor."""
    words = " ".join(str(topic or "").split())[:500]
    if not words:
        return []
    title = words if len(words) <= 70 else words[:69].rsplit(" ", 1)[0] + "…"
    return [{"where": f"Fix: {title}", "what": words, "detail": "",
             "body": "The owner said:\n\n> " + words
                     + "\n\nThe run that should have written this up did not "
                       "answer, so this is their request as they typed it. "
                       "It is the requirement.",
             "ux": False}]


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
