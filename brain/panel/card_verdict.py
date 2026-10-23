"""A card's opening verdict, read against the card's own evidence.

The contract asks every card to open with ONE plain verdict, and three
shapes came back from a real house that the contract alone did not stop:

* **A verdict over no new evidence.** "Dryer: no run since Sat, so no new
  vent reading" opened "The vent looks fine"; an air-handler card with no
  recent run opened "Fine, nothing points to filter trouble" on readings
  days old. A verdict of fine is a claim about now, and with nothing read
  since the last card it is the last card's claim repeated. So the lead
  says there is nothing new since then, and gives no verdict.
* **A verdict its own figures contradict.** "Mon morning 193 min vs Sun
  112 min" opened "Nothing needs action" and then said the room was
  working harder. A rise of more than half against the comparison the card
  itself gives is not "fine"; the verdict is taken off and the figures
  lead.
* **A card about nothing.** "0 kWh", "nothing ran", "only 1 override in
  48 h": a card whose whole content is that nothing happened is not a
  fresh card. A scheduled run that produced one keeps the card that was
  there and says why (`HOLD_WHY`), the way `REFRESH_HOLDS` already says why
  a card did not move.

Everything here is pure over the parsed reply and the previous card, so
the server's `_generate` asks it once and the tests drive it directly. It
never invents a number or a sentence about the house: a rewrite only ever
REMOVES the verdict clause and, for the first shape, says when the last
card was made — a date the card already carries.
"""
from __future__ import annotations

import datetime as dt
import re

# The verdict words. A clause is a verdict of fine when it says one of
# these and does not negate it ("not fine" is a finding, not a verdict).
_FINE = re.compile(
    r"\b(?:fine|ok|okay|healthy|all good|all clear|all normal|"
    r"(?:is|are|looks|look|seems|remains|stays|running|runs|reads?) normal(?:ly)?|"
    r"nothing (?:new )?(?:needs|requires|to) (?:action|attention|doing|do|worry about)|"
    r"no action (?:is )?(?:needed|required)|nothing points to|"
    r"no (?:issues|problems|concerns|faults))\b", re.I)
_NEGATED = re.compile(r"\b(?:not|isn'?t|aren'?t|never|no longer)\s+(?:\w+\s+)?"
                      r"(?:fine|ok|okay|healthy|normal)\b", re.I)
# Where the opening clause ends.
_CLAUSE_END = re.compile(r"\s*(?:[.;:!?]|\s[—–-]\s|,)\s*")

# The card's own words for "nothing has been read since". Deliberately the
# card's admission and not a guess about the data: these are sentences in
# which the run says it has no new reading.
_NOTHING_NEW = re.compile(
    r"\b(?:no (?:new|fresh|recent|newer) (?:\w+ )?(?:reading|readings|run|runs|"
    r"data|cycle|cycles|activity|samples?)|no (?:run|cycle|use) since|"
    r"(?:has|have)(?:n'?t| not) (?:run|been used|cycled|changed) since|"
    r"not (?:run|used|cycled) since|nothing new|no recent run|"
    r"(?:\d+|two|three|four|five|several)[ -]days?[ -]old|days[ -]old)\b",
    re.I)

# A card about nothing having happened.
_QUIET = re.compile(
    r"\b(?:nothing (?:happened|ran|to report|changed|moved|was used)|"
    r"no (?:activity|use|usage|runs?|cycles?|events?|openings?|overrides?|"
    r"changes?)\b|"
    r"0(?:\.0+)? ?(?:kwh|wh|runs?|cycles?|events?|times|openings?|"
    r"overrides?)\b|"
    r"only (?:one|1) \w+ in (?:the last )?\d+ ?(?:h|hours?|days?))", re.I)

_ZERO_COUNT = re.compile(
    r"\s*(?:0(?:\.0+)?|none|no|zero)\s*(?:kwh|wh|runs?|cycles?|events?|times|"
    r"openings?|overrides?)?\s*", re.I)

