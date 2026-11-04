"""What every grader shares: the verdict shape and the text matching.

A verdict is ``{"verdict": "pass"|"fail"|"unknown", "reason": str}``.
``unknown`` is an answer, not an error: it is the grader saying that a
deterministic check cannot decide this output, which is the one case the
optional LLM judge is asked about (``graders/judge.py``). A grader that
cannot read the output at all says ``fail`` and names why — an unreadable
reply is the job failing, not the grader being unsure.
"""
from __future__ import annotations

import re
import unicodedata

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
VERDICTS = (PASS, FAIL, UNKNOWN)

_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9]{3,}")


def verdict(word: str, reason: str = "") -> dict:
    assert word in VERDICTS, word
    return {"verdict": word, "reason": reason}


def passed(reason: str = "every check held") -> dict:
    return verdict(PASS, reason)


def failed(reason: str) -> dict:
    return verdict(FAIL, reason)


def unknown(reason: str) -> dict:
    return verdict(UNKNOWN, reason)


def first_failure(problems: list[str], ok: str = "every check held") -> dict:
    """``fail`` with every problem named, or ``pass``."""
    return failed("; ".join(problems)) if problems else passed(ok)


def norm(text) -> str:
    """Lowercase, punctuation to spaces, whitespace folded — the same
    normalisation the corpus scorer keys on, written out here because a
    grader's matching must not move when a panel module's does."""
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    return _WS.sub(" ", _PUNCT.sub(" ", text)).strip()


def mentions(text, phrase) -> bool:
    """Whether ``phrase`` appears in ``text``, both normalised, on word
    boundaries (so "ill" is not found inside "will")."""
    needle = norm(phrase)
    if not needle:
        return False
    return f" {needle} " in f" {norm(text)} "


def matches(text, spec) -> bool:
    """A label against a text. ``spec`` is a phrase, or ``{"any": [...],
    "all": [...]}``: at least one of ``any`` (when given) and every one of
    ``all``."""
    if isinstance(spec, str):
        return mentions(text, spec)
    if not isinstance(spec, dict):
        return False
    any_of = spec.get("any") or []
    all_of = spec.get("all") or []
    if not any_of and not all_of:
        return False
    if any_of and not any(mentions(text, p) for p in any_of):
        return False
    return all(mentions(text, p) for p in all_of)


def words(text) -> frozenset:
    return frozenset(_WORD.findall(str(text or "").lower()))


def similar(a, b, threshold: float = 0.75) -> bool:
    """Jaccard over 3+-letter words — Morph's rule for "a reworded title for
    the same idea" (`learning._similar`), at the same threshold."""
    wa, wb = words(a), words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= threshold


_DAYS_AGO = re.compile(r"\{days_ago:(\d+)\}")


def dated(value, today=None):
    """``{days_ago:N}`` in a case's text, as the date N days before
    ``today`` (default: the run's day). A case about "a battery report
    older than thirty days" has to stay older than thirty days next year,
    and a stored date would not; strings inside lists and dicts too."""
    import datetime  # noqa: PLC0415

    today = today or datetime.date.today()
    if isinstance(value, str):
        return _DAYS_AGO.sub(
            lambda m: (today - datetime.timedelta(days=int(m.group(1)))).isoformat(),
            value)
    if isinstance(value, list):
        return [dated(v, today) for v in value]
    if isinstance(value, dict):
        return {k: dated(v, today) for k, v in value.items()}
    return value
