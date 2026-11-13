#!/usr/bin/env python3
"""The spending guard: a Claude Code hook on the Claude in Chrome tools.

Wired by `runner.settings_file` into every errand's `--settings`, as a
PreToolUse hook (`pre`) and a PostToolUse hook (`post`) on
`mcp__claude-in-chrome__.*`. The runner tells it whether THIS errand may buy
(`BROWSER_PURCHASE_APPROVED=1`, set only for a purchase task the panel
approved: `tasks.check_approval`) and where its notes live
(`BROWSER_TASK_STATE`). The model cannot change either: it has no shell.

**For an errand without purchase approval it refuses a call that clearly
places an order or pays**, with the reason handed back to the model:

* `pre` reads the tool's input as text and refuses one that names an
  order-placing or paying control ("place order", "buy now", "pay $42",
  "complete purchase" and the like, matched with spacing and punctuation
  folded so "Place your order" and "placeYourOrder" are one), and a click on
  an element reference the page earlier labelled that way;
* `post` reads what a page-reading tool returned (`find`, `read_page`) and
  remembers the references (`ref_12`) of elements whose line carries one of
  those labels, so a later click by reference is refused even though the
  click's own input says nothing but `ref_12`.

**This is a net, not a guarantee, and every page that documents it says
so.** A click by screen coordinates names no element, a keyboard Enter on a
focused button names nothing, and a site can label its order button any way
it likes. What makes a purchase need a person is upstream of this file: the
panel refuses `purchase: true` without an approval it can check, and brAIn
asks a person before it asks for one. This catches the model reaching for
the button anyway.

For an approved purchase it does nothing. It never prints `allow` (an allow
from a hook would bypass the run's permission rules); an allowed call is
this script printing nothing. A crash on an unapproved errand refuses the
call (the one direction a broken guard may fail); on an approved one it
lets it through.
"""
from __future__ import annotations

import json
import os
import re
import sys

CHROME_PREFIX = "mcp__claude-in-chrome__"

# Order-placing and paying controls, as their words run together once case,
# spaces and punctuation are folded away.
PHRASES = (
    "placeorder", "placeyourorder", "placemyorder", "placetheorder",
    "submitorder", "submityourorder", "submitpayment",
    "confirmorder", "confirmyourorder", "confirmandpay", "confirmpurchase",
    "confirmpayment", "completepurchase", "completeorder", "completeyourorder",
    "completecheckout", "completepayment", "payandplaceorder",
    "buynow", "buyitnow", "buywith1click", "1clickbuy", "oneclickbuy",
    "ordernow", "paynow", "makepayment", "authorizepayment", "authorisepayment",
)
# "Pay $54.20", "Pay £12", "pay EUR 9".
PAY_AMOUNT = re.compile(r"\bpay\s*(?:[$£€]|usd|gbp|eur|cad|aud)\s*\d", re.I)
REF = re.compile(r"\bref_\d+\b")
MAX_REFS = 200


def fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def order_words(text: str) -> str | None:
    """The order-placing phrase this text carries, or None."""
    folded = fold(text)
    for phrase in PHRASES:
        if phrase in folded:
            return phrase
    match = PAY_AMOUNT.search(str(text))
    return match.group(0) if match else None


def _strings(value, out: list[str]) -> list[str]:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            _strings(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _strings(item, out)
    return out


def approved() -> bool:
    return os.environ.get("BROWSER_PURCHASE_APPROVED", "") == "1"


def _state_path() -> str:
    return os.environ.get("BROWSER_TASK_STATE", "")


def load_refs() -> set[str]:
    path = _state_path()
    if not path:
        return set()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(r) for r in data.get("order_refs") or []}
    except (OSError, ValueError, AttributeError):
        return set()


def save_refs(refs: set[str]) -> None:
    path = _state_path()
    if not path:
        return
    scratch = f"{path}.{os.getpid()}.tmp"
    with open(scratch, "w", encoding="utf-8") as handle:
        json.dump({"order_refs": sorted(refs)[-MAX_REFS:]}, handle)
    os.replace(scratch, path)


def deny(reason: str) -> int:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason[:600],
    }}))
    return 0


def refusal(what: str) -> str:
    return (f"BRUH Browser's spending guard: this looks like it places an order or "
            f"pays (\"{what}\"), and this errand has no purchase approval. Do not "
            "place the order. Stop on the review page and report the cart — every "
            "item, quantity, price, fee and the total — and brAIn will ask the "
            "household to approve the purchase.")


def pre(payload: dict) -> int:
    tool = str(payload.get("tool_name") or "")
    if not tool.startswith(CHROME_PREFIX):
        return 0
    tool_input = payload.get("tool_input")
    texts = _strings(tool_input, [])
    for text in texts:
        found = order_words(text)
        if found:
            return deny(refusal(found))
    marked = load_refs()
    if marked:
        for text in texts:
            for ref in REF.findall(text):
                if ref in marked:
                    return deny(refusal(f"the element {ref}, labelled as an order or "
                                        "payment button on this page"))
    return 0


def post(payload: dict) -> int:
    tool = str(payload.get("tool_name") or "")
    if not tool.startswith(CHROME_PREFIX):
        return 0
    found: set[str] = set()
    for text in _strings(payload.get("tool_response"), []):
        for line in text.splitlines():
            if REF.search(line) and order_words(line):
                found.update(REF.findall(line))
    if found:
        save_refs(load_refs() | found)
    return 0


def main(argv: list[str], stdin=None) -> int:
    mode = argv[1] if len(argv) > 1 else "pre"
    if approved():
        return 0
    try:
        payload = json.load(stdin or sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("not an object")
        return post(payload) if mode == "post" else pre(payload)
    except Exception as exc:  # noqa: BLE001 — a broken guard refuses, never allows
        if mode == "post":
            return 0
        return deny("BRUH Browser's spending guard could not read this call "
                    f"({type(exc).__name__}), and this errand has no purchase "
                    "approval, so it is refused.")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