# A rise the card states itself.
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_VS = re.compile(_NUM + r"[^\d.;]{0,14}?\b(?:vs\.?|versus|against|compared with)"
                 r"\b[^\d;]{0,25}?" + _NUM, re.I)
_ARROW = re.compile(_NUM + r"[^\d;]{0,10}?(?:→|->)[^\d;]{0,10}?" + _NUM)
_FROM_TO = re.compile(r"\bfrom\s+" + _NUM + r"[^\d;]{0,12}?\bto\s+" + _NUM, re.I)
_PCT_UP = re.compile(r"(?:\+|\bup\s+|\brose\s+|\brisen\s+)" + _NUM + r"\s?%", re.I)
_DOUBLED = re.compile(r"\b(?:doubled|tripled|twice (?:the|its|as)|"
                      r"three times (?:the|its|as))\b", re.I)
RISE = 1.5

HOLD_WHY = ("nothing happened since the last card, so the last card was kept "
            "rather than replaced with one about nothing")


def _num(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _texts(obj: dict) -> list[str]:
    out = [str(obj.get("title") or ""), str(obj.get("summary") or "")]
    for h in obj.get("highlights") or []:
        if isinstance(h, dict):
            out += [str(h.get(k) or "") for k in ("label", "value", "delta")]
    return out


def lead_clause(text: str) -> tuple[str, str]:
    """`(opening clause, the rest)` of a sentence."""
    m = _CLAUSE_END.search(text or "")
    if not m:
        return text or "", ""
    return text[:m.start()], text[m.end():]


def says_fine(clause: str) -> bool:
    return bool(_FINE.search(clause or "")) and not _NEGATED.search(clause or "")


def rises(obj: dict) -> bool:
    """Whether the card's own figures show a rise of more than half."""
    for text in _texts(obj):
        for m in _VS.finditer(text):
            now, then = _num(m.group(1)), _num(m.group(2))
            if now is not None and then and now / then >= RISE:
                return True
        for rx in (_ARROW, _FROM_TO):
            for m in rx.finditer(text):
                then, now = _num(m.group(1)), _num(m.group(2))
                if now is not None and then and now / then >= RISE:
                    return True
        for m in _PCT_UP.finditer(text):
            pct = _num(m.group(1))
            if pct is not None and pct >= (RISE - 1) * 100:
                return True
        if _DOUBLED.search(text):
            return True
    return False


def nothing_new(obj: dict) -> bool:
    """The card says it read nothing newer than what it had. Its own words
    and nothing else: the same figures twice is a steady house, not proof
    that nothing was read, so it is not read as one."""
    return any(_NOTHING_NEW.search(t) for t in _texts(obj))


def quiet(obj: dict) -> bool:
    """A card whose whole content is that nothing happened.

    Nothing filed, nothing marked as needing attention, and either every
    figure it shows is zero or its own words say nothing happened.
    """
    if obj.get("findings"):
        return False
    highlights = [h for h in obj.get("highlights") or [] if isinstance(h, dict)]
    if any(str(h.get("status") or "") in ("warning", "serious", "critical")
           for h in highlights):
        return False
    # A zero COUNT or a zero of energy is nothing having happened; 0 °F in
    # a freezer is a reading, and not one.
    if highlights and all(_ZERO_COUNT.fullmatch(str(h.get("value") or ""))
                          for h in highlights):
        return True
    return bool(_QUIET.search(str(obj.get("summary") or ""))
                or _QUIET.search(str(obj.get("title") or "")))


def when_said(stamp: str | None) -> str:
    """`Sat 12 Oct` for a card's generated_at, or "" when it has none."""
    try:
        made = dt.datetime.strptime(str(stamp or "")[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return ""
    return made.strftime("%a ") + str(made.day) + made.strftime(" %b")


def _capital(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def _strip_title(title: str) -> tuple[str, bool]:
    """The title with a verdict taken off, and whether one was."""
    subject, sep, rest = title.partition(":")
    if sep and says_fine(rest):
        return subject.strip(), True
    m = re.match(r"^(.*?)\s+(?:looks|look|is|are|seems|remains|stays)\s+"
                 r"(?:fine|ok|okay|healthy|normal)\b.*$", title, re.I)
    if m and m.group(1).strip():
        return m.group(1).strip(), True
    if says_fine(lead_clause(title)[0]):
        rest = lead_clause(title)[1]
        return _capital(rest), True
    return title, False


def strip_verdict(text: str) -> tuple[str, bool]:
    """The sentence with its opening verdict clauses taken off ("Fine,
    nothing points to filter trouble; readings are 3 days old" is two),
    and whether there was one."""
    rest, stripped = text or "", False
    while True:
        clause, after = lead_clause(rest)
        if not says_fine(clause) or clause == rest:
            break
        rest, stripped = after, True
    if not stripped and says_fine(lead_clause(rest)[0]) \
            and lead_clause(rest)[0] == rest:
        return "", True
    return rest.strip(), stripped


def _names_row(texts: list[str], row: dict) -> bool:
    """Whether the card's words name the device an open row is about."""
    words = " ".join(texts)
    for name in (row.get("name"), row.get("entity_id")):
        name = str(name or "").strip()
        if len(name) >= 4 and re.search(r"(?<![\w.])" + re.escape(name)
                                         + r"(?![\w])", words, re.I):
            return True
    return False


def open_row_named(obj: dict, open_rows) -> dict | None:
    """The first open finding about a device the card names, or None."""
    texts = _texts(obj)
    for row in open_rows or ():
        if isinstance(row, dict) and row.get("text") and _names_row(texts, row):
            return row
    return None


def review(obj: dict, previous: dict | None = None,
           open_rows=()) -> dict:
    """What to do with one parsed card.

    `{"obj": the card to store, "hold": "" or why it should not be stored,
    "changed": [what was rewritten]}`. `obj` is a copy; the reply handed
    in is not touched. `hold` is set only when there IS a previous card to
    keep: a first card about nothing is still the first card.
    """
    out = dict(obj or {})
    changed: list[str] = []
    summary = str(out.get("summary") or "")
    title = str(out.get("title") or "")
    body, fine = strip_verdict(summary)
    title_fine = says_fine(title)
    row = open_row_named(out, open_rows) if (fine or title_fine) else None
    if row is not None:
        # A fine verdict about a device an open finding says is not: the
        # finding is the verdict, and the card points to it.
        lead = f"Open finding: {str(row['text']).rstrip('.')}."
        rest = body if fine else summary
        out["summary"] = f"{lead} {_capital(rest)}".strip()
        subject, stripped = _strip_title(title)
        if stripped and subject:
            out["title"] = subject[:120]
        changed.append("no fine verdict over an open finding")
        return {"obj": out, "hold": "", "changed": changed}
    if (fine or title_fine) and nothing_new(out):
        when = when_said((previous or {}).get("generated_at"))
        since = f"Nothing new since {when}" if when else \
            "Nothing new since the last reading"
        body = body if fine else summary
        out["summary"] = f"{since}: {body}" if body else f"{since}."
        subject, stripped = _strip_title(title)
        if stripped:
            tail = since[0].lower() + since[1:]
            out["title"] = (f"{subject}: {tail}" if subject else since)[:120]
        out["highlights"] = [
            {k: v for k, v in h.items() if not (k == "status" and v == "good")}
            if isinstance(h, dict) else h
            for h in out.get("highlights") or []]
        changed.append("no verdict over nothing new")
        return {"obj": out, "hold": "", "changed": changed}
    if previous and quiet(out):
        return {"obj": out, "hold": HOLD_WHY, "changed": []}
    if (fine or title_fine) and rises(out):
        if fine and body:
            out["summary"] = _capital(body)
        subject, stripped = _strip_title(title)
        if stripped and subject:
            out["title"] = subject[:120]
        changed.append("no fine verdict over a rise")
    return {"obj": out, "hold": "", "changed": changed}


__all__ = ["HOLD_WHY", "RISE", "lead_clause", "nothing_new", "open_row_named",
           "quiet",
           "review", "rises", "says_fine", "strip_verdict", "when_said"]
