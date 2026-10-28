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

Two more came back after the contract stopped asking for a verdict first:

* **An opening reassurance.** Seven cards in eleven opened "There's no
  leak and nothing to fix", "No action", "Normal, nothing to do" — one
  denying a leak nobody had raised — and the one card that needed action
  was lost among them. A summary that OPENS with a no-action clause and
  then says something is stripped of the clause (`strip_reassurance`); a
  card that is only an all-clear keeps it, and a reassurance after the
  finding stays where it was put.
* **The title said twice.** "Septic pump: 34 h, 143 gal since Thu" over
  "It last ran 33 h 55 min ago … with 143 gal since". The title holds the
  headline, so a first summary sentence that repeats two or more of the
  title's figures (`title_echo`; a duration of hours and minutes counts as
  the hours it rounds to) is dropped, when another sentence follows it.

And four after the card carried its judgement in a field of its own
(`verdict`, one of `VERDICTS`, drawn as ONE chip):

* **The verdict written six ways in the prose.** "Verdict: normal.",
  "Needs action.", "Nothing to fix.", "This needs one change.", "Neither
  unit is broken." each opened a summary, so a card's judgement was a
  sentence to read rather than a chip to see. A first sentence that is a
  verdict and nothing else (`verdict_of_sentence`) is taken off when
  another sentence follows (`lead_verdict`) and becomes the chip; a card
  stored before the field existed gets the same reading on the way out
  (`legacy`), so it never shows two.
* **A card whose lead is another card's subject.** A hose card opened on
  the septic pump's figure. A first sentence naming only what another card
  is about, and nothing the title names, is not the lead (`others`).
* **A figure that disagrees with an open finding.** "Dropped 7 times since
  Sat" under a finding counting 14 times in 7 days: the sentence goes and
  the finding leads (`disagreeing_row`); a card saying a fix is already in
  place for a finding names it (`claims_fixed`), so the finding's own check
  is asked again.
* **All fine about nothing.** A scheduled card whose verdict is all fine,
  with nothing to act on and nothing changed (`no_change`), is held like a
  card about nothing; one that is stored anyway folds into the Reports
  pane's "All quiet" line (`folds_quiet`).

