#!/usr/bin/env python3
"""Build one design script: load it, validate it, export it.

    python build.py design.py OUTDIR

Run by the panel in a separate process with a stripped environment and a
time limit (panel/design/runner.py), under the CAD venv's Python. Writes
OUTDIR/report.json always — the panel reads it whether or not the build
worked — and exits 0 (built, perhaps with warnings), 2 (a blocking problem:
an invalid solid or bodies that overlap) or 1 (the script did not run).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PLA_DENSITY = 1.24  # g/cm³, for an estimate of filament weight


def _write(outdir: str, report: dict) -> None:
    with open(os.path.join(outdir, "report.json"), "w") as handle:
        json.dump(report, handle, indent=1)


def main(script: str, outdir: str) -> int:
    os.makedirs(outdir, exist_ok=True)
    report = {"ok": False, "stage": "load", "error": "", "warnings": [], "blocking": []}
    try:
        spec = importlib.util.spec_from_file_location("design", script)
        design = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(design)
        parts = getattr(design, "PARTS", None)
        if not isinstance(parts, dict) or not parts:
            raise ValueError("The script must define PARTS = {\"BodyName\": workplane, ...}.")
        name = str(getattr(design, "NAME", "part")).strip().replace(" ", "_") or "part"
        report.update(name=name, title=str(getattr(design, "TITLE", "") or name),
                      material=str(getattr(design, "MATERIAL", "") or ""),
                      notes=[str(n) for n in getattr(design, "NOTES", [])][:8],
                      dims=getattr(design, "DIMS", None) if isinstance(
                          getattr(design, "DIMS", None), (list, dict)) else None,
                      colors=getattr(design, "COLORS", None) if isinstance(
                          getattr(design, "COLORS", None), dict) else None)
        import cadkit

        report["stage"] = "validate"
        check = cadkit.validate(parts)
        report.update(bodies=check["bodies"], pairs=check["pairs"],
                      warnings=check["warnings"], blocking=check["blocking"])
        boxes = [b["bbox"] for b in check["bodies"].values()]
        if boxes:
            lo = [min(b[i] for b in boxes) for i in range(3)]
            hi = [max(b[i + 3] for b in boxes) for i in range(3)]
            report["size_mm"] = [round(hi[i] - lo[i], 2) for i in range(3)]
        volume = sum(b["volume_mm3"] for b in check["bodies"].values())
        report["volume_mm3"] = round(volume, 1)
        report["grams_pla"] = round(volume / 1000 * PLA_DENSITY, 1)
        if check["blocking"]:
            _write(outdir, report)
            return 2
        report["stage"] = "export"
        report["files"] = cadkit.export_all(parts, name, outdir)
        report["ok"] = True
        report["stage"] = "done"
        _write(outdir, report)
        return 0
    except Exception as exc:  # noqa: BLE001 - every failure is reported, with its traceback
        # Only the design script's own frames: those are the lines brAIn
        # can change, and importlib's and OpenCascade's are noise to it.
        frames = [f for f in traceback.extract_tb(exc.__traceback__)
                  if os.path.abspath(f.filename) == os.path.abspath(script)]
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = [f"design.py line {f.lineno}: {(f.line or '').strip()}"
                               for f in frames[-6:]]
        _write(outdir, report)
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(64)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
