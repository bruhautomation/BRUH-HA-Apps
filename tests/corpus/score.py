#!/usr/bin/env python3
"""Scoring one corpus entry — the corpus's shape over the one scorer.

The arithmetic is not here. `brain/panel/scoring.py` owns "precision and
recall against labels", because `panel/rehearsal.py` grades the same two
producers against defects it planted on a real house and cannot import
from the test tree, while the test tree already has `panel/` on its path.
What lives here is the part that is about a *corpus entry*: which labels
an entry carries, and what it means for a row to answer one.

Two kinds of entry, two match rules, and the difference is what makes the
whole thing affordable:

  * a **checks** entry names check ids and the thing each should be about,
    and is graded against `checks.run_all` — no model, no token, ordinary
    CI. This is the half that fails when a floor moves.
  * an **analyst** entry carries the bundle a real run was given and the
    endings a person gave its findings, and is graded against a real
    model's reply. A `done`/`got_it` label is a finding that was right, so
    reporting it is a hit; a `wrong` label is a finding that was not, so
    reporting it is a **false positive** rather than a miss — which is the
    whole reason the corpus is worth having and is the distinction a
    hit-count alone cannot make.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent
if str(REPO / "brain" / "panel") not in sys.path:
    sys.path.insert(0, str(REPO / "brain" / "panel"))

import scoring  # noqa: E402

# The endings that say the report was RIGHT, and the one that says it was
# not. `findings_store` keeps `done` and `ack` apart because they are
# different facts about the house; here they are the same evidence about
# the producer, which is why the mapping is written out rather than
# assumed from the ledger's `kind`.
CONFIRMED = ("done", "got_it")
DENIED = ("wrong",)

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize(text: str) -> str:
    """The same normalisation `findings_store` dedupes on.

    Copied rather than imported *deliberately*: a label is a key recorded
    at the moment somebody pressed a button, possibly releases ago, and if
    the store's normalisation changes then old labels have to go on
    meaning what they meant. Importing it would silently re-grade the
    whole corpus on a refactor of an unrelated file.
    """
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _row_text(row) -> str:
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        return ""
    return " ".join(str(row.get(k) or "") for k in
                    ("text", "detail", "entity_id", "fix", "source"))


def check_match(label: dict, row: dict) -> bool:
    """Whether this filed row is the one this checks label expects.

    Two halves, and both are required. The **source** has to be the check
    the label names, because a different rule reporting the same box is
    not that rule working; and the row has to be **about** the thing the
    label names, because a check firing on some other entity is not the
    planted defect found.
    """
    if not isinstance(row, dict):
        return False
    if str(row.get("source") or "") != f"check:{label.get('check')}":
        return False
    wanted = str(label.get("entity_id") or "").strip()
    if not wanted:
        return True
    return wanted in _row_text(row)


def analyst_match(label: dict, row) -> bool:
    """Whether this reported finding is the one this label is about.

    On the normalised finding text, which is the key the ending was
    recorded under — and then, failing that, on the entity id, because a
    model that reworded a report of the same fault is the case the whole
    exercise is trying to measure rather than the case it should call a
    miss.
    """
    key = str(label.get("finding_key") or "")
    text = _row_text(row)
    if key and key in normalize(text):
        return True
    entity = str(label.get("entity_id") or "").strip()
    return bool(entity) and entity in text


def score_checks(entry: dict, result: dict) -> dict:
    """One `checks` entry against what `checks.run_all` filed.

    A house whose labels are empty is the clean fixture, and the score for
    it is *everything reported is extra* — which is exactly right: on a
    healthy house every row is a false positive, and precision falls to
    zero the moment one appears.
    """
    labels = entry.get("labels") or []
    rows = result.get("findings") or []
    out = scoring.score(labels, rows, check_match)
    out["skipped"] = dict(result.get("skipped") or {})
    out["errors"] = dict(result.get("errors") or {})
    out["ran"] = list(result.get("ran") or [])
    return out


def score_analyst(entry: dict, reported: list) -> dict:
    """One `analyst` entry against what a model actually reported.

    The labels split in two before any arithmetic. Confirmed labels are
    what the producer *should* say, so recall is over those. Denied labels
    are what it should NOT say, and reporting one is counted as a false
    positive on top of whatever else was extra — a miss and a wrong report
    are different failures and only precision can tell them apart.
    """
    labels = entry.get("labels") or []
    confirmed = [row for row in labels if row.get("verb") in CONFIRMED]
    denied = [row for row in labels if row.get("verb") in DENIED]

    hits = scoring.score(confirmed, list(reported or []), analyst_match)
    # A row that answers a `wrong` label is a repeat of a report this
    # house has already said is not a problem. It is not merely extra: it
    # is the specific mistake the corpus exists to catch, so it is named.
    repeats = scoring.score(denied, hits["extra_rows"], analyst_match)
    return {
        **scoring.tally(hits["found"], len(confirmed),
                        len(hits["extra_rows"])),
        "rows": hits["rows"],
        "extra_rows": hits["extra_rows"],
        "repeated_corrections": repeats["found"],
        "repeated_rows": [r["label"] for r in repeats["rows"]
                          if r["verdict"] == "found"],
        "denied_labels": len(denied),
    }


def summarise(scored: list[dict]) -> dict:
    """Totals over several entries — the one screen a replay prints.

    Summed from the counts rather than averaged from the rates: a mean of
    per-entry precisions weights a house with two findings the same as one
    with forty, which is a number that moves for the wrong reason.
    """
    found = sum(s.get("found", 0) for s in scored)
    planted = sum(s.get("planted", 0) for s in scored)
    extra = sum(s.get("extra", 0) for s in scored)
    return {**scoring.tally(found, planted, extra),
            "entries": len(scored)}