Everything here is pure over the parsed reply and the previous card, so
the server's `_generate` asks it once and the tests drive it directly. It
never invents a number or a sentence about the house: a rewrite only ever
REMOVES the verdict clause and, for the first shape, says when the last
card was made — a date the card already carries.
"""
from __future__ import annotations

import datetime as dt
import re

import card_claims

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
    r"nothing new since|no change since|"
    r"no (?:activity|use|usage|runs?|cycles?|events?|openings?|overrides?|"
    r"changes?)\b|"
    r"0(?:\.0+)? ?(?:kwh|wh|runs?|cycles?|events?|times|openings?|"
    r"overrides?)\b|"
    r"only (?:one|1) \w+ in (?:the last )?\d+ ?(?:h|hours?|days?))", re.I)

_ZERO_COUNT = re.compile(
    r"\s*(?:0(?:\.0+)?|none|no|zero)\s*(?:kwh|wh|runs?|cycles?|events?|times|"
    r"openings?|overrides?)?\s*", re.I)

# A clause that tells the reader there is nothing to do, or denies a
# problem: the opening reassurance. Matched over the WHOLE clause, so
# "There's no leak and nothing to fix" is one.
_REASSURE = re.compile(
    r"\b(?:nothing (?:to (?:fix|do|worry about|act on|report|change)|"
    r"(?:needs|requires) (?:action|attention|fixing|doing|changing))|"
    r"no (?:action|change|fix|attention)(?: is)?(?: needed| required)?|"
    r"no need to (?:act|worry|do anything|change anything)|"
    r"all (?:good|clear|normal|fine))\b", re.I)
# A clause that is a verdict word and nothing else ("Normal", "Fine").
_BARE_VERDICT = re.compile(
    r"\s*(?:all\s+)?(?:normal|fine|ok|okay|healthy|good|clear|steady)\s*",
    re.I)

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
QUIET_WHY = ("all fine and nothing changed since the last card, so the last "
             "card was kept rather than replaced with one saying so again")

# The card's one judgement, and the only words it may take. The panel
# draws it as one chip; the summary never says it again.
FINE, LOOK, ACTION = "all fine", "worth a look", "needs action"
VERDICTS = (FINE, LOOK, ACTION)


def clean_verdict(value) -> str:
    """One of `VERDICTS`, or "" for anything else."""
    text = str(value or "").strip().lower()
    return text if text in VERDICTS else ""


# A sentence that is a verdict and nothing else, in the shapes cards wrote
# it. Matched over the WHOLE sentence: "Needs action — the pump ran 9
# times" is a finding with a lead clause (`strip_reassurance`'s job), not a
# verdict sentence.
_ACTION_SENT = re.compile(
    r"(?:(?:this|it|one thing|something|the \w+(?: \w+)?)\s+)?"
    r"(?:needs|requires|wants)\s+(?:(?:one|a|some|your)\s+)?"
    r"(?:action|change|fix|attention|doing|changing|fixing)"
    r"(?:\s+(?:now|today|soon))?|action (?:needed|required)|act now", re.I)
_LOOK_SENT = re.compile(
    r"(?:(?:this is|it is|it's|this one is)\s+)?"
    r"(?:worth (?:a look|a check|checking|watching)|one to watch|"
    r"keep an eye on (?:it|this|them))", re.I)
_FINE_SENT = re.compile(
    r"(?:all\s+)?(?:normal|fine|ok|okay|good|clear|healthy|steady|as expected)|"
    r"(?:all|everything|it|this|both|they|each|the \w+(?: \w+)?)\s+"
    r"(?:is|are|looks?|seems?|reads?|runs?)\s+(?:normal|fine|ok|okay|good|"
    r"healthy|as expected|working)|"
    r"nothing (?:to (?:fix|do|report|worry about|act on)|(?:is )?(?:wrong|broken)|"
    r"(?:needs|requires) (?:action|attention|doing|fixing|changing))|"
    r"no (?:action|change|fix|attention)(?: is)?(?: needed| required)?|"
    r"no (?:problems?|issues?|faults?|concerns?)(?: found| here)?|"
    r"neither (?:\w+\s+){1,3}(?:is|was) (?:broken|faulty|at fault|wrong|failing)|"
    r"(?:there is|there's) nothing wrong", re.I)
_VERDICT_LABEL = re.compile(r"(?:the\s+)?verdict\s*[:\-–—]\s*(.+)", re.I)


def verdict_of_sentence(sentence: str) -> str:
    """The verdict a sentence IS, or "" when it says anything else."""
    text = str(sentence or "").strip().rstrip(".!…").strip()
    label = _VERDICT_LABEL.fullmatch(text)
    if label:
        text = label.group(1).strip().rstrip(".!…").strip()
        if clean_verdict(text):
            return clean_verdict(text)
    for rx, verdict in ((_ACTION_SENT, ACTION), (_LOOK_SENT, LOOK),
                        (_FINE_SENT, FINE)):
        if rx.fullmatch(text):
            return verdict
    return ""


def lead_verdict(summary: str) -> tuple[str, str, bool]:
    """`(verdict, summary, stripped)`: the verdict the summary's first
    sentence is, and the summary without it when another sentence follows
    (a summary that is only an all-clear keeps it, as the contract allows).
    """
    parts = _SENTENCE_END.split(str(summary or "").strip(), maxsplit=1)
    verdict = verdict_of_sentence(parts[0]) if parts and parts[0] else ""
    if verdict and len(parts) == 2 and parts[1].strip():
        return verdict, _capital(parts[1]), True
    return verdict, summary, False


def _title_verdict(title: str) -> tuple[str, str]:
    """`(title without a trailing verdict, the verdict)`: "Sump: normal"."""
    subject, sep, rest = str(title or "").partition(":")
    if sep and subject.strip():
        verdict = verdict_of_sentence(rest)
        if verdict:
            return subject.strip(), verdict
    return title, ""


def legacy(card: dict) -> dict:
    """A stored card read with one verdict: the chip it carries, or — for a
    card made before the field existed — the verdict its first sentence or
    its title's tail wrote, taken off the prose. Returns the fields to show
    (`title`, `summary`, `verdict`); the stored file is not touched."""
    card = card or {}
    title = str(card.get("title") or "")
    summary = str(card.get("summary") or "")
    given = clean_verdict(card.get("verdict"))
    said, body, stripped = lead_verdict(summary)
    plain_title, title_said = _title_verdict(title)
    out = {"title": plain_title if title_said else title,
           "summary": body if stripped else summary,
           "verdict": given or said or title_said}
    if not given and not said and not title_said:
        clause, after = lead_clause(summary)
        if after.strip() and is_reassurance(clause):
            out["summary"], _ = strip_reassurance(summary)
            out["verdict"] = FINE
    return out


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


def is_reassurance(clause: str) -> bool:
    """A clause whose whole job is telling the reader there is nothing to
    do: "No action", "Normal", "There's no leak and nothing to fix"."""
    clause = clause or ""
    if _BARE_VERDICT.fullmatch(clause):
        return True
    return bool(_REASSURE.search(clause)) or (says_fine(clause)
                                              and len(clause) <= 40)


def strip_reassurance(text: str) -> tuple[str, bool]:
    """The summary with its OPENING reassurance taken off, when something
    follows it; `(text, False)` when it opens with something else or is
    nothing but an all-clear (which the contract allows)."""
    rest, stripped = text or "", False
    while True:
        clause, after = lead_clause(rest)
        if clause == rest or not after.strip() or not is_reassurance(clause):
            break
        rest, stripped = after, True
    return (_capital(rest), True) if stripped else (text, False)


# A duration of hours and minutes is one figure, the hours it rounds to:
# "33 h 55 min" is the "34 h" of the title said again.
_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*h(?:ours?)?\s+(\d+)\s*min", re.I)
_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_FIGURE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[A-Z0-9“\"'])")


def _figures(text: str) -> list[float]:
    text = text or ""
    out: list[float] = []

    def hours(m: re.Match) -> str:
        out.append(float(m.group(1)) + float(m.group(2)) / 60.0)
        return " "

    def clock(m: re.Match) -> str:
        out.append(int(m.group(1)) * 100.0 + int(m.group(2)) + 0.5)
        return " "

    text = _CLOCK.sub(clock, _DURATION.sub(hours, text))
    for m in _FIGURE.finditer(text):
        n = _num(m.group(0))
        if n is not None:
            out.append(n)
    return out


def title_echo(title: str, sentence: str) -> int:
    """How many of the title's figures a sentence says again (a figure
    within 2% of one is the same figure said in other units)."""
    said = _figures(sentence)
    count = 0
    for n in dict.fromkeys(_figures(title)):
        if any(abs(n - m) <= 0.02 * max(abs(n), abs(m), 1.0) for m in said):
            count += 1
    return count


def drop_title_echo(title: str, summary: str) -> tuple[str, bool]:
    """The summary without a first sentence that only restates the title."""
    parts = _SENTENCE_END.split(summary or "", maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return summary, False
    if title_echo(title, parts[0]) < 2:
        return summary, False
    return _capital(parts[1]), True


def _finish(out: dict, changed: list[str]) -> None:
    """The two passes every stored card gets, whatever else was rewritten:
    no opening reassurance, and no first sentence that is the title again."""
    summary = str(out.get("summary") or "")
    body, stripped = strip_reassurance(summary)
    if stripped:
        out["summary"] = body
        changed.append("no opening reassurance")
    title = str(out.get("title") or "")
    subject, sep, rest = title.partition(":")
    if sep and subject.strip() and is_reassurance(rest.strip()):
        out["title"] = subject.strip()[:120]
        if "no opening reassurance" not in changed:
            changed.append("no opening reassurance")
    body, dropped = drop_title_echo(str(out.get("title") or ""),
                                    str(out.get("summary") or ""))
    if dropped:
        out["summary"] = body
        changed.append("the title said twice")


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


def initial_verdict(obj: dict) -> str:
    """The verdict a reply carries: its `verdict` field, else the one its
    first sentence, its title's tail or its opening clause wrote."""
    obj = obj or {}
    given = clean_verdict(obj.get("verdict"))
    if given:
        return given
    said = lead_verdict(str(obj.get("summary") or ""))[0]
    if said:
        return said
    title_said = _title_verdict(str(obj.get("title") or ""))[1]
    if title_said:
        return title_said
    if is_reassurance(lead_clause(str(obj.get("summary") or ""))[0]):
        return FINE
    return ""


