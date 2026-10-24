"""How long a person's words may be on the routes that hand them to brAIn's
queue, and what happens when they are longer. Pure (no Home Assistant import),
so a test can read it.

brAIn keeps at most ``BRAIN_TEXT_MAX`` characters of an Ask line or a reply
(``morph_bridge.ASK_TEXT_MAX``, ``finding_requests.MORPH_TEXT_MAX``). These
routes used to slice at 500 and send the rest to nobody, so the end of what
somebody wrote was gone with nothing on screen saying so. A longer Ask line is
a conversation, which takes the words whole (the service's ``converse``); a
longer reply is refused with a sentence. Neither is cut.
"""
from __future__ import annotations

BRAIN_TEXT_MAX = 1000


def too_long(text: str) -> bool:
    return len(text) > BRAIN_TEXT_MAX


def reply_refusal(text: str) -> str:
    """The sentence for a reply brAIn's queue would not keep whole, or ""."""
    if not too_long(text):
        return ""
    return (f"That is {len(text)} characters, and a reply to brAIn holds {BRAIN_TEXT_MAX}. "
            "Ask it in the Ask line instead, which takes it whole.")
