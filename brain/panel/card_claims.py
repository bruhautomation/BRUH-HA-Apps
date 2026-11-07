"""What a card claims, read against itself before it is stored.

`card_verdict` reads a card's judgement against its evidence; this reads
its CLAIMS. Three rules, each pure over the parsed reply so `review` and
`_generate` ask them and the tests drive them directly:

* **A blind spot is never the headline** (`blind_lead`). A house's Reports
  carried whole cards that said they had nothing to say: "no cooling in 10
  days, nothing to compare", "both doors stayed shut", "door history after
  1:00 AM is missing". A card whose main claim — its title — is missing
  data, no comparison or no event, with nothing to act on and nothing
  compared, is not news: a scheduled one keeps the last card
  (`BLIND_WHY`), and a first or pressed one is stored `blind` and folded
  into the quiet line. An ASKED card is the answer to a question and is
  never folded: "it stayed closed" is what somebody wanted to know.
* **A data gap is at most one short line** (`trim_gaps`): the first gap
  sentence of the summary under `GAP_LINE_MAX` stays, every other goes,
  and a tile whose value is a gap ("no data", "n/a") is not a tile.
* **A card and a finding about one thing are one item**
  (`finding_twin`): a card every entity of which is an open finding's
  entity, or on that entity's device, is drawn as that finding.

Nothing here invents a word: a rewrite only removes a sentence or a tile.
"""
from __future__ import annotations

import re

BLIND_WHY = ("the new card only said what brAIn could not see or that "
             "nothing happened, so the last card was kept")
# A gap line short enough to read as an aside rather than a paragraph.
GAP_LINE_MAX = 110

# A sentence saying brAIn lacks the data, or could not compare.
_GAP = re.compile(
    r"\b(?:can(?:no|['’])?t|cannot|could(?:n['’]t| not)|unable to)\s+"
    r"(?:see|tell|read|compare|confirm|know|say|check)\b"
    r"|\bnothing to compare\b"
    r"|\bno (?:earlier |previous |prior |older )?(?:comparison|baseline|"
    r"history|data|records?|recording|readings?|samples?)\b"
    r"|\b(?:history|data|records?|recording|readings?|log)\b[^.;]{0,40}?"
    r"\b(?:is|are|was|were|goes|go)\s+(?:missing|unavailable|incomplete|"
    r"gone|blank|empty)\b"
    r"|\bmissing (?:data|history|readings?|records?)\b"
    r"|\bgaps? in (?:the |its )?(?:data|history|record|readings)\b"
    r"|\b(?:not enough|too (?:little|few)) (?:data|history|readings|"
    r"samples|days)\b"
    r"|\bblind spot\b|\b(?:not|isn['’]t|wasn['’]t) recorded\b", re.I)

# A headline about nothing having happened.
_NON_EVENT = re.compile(
    r"\bno (?:cooling|heating|runs?|cycles?|openings?|activity|events?|use|"
    r"usage|motion|change|alerts?|visits?|deliveries)\b"
    r"|\bnothing (?:happened|ran|moved|changed|opened|to report)\b"
    r"|\bstayed (?:shut|closed|off|locked|dry|quiet|idle|dark|empty)\b"
    r"|\b(?:never|didn['’]t|did not|hasn['’]t|has not|haven['’]t|have not|"
    r"wasn['’]t|was not) (?:\w+ )?(?:open(?:ed)?|run|ran|cycled?|come on|"
    r"came on|fired|triggered|used|moved)\b"
    r"|\b(?:zero|0) (?:runs?|cycles?|openings?|events?|times)\b", re.I)

# A headline that compares or moves is news, whatever else it says.
_NEWS = re.compile(
    r"→|->|\bvs\.?\b|\bversus\b|\busual(?:ly)?\b|\bmore than\b|\bless than\b|"
    r"\bfewer\b|\bhigher\b|\blower\b|\brose\b|\bfell\b|\brising\b|"
    r"\bfalling\b|\bdoubled\b|\btwice\b|%", re.I)

# A tile whose value says there is no value.
_GAP_VALUE = re.compile(
    r"\s*(?:no data|no reading|no readings|missing|n/?a|unknown|"
    r"not recorded|none recorded|can['’]?t see|unavailable|[—–-]+|\?)\s*",
    re.I)

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[A-Z0-9“\"'])")

_ATTENTION = ("warning", "serious", "critical")


def _claim(title: str) -> str:
    """The title's claim: what follows "Subject:", else the whole title."""
    subject, sep, rest = str(title or "").partition(":")
    return rest.strip() if sep and rest.strip() else str(title or "")


def is_gap(sentence: str) -> bool:
    """Whether a sentence is about data brAIn lacks."""
    return bool(_GAP.search(str(sentence or "")))