def review(obj: dict, previous: dict | None = None,
           open_rows=(), others=(), names_in=None, asked: bool = False) -> dict:
    """What to do with one parsed card (`_review`), with the reassurance,
    a verdict sentence and the restated title taken off whatever is to be
    stored, and the card's one `verdict` set from what it said.

    ``others`` is the entity sets of the other cards on the dashboard and
    ``names_in`` the panel's reader of which entities a sentence names;
    with both, a first sentence about another card's subject is not this
    card's lead. ``fixed``, present only when there is one, is the open rows
    the card says are already fixed, whose checks the caller asks again.
    """
    # ``asked``: a card somebody asked for. Its claim is the answer to
    # their question, so a blind spot or a non-event is never folded.
    verdict = initial_verdict(obj)
    got = _review(obj, previous, open_rows, verdict)
    fixed = claims_fixed(obj, open_rows)
    if fixed:
        # Only when there are some: the answer stays the three keys it
        # always was for every card that claims nothing.
        got["fixed"] = fixed
    if got["hold"]:
        return got
    out = got["obj"]
    blind = "" if asked else card_claims.blind_lead(out, verdict)
    if blind and open_row_named(out, open_rows) is None:
        # Its headline is what brAIn could not see, or that nothing
        # happened: not news (`card_claims`). The last card stays; a first
        # card is stored folded into the quiet line.
        if previous:
            got = {"obj": out, "hold": card_claims.BLIND_WHY, "changed": []}
            if fixed:
                got["fixed"] = fixed
            return got
        out["blind"] = True
    # Before `_finish`: the title's figures are read against the body the
    # model wrote, before a summary sentence restating them is taken off.
    card_claims.title_figures_agree(out, got["changed"])
    _finish(out, got["changed"])
    card_claims.trim_gaps(out, got["changed"])
    _strip_verdict_sentence(out, got["changed"])
    _not_another_cards_lead(out, got["changed"], others, names_in)
    changed = got["changed"]
    if "no verdict over nothing new" in changed:
        verdict = ""
    elif verdict != ACTION and any(c in changed for c in (
            "no fine verdict over an open finding", "no fine verdict over a rise",
            "a figure that disagrees with an open finding")):
        verdict = LOOK
    if verdict:
        out["verdict"] = verdict
    else:
        out.pop("verdict", None)
    return got


