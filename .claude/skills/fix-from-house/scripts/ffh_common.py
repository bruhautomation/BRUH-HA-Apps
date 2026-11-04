"""What every fix-from-house helper shares: the signed blocks, the evidence rule.

The house writes machine-readable parts of its issues and comments as fenced
JSON blocks (```json brain-devloop```, ```json brain-canary```,
```json brain-held```, ```json brain-after```). A block counts only when

- it is valid JSON, an object, with ``"v": 1``;
- its ``digest`` is the sha256 of the object without ``digest``, serialised
  as ``json.dumps(obj, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)`` and encoded utf-8;
- the issue or comment that carries it was written by the house's login,
  ``house_login`` in ``.claude/devloop.json``.

The digest is integrity, not a secret: the author check is what says the
house wrote it. A block that fails either is *unverified*, and an unverified
block is never a task.

Standard library only, so the cloud run can call it with nothing installed.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

HEX64 = re.compile(r"^[0-9a-f]{64}$")

MODEL_TIERS = ("haiku", "sonnet", "opus", "fable")

# The highest tier an automatic escalation may name. Fable is a press, not a
# rung: it costs far more of the account's usage than Opus, so no script ever
# hands it out. The run may spend its one Fable attempt by hand, under the
# skill's Fable rule (*Choosing a model*), and nowhere else.
AUTO_CEILING = "opus"


def canonical(obj: dict) -> str:
    body = {k: v for k, v in obj.items() if k != "digest"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def digest_of(obj: dict) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def sign(obj: dict) -> dict:
    """The object with its digest set (what the house does; tests use it)."""
    out = dict(obj)
    out["digest"] = digest_of(obj)
    return out


def fence(obj: dict, tag: str) -> str:
    return f"```json {tag}\n{json.dumps(obj, ensure_ascii=False)}\n```"


def find_blocks(text: str | None, tag: str) -> list[str]:
    """The raw contents of every ```json <tag>``` block in ``text``."""
    if not text:
        return []
    pattern = re.compile(
        r"^[ \t]*```json[ \t]+" + re.escape(tag) + r"[ \t]*\r?\n(.*?)\r?\n[ \t]*```",
        re.DOTALL | re.MULTILINE)
    return [m.group(1) for m in pattern.finditer(text)]


def same_login(a: str | None, b: str | None) -> bool:
    """GitHub logins compare without case; an empty one never matches."""
    return bool(a) and bool(b) and a.strip().casefold() == b.strip().casefold()


def author_of(item: dict) -> str | None:
    """The login of an issue or comment as the GitHub API (or our own
    simplified shape, ``author``) gives it."""
    if isinstance(item.get("author"), str):
        return item["author"]
    user = item.get("user") or item.get("author") or {}
    if isinstance(user, dict):
        return user.get("login")
    return None


def verify_block(raw: str, author: str | None, house_login: str | None,
                 required: dict[str, Any] | None = None) -> tuple[dict | None, str]:
    """(object, "ok") when the block is the house's, else (None, why).

    ``required`` maps a field to the type (or tuple of types) it must have;
    ``None`` in a tuple allows null.
    """
    if not house_login:
        return None, "house_login is not configured"
    if not same_login(author, house_login):
        return None, f"written by {author or 'nobody'}, not the house"
    try:
        obj = json.loads(raw)
    except ValueError as exc:
        return None, f"not JSON ({exc.msg})"
    if not isinstance(obj, dict):
        return None, "not a JSON object"
    if obj.get("v") != 1:
        return None, "unknown version"
    dig = obj.get("digest")
    if not isinstance(dig, str) or not HEX64.match(dig):
        return None, "no digest"
    if dig != digest_of(obj):
        return None, "digest does not match"
    for field, kind in (required or {}).items():
        if field not in obj:
            return None, f"missing {field}"
        kinds = kind if isinstance(kind, tuple) else (kind,)
        value = obj[field]
        ok = any((k is None and value is None)
                 or (k is not None and isinstance(value, k)
                     and not (k is int and isinstance(value, bool)))
                 for k in kinds)
        if not ok:
            return None, f"{field} has the wrong type"
    return obj, "ok"


def one_verified(text: str | None, tag: str, author: str | None,
                 house_login: str | None,
                 required: dict[str, Any] | None = None) -> tuple[dict | None, str]:
    """Exactly one block of ``tag`` in ``text``, verified. Two are ambiguous,
    and ambiguity is unverified."""
    raws = find_blocks(text, tag)
    if not raws:
        return None, "no block"
    if len(raws) > 1:
        return None, "more than one block"
    return verify_block(raws[0], author, house_login, required)


def load_config(path: str | Path | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_json(path: str) -> Any:
    if path == "-":
        import sys
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def next_model(model: str | None) -> str | None:
    """One tier up (sonnet → opus → fable); None above fable."""
    name = (model or "sonnet").lower()
    for i, tier in enumerate(MODEL_TIERS):
        if tier in name:
            return MODEL_TIERS[i + 1] if i + 1 < len(MODEL_TIERS) else None
    return "opus"


def escalate_model(model: str | None) -> str | None:
    """One tier up for an automatic retry, never past AUTO_CEILING.

    sonnet → opus; opus (or fable) → None, which means "the ladder is spent":
    the caller declines the issue with a plan rather than reaching for Fable.
    """
    up = next_model(model)
    if up is None or model_rank(up) > model_rank(AUTO_CEILING):
        return None
    return up


def model_rank(model: str | None) -> int:
    name = (model or "").lower()
    for i, tier in enumerate(MODEL_TIERS):
        if tier in name:
            return i
    return -1


# ---------------------------------------------------------------------------
# Evidence: what a declined or duplicate closure must cite.
# ---------------------------------------------------------------------------

_ISSUE_REF = re.compile(r"(?<![\w&])#\d+\b")
_GH_LINK = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/\d+")
_PATH_LINE = re.compile(r"(?<![\w/])(?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9]{1,6}:\d+\b")
_RELEASE = re.compile(r"\b\d+\.\d+\.\d+\b")
_TEST_PATH = re.compile(r"\btests/[\w./-]+\.(?:py|mjs|js)\b")


def evidence_kinds(text: str | None) -> list[str]:
    """Which kinds of evidence ``text`` cites (empty: none)."""
    text = text or ""
    kinds = []
    if _ISSUE_REF.search(text) or _GH_LINK.search(text):
        kinds.append("link")
    if _PATH_LINE.search(text):
        kinds.append("path:line")
    if _RELEASE.search(text) and _TEST_PATH.search(text):
        kinds.append("release+test")
    return kinds


def has_evidence(text: str | None) -> bool:
    return bool(evidence_kinds(text))