def _acts(obj: dict) -> bool:
    obj = obj or {}
    if obj.get("findings") or obj.get("opportunities"):
        return True
    return any(str(h.get("status") or "") in _ATTENTION
               for h in obj.get("highlights") or [] if isinstance(h, dict))


def blind_lead(obj: dict, verdict: str = "") -> str:
    """Why the card's main claim is not news — "a data gap", "no
    comparison" or "nothing happened" — or "" when it is."""
    obj = obj or {}
    if verdict in ("worth a look", "needs action") or _acts(obj):
        return ""
    claim = _claim(str(obj.get("title") or ""))
    if not claim.strip() or _NEWS.search(claim):
        return ""
    if re.search(r"\bnothing to compare\b|\bno comparison\b", claim, re.I):
        return "no comparison"
    if _GAP.search(claim):
        return "a data gap"
    if _NON_EVENT.search(claim):
        return "nothing happened"
    return ""


def trim_gaps(out: dict, changed: list[str]) -> None:
    """At most one short gap line in the summary, and no gap tiles."""
    summary = str(out.get("summary") or "")
    parts = [p for p in _SENTENCE_END.split(summary.strip()) if p]
    kept, gaps = [], 0
    for part in parts:
        if is_gap(part):
            if gaps or len(part) > GAP_LINE_MAX:
                continue
            gaps += 1
        kept.append(part)
    if kept and len(kept) != len(parts):
        out["summary"] = " ".join(kept)
        changed.append("a data gap said more than once")
    tiles = out.get("highlights")
    if isinstance(tiles, list):
        real = [h for h in tiles if not (isinstance(h, dict) and _GAP_VALUE
                                        .fullmatch(str(h.get("value") or "")))]
        if len(real) != len(tiles):
            out["highlights"] = real
            changed.append("a tile with no value")


def finding_twin(card_entities: set, rows, device_of=None) -> dict | None:
    """The open finding a card is wholly about: every entity the card names
    is that row's entity (or one in its evidence), or on its device."""
    ents = {str(e) for e in card_entities or () if e}
    if not ents:
        return None
    device_of = device_of or (lambda _e: None)
    for row in rows or ():
        if not isinstance(row, dict) or not row.get("entity_id"):
            continue
        theirs = {str(row["entity_id"])}
        for ev in row.get("evidence") or []:
            if isinstance(ev, dict) and ev.get("entity"):
                theirs.add(str(ev["entity"]))
        theirs |= {str(e) for e in row.get("about") or [] if e}
        devices = {device_of(e) for e in theirs} - {None, ""}
        if all(e in theirs or (device_of(e) or None) in devices for e in ents):
            return row
    return None


# ---------------------------------------------------------------------------
# A title's figures, stood behind by its body
# ---------------------------------------------------------------------------
#
# "0 kWh over the last 8 days" over a body that said "all 11 days", "no
# cooling at 73 °F" over one whose afternoon "passed 65 °F", and "flipped
# from 43 to clear" with nothing saying what 43 was. Every figure in a
# title has to be in the summary or a tile with the same value and unit;
# one that is not, or a bare number, is taken out of the title.

# A measurement's unit, as written → one spelling. A figure in one of these
# must be said in the same unit; a counted noun ("14 openings") must only be
# said with the same value.
_UNITS = (
    (r"°\s?f\b|℉|fahrenheit", "°F"), (r"°\s?c\b|℃|celsius", "°C"),
    (r"degrees?|°", "°"), (r"kwh\b", "kWh"), (r"wh\b", "Wh"),
    (r"kw\b", "kW"), (r"w\b|watts?\b", "W"), (r"%|percent\b", "%"),
    (r"psi\b", "psi"), (r"bar\b", "bar"), (r"gal(?:lons?)?\b|gal\b", "gal"),
    (r"(?:litres?|liters?|l)\b", "L"), (r"mm\b", "mm"),
    (r"(?:inch(?:es)?|in)\b(?=\s*(?:of|$|[,.;]))", "in"),
    (r"mph\b", "mph"), (r"km/h\b", "km/h"),
    (r"(?:h|hrs?|hours?)\b", "h"), (r"(?:min(?:ute)?s?)\b", "min"),
    (r"(?:s|secs?|seconds?)\b", "s"), (r"days?\b", "day"),
    (r"weeks?\b", "week"), (r"months?\b", "month"), (r"ppm\b", "ppm"),
    (r"(?:lux|lx)\b", "lux"), (r"db\b", "dB"), (r"v\b|volts?\b", "V"),
    (r"(?:a|amps?)\b(?!\s+\w)", "A"), (r"(?:am|pm|a\.m\.|p\.m\.)", "clock"),
    (r"(?:times|x|×)\b", "times"),
)
_UNIT_RE = re.compile(r"\s?(?:" + "|".join(f"({p})" for p, _ in _UNITS) + ")",
                      re.I)