def _strip_verdict_sentence(out: dict, changed: list[str]) -> None:
    """No first sentence that is a verdict, and no title ending in one: the
    chip says it once."""
    _, body, stripped = lead_verdict(str(out.get("summary") or ""))
    if stripped:
        out["summary"] = body
        changed.append("no verdict sentence leading the summary")
    title, said = _title_verdict(str(out.get("title") or ""))
    if said:
        out["title"] = title[:120]
        if "no verdict sentence leading the summary" not in changed:
            changed.append("no verdict sentence leading the summary")


def _own_words(out: dict) -> list[str]:
    return _texts(out) + [str(x) for x in out.get("learned") or []
                          if isinstance(x, str)]


def _not_another_cards_lead(out: dict, changed: list[str], others,
                            names_in) -> None:
    """A first sentence naming only what another card is about, and nothing
    else this card names, is dropped when the card has more to say: a hose
    card that opened on the septic pump's figure told the pump's story with
    a number the pump's own card did not have."""
    if not names_in or not others:
        return
    parts = _SENTENCE_END.split(str(out.get("summary") or ""), maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return
    try:
        lead = set(names_in(parts[0]) or ())
        rest = set(names_in(" ".join([parts[1], str(out.get("title") or "")]
                                     + _texts(out)[2:])) or ())
    except Exception:  # noqa: BLE001 — a reader that failed decides nothing
        return
    others = [set(o) for o in others if o]
    if not lead or lead & rest:
        return
    if all(any(eid in o for o in others) for eid in lead):
        out["summary"] = _capital(parts[1])
        changed.append("another card's subject as the lead")


# A count the card or a row states, with what it counts. Only counts: a
# window ("7 days", "48 h") is the period, and two periods differing is
# what the card is told to explain in words, not a disagreement.
_COUNT = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(times|drops?|dropouts?|runs?|cycles?|"
    r"openings?|events?|restarts?|overrides?|gal(?:lons?)?|kwh|litres?|liters?)\b",
    re.I)
_UNIT = {"drop": "drop", "dropout": "drop", "run": "run", "cycle": "cycle",
         "opening": "opening", "event": "event", "restart": "restart",
         "override": "override", "gallon": "gal", "liter": "litre"}


def _counts(text: str) -> list[tuple[float, str]]:
    out = []
    for m in _COUNT.finditer(text or ""):
        n = _num(m.group(1))
        unit = m.group(2).lower().rstrip("s") if m.group(2).lower() not in (
            "times", "kwh") else m.group(2).lower()
        if unit.startswith("gal"):
            unit = "gal"
        unit = _UNIT.get(unit, unit)
        if n is not None:
            out.append((n, unit))
    return out


def _sentences(text: str) -> list[str]:
    return [p for p in _SENTENCE_END.split(str(text or "").strip()) if p]


def disagreeing_row(obj: dict, open_rows) -> tuple[dict | None, str]:
    """`(row, sentence)`: an open finding the card names whose count a
    sentence about that device states differently ("dropped 7 times" under
    a row counting 14), or `(None, "")`."""
    for row in open_rows or ():
        if not isinstance(row, dict) or not row.get("text"):
            continue
        theirs = _counts(f"{row.get('text') or ''} {row.get('detail') or ''}")
        if not theirs:
            continue
        for sentence in _sentences(obj.get("summary")):
            if not _names_row([sentence], row):
                continue
            mine = _counts(sentence)
            for n, unit in mine:
                same = [m for m, u in theirs if u == unit]
                if same and not any(
                        abs(n - m) <= 0.02 * max(abs(n), abs(m), 1.0)
                        for m in same):
                    return row, sentence
    return None, ""


# A sentence saying a problem has already been dealt with.
_FIXED_SAYS = re.compile(
    r"\b(?:now (?:handles|covers|stops|prevents|catches|blocks)|"
    r"already (?:handles|covers|fixed|in place|done|added|resolved)|"
    r"(?:has|have) (?:since )?been (?:fixed|added|resolved|replaced|repaired)|"
    r"(?:is|are) (?:now )?(?:fixed|in place|resolved|repaired)|"
    r"no longer (?:happens|needed|drops?|fails?|missing))\b", re.I)


def claims_fixed(obj: dict, open_rows) -> list[dict]:
    """The open rows the card says are already fixed: named in its
    `fixed` field, or named in a sentence saying so."""
    obj = obj or {}
    listed = {str(e) for e in obj.get("fixed") or [] if isinstance(e, str)}
    out = []
    for row in open_rows or ():
        if not isinstance(row, dict):
            continue
        if row.get("entity_id") and str(row["entity_id"]) in listed:
            out.append(row)
            continue
        if any(_FIXED_SAYS.search(s) and _names_row([s], row)
               for s in _sentences(obj.get("summary"))):
            out.append(row)
    return out


# The card's own words for nothing having changed, beyond `_NOTHING_NEW`:
# "no cooling since 17 Oct", "neither unit has run since".
_NO_CHANGE = re.compile(
    r"\b(?:no|nothing)\s+(?:\w+\s+){0,2}since\b|"
    r"\b(?:has|have|had)(?:n'?t| not)\s+(?:\w+\s+)?(?:run|been|cycled|changed|"
    r"moved|fired|started|come on)\b[^.]*\bsince\b|"
    r"\bneither \w+ (?:has|have) (?:\w+ )?(?:run|cycled|changed|fired|started)\b|"
    r"\bno change\b|\bunchanged\b", re.I)


def _figures_of(card: dict) -> dict:
    return {str(h.get("label")): str(h.get("value"))
            for h in (card or {}).get("highlights") or []
            if isinstance(h, dict) and h.get("label")}


def no_change(obj: dict, previous: dict | None = None) -> bool:
    """The card says nothing changed, or shows the figures it showed last
    time, every one of them."""
    if nothing_new(obj):
        return True
    if any(_NO_CHANGE.search(t) for t in _texts(obj)[:2]):
        return True
    now, then = _figures_of(obj), _figures_of(previous or {})
    return bool(now) and now == then


def nothing_to_act(obj: dict) -> bool:
    """Nothing filed, nothing offered and no figure marked as needing
    attention."""
    obj = obj or {}
    if obj.get("findings") or obj.get("opportunities"):
        return False
    return not any(str(h.get("status") or "") in ("warning", "serious", "critical")
                   for h in obj.get("highlights") or [] if isinstance(h, dict))


def quiet_now(obj: dict, previous: dict | None, verdict: str) -> bool:
    """All fine, nothing to act on, and nothing happened or changed."""
    return (verdict == FINE and nothing_to_act(obj)
            and (quiet(obj) or no_change(obj, previous)))


def folds_quiet(card: dict) -> bool:
    """A stored card the Reports pane folds into its "All quiet" line
    rather than giving a card of its own."""
    card = card or {}
    shown = legacy(card)
    if (card.get("blind") and nothing_to_act(card)
            and shown["verdict"] not in (LOOK, ACTION)):
        # A headline that was a blind spot or a non-event (`card_claims`).
        return True
    if shown["verdict"] != FINE or not nothing_to_act(card):
        return False
    return bool(card.get("quiet")) or quiet(card) or no_change(card, None)


def _review(obj: dict, previous: dict | None = None,
            open_rows=(), verdict: str = "") -> dict:
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
    row, sentence = disagreeing_row(out, open_rows)
    if row is not None:
        # A count about a device an open finding counts differently: the
        # finding's figure stands, and the card leads with it rather than
        # telling the homeowner two numbers for one thing.
        kept = [s for s in _sentences(summary) if s != sentence]
        lead = f"Open finding: {str(row['text']).rstrip('.')}."
        out["summary"] = " ".join([lead] + kept).strip()
        changed.append("a figure that disagrees with an open finding")
        return {"obj": out, "hold": "", "changed": changed}
    if (previous and clean_verdict(out.get("verdict")) == FINE
            and quiet_now(out, previous, FINE)):
        # The field's own all-clear over nothing that changed: the card
        # about nothing, said in the new words.
        return {"obj": out, "hold": QUIET_WHY, "changed": []}
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
    if previous and verdict not in (LOOK, ACTION) and quiet(out):
        return {"obj": out, "hold": HOLD_WHY, "changed": []}
    if (fine or title_fine) and rises(out):
        if fine and body:
            out["summary"] = _capital(body)
        subject, stripped = _strip_title(title)
        if stripped and subject:
            out["title"] = subject[:120]
        changed.append("no fine verdict over a rise")
    return {"obj": out, "hold": "", "changed": changed}


__all__ = ["ACTION", "FINE", "HOLD_WHY", "LOOK", "QUIET_WHY", "RISE",
           "VERDICTS", "claims_fixed", "clean_verdict", "disagreeing_row",
           "drop_title_echo", "folds_quiet", "initial_verdict",
           "is_reassurance", "lead_verdict", "legacy", "no_change",
           "nothing_to_act", "quiet_now", "verdict_of_sentence",
           "lead_clause", "nothing_new", "open_row_named", "quiet",
           "strip_reassurance", "title_echo",
           "review", "rises", "says_fine", "strip_verdict", "when_said"]
