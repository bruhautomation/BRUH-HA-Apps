"""What `sensor.bruh_browser_status` and `binary_sensor.bruh_browser_waiting_on_you`
read, with no Home Assistant import.

BRUH Browser has no integration of its own; brAIn's calls its errand list
(`GET /api/tasks`, the bearer token in `/config/.bruh_browser/api_token`,
the same token and route brAIn's `browser_status` tool uses) and turns the
rows into one word and four facts. Read-only: nothing here starts, answers,
approves or stops an errand.

**Only a status, a time, a count and a yes/no leave this module.** An
errand's words, its cart, its report, the question it is waiting on and
every address are never copied into an attribute: they are the household's
shopping, and a state attribute is readable by every dashboard and log.

States: `needs_you` when any errand waits on a person, else `running`
(running or queued), else the latest finished errand's `done` or `failed`
(a stopped one is `idle`: the person ended it), else `idle`. `unknown`
with a `reason` when the add-on cannot be asked, never the last answer.
"""
from __future__ import annotations

from datetime import datetime, timezone

STATES = ("idle", "running", "needs_you", "done", "failed", "unknown")
BROWSER_SLUG = "bruh-browser"
BROWSER_NAME = "BRUH Browser"
BROWSER_PORT = 8105
TOKEN_DIR = ".bruh_browser"
TOKEN_FILENAME = "api_token"
FINISHED = ("done", "failed", "stopped")


def is_browser_addon(row: dict) -> bool:
    slug = str(row.get("slug") or "")
    name = str(row.get("name") or "").strip().lower()
    return ((slug == BROWSER_SLUG or slug.endswith("_" + BROWSER_SLUG))
            and (not name or name == BROWSER_NAME.lower()))


def base_url(addons: dict | None) -> tuple[str | None, str]:
    """`(the add-on's base URL, "")` or `(None, why)` from Home Assistant's
    list of add-ons (slug -> info)."""
    rows = [r for r in (addons or {}).values() if isinstance(r, dict)]
    row = next((r for r in rows if is_browser_addon(r)), None)
    if row is None:
        return None, "BRUH Browser is not installed"
    if row.get("state") != "started":
        return None, "BRUH Browser is not running"
    host = str(row.get("hostname") or row["slug"]).replace("_", "-")
    return f"http://{host}:{BROWSER_PORT}", ""


def _iso(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def derive(rows) -> tuple[str, dict]:
    """`(state, attributes)` from the errand list. Never raises."""
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    active = [r for r in rows if r.get("state") in ("running", "queued")]
    waiting = [r for r in rows if r.get("state") == "needs_you"]
    done = [r for r in rows if r.get("state") in FINISHED]
    last = max(done, key=lambda r: r.get("finished_at") or 0, default=None)
    if waiting:
        state = "needs_you"
    elif active:
        state = "running"
    elif last and last.get("state") in ("done", "failed"):
        state = last["state"]
    else:
        state = "idle"
    steps = last.get("steps") if last else None
    attrs = {
        "waiting_on_you": bool(waiting),
        "errands_waiting_on_you": len(waiting),
        "errands_running": len(active),
        "last_result": last.get("state") if last else None,
        "last_finished_at": _iso(last.get("finished_at")) if last else None,
        "last_steps": steps if isinstance(steps, int)
        and not isinstance(steps, bool) and steps >= 0 else None,
        "last_bought": bool(last and last.get("purchase")
                            and last.get("state") == "done"
                            and last.get("order_placed") is True) if last else None,
    }
    return state, attrs


def unknown(reason: str) -> tuple[str, dict]:
    return "unknown", {"reason": reason, "waiting_on_you": None,
                       "errands_waiting_on_you": None, "errands_running": None,
                       "last_result": None, "last_finished_at": None,
                       "last_steps": None, "last_bought": None}


__all__ = ["STATES", "base_url", "derive", "unknown"]
