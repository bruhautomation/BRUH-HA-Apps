"""Real houses' failures as corpus entries: the `corpus` stream (plan 1.7).

The corpus (`tests/corpus/`) grades the first look against frozen houses,
and it had two fixtures and one entry. The houses that run brAIn already
hold the cases that matter: with capture on, every first look is kept with
the batch it judged and the inputs its prompt was built from, and the
nightly outcomes join labels each signal by what the household did next
(`capture.label_first_look`, `outcomes.look_labels`). A look that called a
signal nothing and the house then confirmed it (``missed``), or raised one
somebody marked Wrong (``wrong``), is a regression case nobody had to
write.

So this stream, off by default and only while capture is on, files each
such capture as ONE issue carrying a ``brain-corpus`` block: a corpus
entry that `tests/corpus/schema.json` accepts (kind ``first_look``, only
the labels that say what went wrong), every string scrubbed and aliased as
everything else the loop sends. The cloud adds it to `tests/corpus/entries`
frozen. One issue per capture, keyed on its run id, under the loop's own
review setting, caps and redaction.

A capture is already redacted on the way in (`capture.redact`); the
aliases and `upstream.scrub` are applied once more when the block is
composed, like every issue body.
"""
from __future__ import annotations

import json

from . import blocks

# The outcomes a label must carry for its capture to be a case: the look
# was wrong about it, one way or the other.
CASE_OUTCOMES = frozenset({"wrong", "missed"})
MAX_ROWS = 5
# A body GitHub will take with the human half beside it; a capture whose
# entry will not fit even without its `inputs` is not filed.
MAX_ENTRY_CHARS = 45_000


def entry_for(capture_entry: dict) -> dict | None:
    """The corpus entry for one first-look capture, or None when it is not
    a case (no label says the look was wrong or missed something)."""
    if not isinstance(capture_entry, dict) or capture_entry.get("kind") != "first_look":
        return None
    labels = [lb for lb in capture_entry.get("labels") or []
              if isinstance(lb, dict) and lb.get("outcome") in CASE_OUTCOMES
              and (lb.get("floor") or lb.get("ceiling"))]
    batch = [b for b in capture_entry.get("batch") or [] if isinstance(b, dict)]
    run_id = str(capture_entry.get("run_id") or capture_entry.get("id") or "")
    if not labels or not batch or not run_id:
        return None
    labels = [lb for lb in labels if isinstance(lb.get("signal"), int)
              and 1 <= lb["signal"] <= len(batch)]
    if not labels:
        return None
    wrong = sum(1 for lb in labels if lb["outcome"] == "wrong")
    missed = len(labels) - wrong
    entry = {
        "schema": 1,
        "kind": "first_look",
        "id": f"house-{run_id}"[:128],
        "title": (f"A first look on a real house: {wrong} raised and marked Wrong, "
                  f"{missed} passed over and then confirmed"),
        "note": ("Filed by a house's development loop from a captured first look "
                 "whose household's endings disagreed with it. Frozen as found."),
        "captured_at": int(capture_entry.get("captured_at") or 0),
        "source": "house",
        "model": str(capture_entry.get("model") or ""),
        "now": float(capture_entry.get("now") or capture_entry.get("captured_at") or 0),
        "batch": batch,
        "inputs": capture_entry.get("inputs") if isinstance(capture_entry.get("inputs"), dict) else {},
        "labels": [{k: lb[k] for k in ("signal", "floor", "ceiling", "outcome") if k in lb}
                   for lb in labels],
    }
    if len(json.dumps(entry, ensure_ascii=False)) > MAX_ENTRY_CHARS:
        entry["inputs"] = {}
        if len(json.dumps(entry, ensure_ascii=False)) > MAX_ENTRY_CHARS:
            return None
    return entry


def rows(captures: list[dict], capture_on: bool) -> list[dict]:
    """The stream's rows from every first-look capture: nothing while
    capture is off (there would be nothing new to find, and the switch is
    the owner's word on what may be kept)."""
    if not capture_on:
        return []
    out = []
    for cap in sorted((c for c in captures or [] if isinstance(c, dict)),
                      key=lambda c: -int(c.get("captured_at") or 0)):
        entry = entry_for(cap)
        if entry is None:
            continue
        kinds = sorted({lb["outcome"] for lb in entry["labels"]})
        out.append({
            "key": f"corpus:{entry['id']}",
            "where": "Corpus: first look",
            "what": (f"A first look was {' and '.join(kinds)} on "
                     f"{len(entry['labels'])} of {len(entry['batch'])} signals"),
            "detail": "",
            "body": ("A candidate regression case for `tests/corpus/entries/`: the "
                     "household's endings disagreed with what brAIn's first look "
                     "decided. Add the block below as one entry, frozen."),
            "corpus": entry,
        })
        if len(out) >= MAX_ROWS:
            break
    return out


def _deep(value, clean):
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [_deep(v, clean) for v in value]
    if isinstance(value, dict):
        return {k: _deep(v, clean) for k, v in value.items()}
    return value


def block_object(entry: dict, clean) -> dict:
    """The entry with every string scrubbed and aliased, and ``v``; the
    block's digest is added by `blocks.make_block`. A schema-valid corpus
    entry (the schema allows the two extra keys)."""
    obj = _deep(dict(entry), clean)
    # The id is a filename: aliasing must not have made it one it is not.
    obj["id"] = entry["id"]
    obj["v"] = 1
    return obj


def block(entry: dict, clean) -> str:
    return blocks.make_block("corpus", block_object(entry, clean))
