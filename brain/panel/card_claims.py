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


__all__ = ["BLIND_WHY", "GAP_LINE_MAX", "blind_lead", "finding_twin",
           "is_gap", "trim_gaps"]
