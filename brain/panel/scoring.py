"""Precision and recall against labels — one implementation, three callers.

Three things in this add-on grade a producer against a set of expected
answers, and all three were about to write the same arithmetic:

  * ``rehearsal.py`` scores the checks and the analyst against defects it
    planted, on a real house;
  * ``tests/corpus/replay.py`` scores the same producers against
    contributed houses whose labels are somebody's endings;
  * ``tests/test_corpus.py`` scores the deterministic half of that in
    ordinary CI, which is what fails when a check's floor moves.

"Precision against labels" having two answers is exactly the kind of
drift `_CARD_CONTRACT` is shared to avoid, so it has one. It lives in
``panel/`` rather than under ``tests/`` for the reason that decides every
such placement here: ``rehearsal.py`` ships inside the add-on and cannot
import from the test tree, while the test tree already puts ``panel/`` on
its path.

Two functions, and the split matters. :func:`tally` is the arithmetic
alone — hand it three counts and it answers. :func:`score` is the walk:
hand it what was expected, what was reported, and how to tell whether one
answers the other, and it says which were found, which were missed and
what else was said. The match predicate is the caller's because it is the
only part that differs: a rehearsal matches a planted id inside a
sentence, a corpus entry matches a normalised finding key, and a check
entry matches a check id on the row's source.

**A denominator of nothing is nothing, not one.** Both rates answer 0.0
when there is nothing to divide by, which reads correctly everywhere it
is rendered ("0 of 0") and would read as a perfect score if it answered
1.0 — the shape of a number nobody should trust that looks like the best
possible one.

Stdlib only.
"""
from __future__ import annotations


def tally(found: int, planted: int, extra: int) -> dict:
    """Precision and recall from three counts.

    ``found`` of ``planted`` expected answers were reported, and ``extra``
    things were reported that no label accounts for. Recall is found over
    planted; precision is found over everything reported *about the things
    being scored*, which is found plus extra.
    """
    found = max(0, int(found))
    planted = max(0, int(planted))
    extra = max(0, int(extra))
    reported = found + extra
    return {
        "planted": planted,
        "found": found,
        "extra": extra,
        "missed": max(0, planted - found),
        "recall": round(found / planted, 3) if planted else 0.0,
        "precision": round(found / reported, 3) if reported else 0.0,
    }


def score(expected: list, reported: list, match) -> dict:
    """Walk one producer's answers against the labels for them.

    ``expected`` is whatever the caller's labels are; ``reported`` is
    whatever the producer said; ``match(label, row)`` says whether that row
    answers that label.

    Returns :func:`tally`'s numbers plus ``rows`` (one verdict per label,
    in the order the labels were given) and ``extra_rows`` (what was
    reported that no label claims). A row that answers two labels counts
    for both and is extra to neither — one finding legitimately covering
    two expectations is not a false positive, and treating it as one would
    make a good report score worse than a vague one.
    """
    matched: set[int] = set()
    rows = []
    for label in expected:
        hits = [i for i, row in enumerate(reported) if match(label, row)]
        matched.update(hits)
        rows.append({
            "label": label,
            "verdict": "found" if hits else "missed",
            "reported": [reported[i] for i in hits],
        })
    extra_rows = [row for i, row in enumerate(reported) if i not in matched]
    found = sum(1 for r in rows if r["verdict"] == "found")
    return {
        **tally(found, len(expected), len(extra_rows)),
        "rows": rows,
        "extra_rows": extra_rows,
    }
