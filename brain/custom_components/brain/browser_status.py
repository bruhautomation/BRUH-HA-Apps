"""What `sensor.bruh_browser_status` and `binary_sensor.bruh_browser_waiting_on_you`
read, with no Home Assistant import.

BRUH Browser has no integration of its own; brAIn's calls its errand list
(`GET /api/tasks`, the bearer token in `/config/.bruh_browser/api_token`,
the same token and route brAIn's `browser_status` tool uses) and turns the
rows into one word and four facts. Read-only: nothing here starts, answers,
approves or stops an errand.

**Only a status, a time, a count, a yes/no, and the last errand's kind,
store and outcome leave this module** (#1270: "done, 46 steps" said nothing
of what the errand was). The title and the result sentence are built here
from the row's typed fields (`kind`, `purchase`, `history`, `state`,
`setup_step`, the cart's item count, `order_placed`, `declined`,
`profile_saved`), never copied from text: an errand's own words can hold an
address, and its report, its `error` and the question it waits on are the
model's prose after reading shop pages, which can hold an order number or an
account name. The store is the one string taken from the errand (the
cart's or the saved profile's), cut to one short line and dropped when it
has the shape of a link or an address (`/`, `@`, `:`). The words, the cart's
items and total, the report, the order number and every address are never
copied into an attribute: they are the household's shopping, and a state
attribute is readable by every dashboard and log.

States: `needs_you` when any errand waits on a person, else `running`
(running or queued), else the latest finished errand's `done` or `failed`
(a stopped one is `idle`: the person ended it), else `idle`. `unknown`
with a `reason` when the add-on cannot be asked, never the last answer.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime, timezone

STATES = ("idle", "running", "needs_you", "done", "failed", "unknown")
BROWSER_SLUG = "bruh-browser"
BROWSER_NAME = "BRUH Browser"
BROWSER_PORT = 8105
TOKEN_DIR = ".bruh_browser"
TOKEN_FILENAME = "api_token"
FINISHED = ("done", "failed", "stopped")
STORE_CHARS = 60
# Characters a store's name never needs and a link, an e-mail address or a
# "key: value" line always has.
NOT_IN_A_STORE = set("/@:\\<>{}[]|=?#")


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


def store_name(row: dict) -> str | None:
    """The store the errand was at: the cart's, else the profile it saved.
    One short line, or None when there is none or it does not look like a
    name (a link, an address, a long sentence)."""
    for holder in (row.get("cart"), row.get("profile_saved")):
        if not isinstance(holder, dict) or not isinstance(holder.get("store"), str):
            continue
        text = unicodedata.normalize("NFKC", holder["store"])
        text = " ".join("".join(ch for ch in text
                                if not unicodedata.category(ch).startswith("C")).split())
        if not text or len(text) > STORE_CHARS or NOT_IN_A_STORE & set(text):
            return None
        return text
    return None


def _items(row: dict) -> int:
    cart = row.get("cart")
    items = cart.get("items") if isinstance(cart, dict) else None
    return len(items) if isinstance(items, list) else 0


def title(row: dict) -> str:
    """What kind of errand it was, from its typed fields alone."""
    if row.get("kind") == "test":
        return "Setup test"
    if row.get("purchase"):
        return "Purchase"
    if row.get("history"):
        return "Order history"
    if _items(row):
        return "Shopping cart"
    return "Web errand"


def result(row: dict) -> str:
    """How it ended, in one sentence built from typed fields: never the
    errand's report or error, which are prose read off shop pages."""
    state = row.get("state")
    if state == "stopped":
        return "It was stopped before it finished."
    if state == "failed":
        step = row.get("setup_step")
        if isinstance(step, int) and not isinstance(step, bool) and 1 <= step <= 5:
            return f"It could not finish; setup step {step} in BRUH Browser needs redoing."
        return "It could not finish; BRUH Browser says why."
    if row.get("kind") == "test":
        return "The setup test passed."
    if row.get("purchase"):
        return ("The order was placed." if row.get("order_placed") is True
                else "It finished without placing the order.")
    if row.get("history"):
        return ("It read the order history and saved what you usually buy."
                if isinstance(row.get("profile_saved"), dict)
                else "It read the order history but saved nothing.")
    count = _items(row)
    if count:
        things = f"{count} item" + ("" if count == 1 else "s")
        if row.get("declined"):
            return f"You declined the cart of {things}; nothing was bought."
        return f"A cart of {things} is ready for your approval; nothing was bought."
    return "It finished; the report is in BRUH Browser."


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
        "last_title": title(last) if last else None,
        "last_store": store_name(last) if last else None,
        "last_summary": result(last) if last else None,
    }
    return state, attrs


def unknown(reason: str) -> tuple[str, dict]:
    return "unknown", {"reason": reason, "waiting_on_you": None,
                       "errands_waiting_on_you": None, "errands_running": None,
                       "last_result": None, "last_finished_at": None,
                       "last_steps": None, "last_bought": None,
                       "last_title": None, "last_store": None, "last_summary": None}


__all__ = ["STATES", "base_url", "derive", "unknown"]