_MONTH = re.compile(r"\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                    r"[a-z]*\b", re.I)
_WEEKDAY = re.compile(r"\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+$", re.I)
_NUMBER = re.compile(r"(?<![\w.:/])(-?\d[\d,]*(?:\.\d+)?)(?![\d:])")
_CLOCK_RE = re.compile(r"(?<![\w.])(\d{1,2}):(\d{2})(?:\s?(am|pm))?\b", re.I)
_DURATION_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s?h(?:ours?|rs?)?\s+(\d+)\s?min\b", re.I)
# Words that frame a figure without saying what it is.
_STOP = frozenset((
    "a an the of to in on at for from by over since until till after before "
    "and or but with within during across per vs versus about around than "
    "this that last past next its it is was are were be been only just "
    "all every each some no not nearly almost roughly up down into out off "
    "then so as").split())
_LEAD = re.compile(
    r"(?:\b(?:over|in|for|at|from|since|of|after|before|by|on|within|"
    r"during|across|around|about|to)\b(?:\s+(?:the|last|past|this|a|an|"
    r"its|first|nearly|about|almost)\b){0,3}\s*)$", re.I)
_RANGE_DAY = re.compile(r"\s?[–-]\s?\d{1,2}(?=\s+(?:jan|feb|mar|apr|may|jun|"
                        r"jul|aug|sep|oct|nov|dec))", re.I)
_PAIR = re.compile(r"^\s*(?:→|->|–|to)\s*$", re.I)
_TOL_INT = 0.5


def _unit_at(text: str, pos: int) -> tuple[str, int]:
    m = _UNIT_RE.match(text, pos)
    if not m:
        return "", pos
    for i, (_p, unit) in enumerate(_UNITS, start=1):
        if m.group(i) is not None:
            return unit, m.end()
    return "", pos


def _word_after(text: str, pos: int) -> tuple[str, int]:
    m = re.match(r"\s+([A-Za-z][A-Za-z'-]*)", text[pos:])
    if not m:
        return "", pos
    return m.group(1), pos + m.end()


def _word_before(text: str, pos: int) -> str:
    m = re.search(r"([A-Za-z][A-Za-z'-]*)\s*$", text[:pos])
    return m.group(1) if m else ""


def _figures_in(text: str) -> list[dict]:
    """Every figure in ``text``: `{value, unit, noun, start, end, bare}`.
    A clock time and an hours-and-minutes duration are one figure each; a
    date's day and a year are not figures."""
    text = str(text or "")
    out: list[dict] = []
    taken: list[tuple[int, int]] = []
    for m in _CLOCK_RE.finditer(text):
        hour = int(m.group(1)) % 12 if m.group(3) else int(m.group(1))
        if m.group(3) and m.group(3).lower() == "pm":
            hour += 12
        out.append({"value": hour * 60.0 + int(m.group(2)), "unit": "clock",
                    "noun": "", "start": m.start(), "end": m.end(),
                    "bare": False})
        taken.append((m.start(), m.end()))
    for m in _DURATION_RE.finditer(text):
        out.append({"value": float(m.group(1)) + int(m.group(2)) / 60.0,
                    "unit": "h", "noun": "", "start": m.start(),
                    "end": m.end(), "bare": False})
        taken.append((m.start(), m.end()))
    for m in _NUMBER.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if (_MONTH.match(text, m.end()) or _WEEKDAY.search(text[:m.start()])
                or _RANGE_DAY.match(text, m.end())
                or re.search(r"\d\s?[–-]\s?$", text[:m.start()])
                and _MONTH.match(text, m.end())):
            continue  # a date's day, or the first day of a range of them
        if re.fullmatch(r"(?:19|20)\d\d", raw):
            continue  # a year
        if re.match(r"(?:st|nd|rd|th)\b", text[m.end():]):
            continue  # an ordinal
        unit, end = _unit_at(text, m.end())
        if unit == "clock":
            hour = int(value) % 12 + (12 if re.match(
                r"\s?p", text[m.end():], re.I) else 0)
            value = hour * 60.0
        noun = ""
        if not unit:
            after, after_end = _word_after(text, m.end())
            if after and after.lower() not in _STOP:
                noun, end = after.lower().rstrip("s"), after_end
            else:
                before = _word_before(text, m.start())
                if before and before.lower() not in _STOP:
                    noun = before.lower().rstrip("s")
        out.append({"value": value, "unit": unit, "noun": noun,
                    "start": m.start(), "end": end,
                    "bare": not unit and not noun})
    out.sort(key=lambda f: f["start"])
    # "1.2 kWh, down from 49.3": a bare number after a figure with a unit
    # is said in that unit.
    for prev, f in zip(out, out[1:]):
        if f["bare"] and not prev["bare"] and prev["unit"] not in ("", "clock"):
            f["bare"], f["unit"] = False, prev["unit"]
    # "openings 14 → 5": the second side of a pair means what the first does.
    for a, b in zip(out, out[1:]):
        if _PAIR.match(text[a["end"]:b["start"]]):
            a["pair"] = b["pair"] = True
            if a["bare"] != b["bare"]:
                for f in (a, b):
                    if f["bare"]:
                        f["bare"] = False
                        f["unit"] = f["unit"] or (a["unit"] or b["unit"])
                        f["noun"] = f["noun"] or (a["noun"] or b["noun"])
    return out


def title_figures(title: str) -> list[dict]:
    """The figures in a title's claim (its subject is a name: "Bedroom 2"
    is not a figure), with positions in the WHOLE title."""
    title = str(title or "")
    subject, sep, rest = title.partition(":")
    offset = len(subject) + 1 if sep and rest.strip() else 0
    claim = title[offset:]
    figs = []
    for f in _figures_in(claim):
        before = _word_before(claim, f["start"])
        if (not offset and not f["unit"] and before[:1].isupper()
                and f["noun"] == before.lower().rstrip("s")):
            continue  # "Plug 3", "Zone 2": a name
        figs.append({**f, "start": f["start"] + offset,
                     "end": f["end"] + offset})
    return figs


def _same_unit(a: str, b: str) -> bool:
    if a == b:
        return True
    return {a, b} in ({"°", "°F"}, {"°", "°C"})


def _close(title_value: float, body_value: float) -> bool:
    diff = abs(title_value - body_value)
    if float(title_value).is_integer():
        # A whole number in the title is the body's figure rounded.
        return diff < _TOL_INT or diff <= 0.005 * abs(body_value)
    return diff <= 0.02 * max(abs(title_value), abs(body_value), 1.0)


def _stood_behind(fig: dict, body: list[dict], body_text: str) -> bool:
    for other in body:
        if not _close(fig["value"], other["value"]):
            continue
        if not fig["unit"] or _same_unit(fig["unit"], other["unit"]):
            return True
        # A tile's bare value under a label that names the unit.
        if not other["unit"] and re.search(re.escape(fig["unit"]),
                                           body_text, re.I):
            return True
    return False


def _without(title: str, start: int, end: int) -> str:
    head = title[:start]
    lead = _LEAD.search(head)
    if lead:
        head = head[:lead.start()]
    out = re.sub(r"\s{2,}", " ", head + title[end:])
    out = re.sub(r"\s+([,.;])", r"\1", out)
    out = re.sub(r"([,;:])\s*(?=[,;]|$)", "", out)
    return re.sub(r"(?:[,;—–-]\s*)+$", "", out).strip()


_PREP = frozenset("of to in on at for from by over since until after before "
                  "with within during across per vs than".split())


def _tidy_title(title: str) -> str:
    subject, sep, rest = title.partition(":")
    if not sep:
        return title.strip()
    words = rest.split()
    if len(words) < 2 or words[0].lower() in _PREP:
        return subject.strip()
    return f"{subject.strip()}: {rest.strip()}"


def title_figures_agree(out: dict, changed: list[str]) -> None:
    """Take out of the title every figure the summary and tiles do not
    state with the same value and unit, and every bare number."""
    title = str(out.get("title") or "")
    figs = title_figures(title)
    if not figs:
        return
    texts = [str(out.get("summary") or "")]
    for h in out.get("highlights") or []:
        if isinstance(h, dict):
            texts.append(" ".join(str(h.get(k) or "") for k in
                                  ("label", "value", "delta")))
    body_text = " ".join(texts)
    body = [f for t in texts for f in _figures_in(t)]
    # A pair goes as a pair: "from 68 to 74" says nothing with one side.
    drop = [f for f in figs if f["bare"]
            or not _stood_behind(f, body, body_text)]
    if not drop:
        return
    spans = []
    for f in drop:
        start, end = f["start"], f["end"]
        if f.get("pair"):
            mates = [g for g in figs if g.get("pair")
                     and abs(g["start"] - f["start"]) < 24]
            start = min(start, *(g["start"] for g in mates))
            end = max(end, *(g["end"] for g in mates))
        spans.append((start, end))
    for start, end in sorted(set(spans), reverse=True):
        if any(s < start < e for s, e in spans if (s, e) != (start, end)):
            continue
        title = _without(title, start, end)
    title = _tidy_title(title)
    if title and title != out.get("title"):
        out["title"] = title[:120]
        changed.append("a title figure the card does not stand behind")


__all__ = ["BLIND_WHY", "GAP_LINE_MAX", "blind_lead", "finding_twin",
           "is_gap", "title_figures", "title_figures_agree", "trim_gaps"]
