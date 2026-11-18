#!/usr/bin/env python3
"""The UI ratchet: a stylesheet may use fewer distinct sizes, never more.

    python3 .github/scripts/ui_ratchet.py            # check against the baseline
    python3 .github/scripts/ui_ratchet.py --report   # a table of the counts now
    python3 .github/scripts/ui_ratchet.py --update   # lower (or reset) the baseline

Per stylesheet it counts four things (docs/notes/ui-standard.md):

  space   distinct px values in padding/margin/gap not in 0 1 2 4 8 12 16 20 24 32 48
  radius  distinct border-radius values not in 0 8 12 999px
  font    distinct font-size values not in 12 14 16 20px
  media   distinct media-query widths not in 640 900 1200px (639.98 etc. count as them)

Only off-standard values are counted, so adopting a standard value can never
fail the check. It fails when a count is higher than `ui_baseline.json` records. The block
a stylesheet carries between the ui-tokens markers is not counted: it is the
standard itself. Standard library only, so it adds nothing to the check.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ui_tokens import ROOT, STYLESHEETS
from ui_tokens import check as token_problems

BASELINE = Path(__file__).resolve().parent / "ui_baseline.json"
METRICS = ("space", "radius", "font", "media")
SCALE = {0, 1, 2, 4, 8, 12, 16, 20, 24, 32, 48}
RADII = {0, 8, 12, 999}
FONTS = {12, 14, 16, 20}
WIDTHS = {640, 900, 1200}
UPDATE = "python3 .github/scripts/ui_ratchet.py --update"

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_TOKENS = re.compile(r"/\* ui-tokens:start.*?ui-tokens:end \*/", re.S)
_LENGTH = re.compile(r"(?<![\w.-])(-?\d*\.?\d+)(px|rem|em)\b")
_MEDIA = re.compile(r"@media([^{]*)\{")
_WIDTH = re.compile(r"(?:(?:max|min)-width\s*:\s*|width\s*[<>]=?\s*)([\d.]+)(px|em|rem)")


def _number(raw: str) -> str:
    return f"{abs(float(raw)):g}"


def _values(text: str, prop: str, unit_ok: tuple[str, ...]) -> set[str]:
    found = set()
    for match in re.finditer(r"(?<![\w-])" + prop + r"\s*:\s*([^;}{]+)", text):
        for number, unit in _LENGTH.findall(match.group(1)):
            if unit in unit_ok and float(number) != 0:
                found.add(_number(number) + unit)
    return found


def count(text: str) -> dict[str, list[str]]:
    """The four metrics of one stylesheet's text, each a sorted list of values."""
    text = _COMMENT.sub("", _TOKENS.sub("", text))
    space = _values(
        text, r"(?:padding|margin|gap|row-gap|column-gap)"
        r"(?:-(?:top|right|bottom|left|inline|block)(?:-(?:start|end))?)?", ("px",))
    media = {_number(n) + u for prelude in _MEDIA.findall(text)
             for n, u in _WIDTH.findall(prelude)}

    def off(values, ok, pill=False):
        """The values that are not standard: a standard one is px and in `ok`."""
        keep = set()
        for v in values:
            n = float(re.sub(r"[a-z]+$", "", v))
            if not (v.endswith("px") and (round(n) in ok or (pill and n >= 999))):
                keep.add(v)
        return keep

    out = {
        "space": {v for v in space if float(v[:-2]) not in SCALE},
        "radius": off(_values(text, r"border(?:-[a-z]+)*-radius", ("px", "rem", "em")), RADII, True),
        "font": off(_values(text, "font-size", ("px", "rem", "em")), FONTS),
        "media": off(media, WIDTHS),
    }
    return {k: sorted(v, key=lambda s: (float(re.sub(r"[a-z]+$", "", s)), s))
            for k, v in out.items()}


def measure() -> dict[str, dict[str, list[str]]]:
    return {rel: count((ROOT / rel).read_text())
            for rel in STYLESHEETS if (ROOT / rel).exists()}


def _baseline() -> dict:
    try:
        return json.loads(BASELINE.read_text())
    except (OSError, ValueError):
        return {}


def check() -> tuple[list[str], list[str]]:
    """(problems, hints). Problems fail the check; hints are counts that fell."""
    problems, hints = list(token_problems()), []
    base, now = _baseline(), measure()
    for rel, metrics in now.items():
        if rel not in base:
            problems.append(f"{rel}: no ratchet baseline recorded; run `{UPDATE}`")
            continue
        for metric in METRICS:
            old, new = base[rel].get(metric, []), metrics[metric]
            if len(new) > len(old):
                added = [v for v in new if v not in old]
                problems.append(
                    f"{rel}: {metric} went from {len(old)} to {len(new)} distinct off-standard values "
                    f"(new: {', '.join(added)}). Use the standard's token instead "
                    f"(docs/notes/ui-standard.md): "
                    + {"space": "var(--sp-N) from the 4 8 12 16 20 24 32 48 scale",
                       "radius": "var(--card-radius), var(--control-radius) or 999px",
                       "font": "var(--fs-title/card/body/meta)",
                       "media": "only 640, 900 and 1200"}[metric] + ".")
            elif len(new) < len(old):
                hints.append(f"{rel}: {metric} fell from {len(old)} to {len(new)}")
    if hints:
        hints = [f"UI ratchet: {len(hints)} count(s) went down; lock it in with `{UPDATE}`"]
    return problems, hints


def update() -> None:
    data = {rel: {m: metrics[m] for m in METRICS} for rel, metrics in measure().items()}
    BASELINE.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def report() -> str:
    base, now = _baseline(), measure()
    rows = [("stylesheet", *METRICS)]
    for rel, metrics in now.items():
        cells = []
        for metric in METRICS:
            old = base.get(rel, {}).get(metric)
            cells.append(f"{len(metrics[metric])}" + ("" if old is None else f" (base {len(old)})"))
        rows.append((rel, *cells))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)


def main() -> int:
    args = sys.argv[1:]
    if "--update" in args:
        update()
        print(f"wrote {BASELINE.relative_to(ROOT)}")
        return 0
    if "--report" in args:
        print(report())
        return 0
    problems, hints = check()
    print("\n".join(problems + hints) or "ui ratchet holds")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
