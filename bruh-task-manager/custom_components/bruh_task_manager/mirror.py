"""Read the add-on's state mirror and decide whether it is still current.

Pure (no Home Assistant import) so a test can drive it in any checkout.

Freshness is judged by the FILE's modification time against the window the
file itself publishes (`stale_after_s`), not by the `generated_at` stamp
inside it: a clock corrected after the stamp was written would leave a stamp
in the future, and a reading that can never go stale is a reading nothing can
correct. A stale or missing file is reported with a reason, never served as
the last good answer — "the add-on stopped measuring" must not read as
"nothing is running hot".
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

DEFAULT_STALE_S = 120


def read(path: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    try:
        stat = os.stat(path)
        with open(path) as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"available": False,
                "reason": "The BRUH Task Manager add-on has not started yet."}
    except (OSError, ValueError) as exc:
        return {"available": False, "reason": f"Could not read {path}: {exc}"}
    if not isinstance(data, dict):
        return {"available": False, "reason": f"{path} is not a JSON object."}
    window = data.get("stale_after_s")
    if not isinstance(window, (int, float)) or window <= 0:
        window = DEFAULT_STALE_S
    age = now - stat.st_mtime
    if age > window:
        return {"available": False,
                "reason": f"The add-on has not measured for {int(age // 60)} min; "
                          "it may be stopped."}
    data["available"] = True
    return data
