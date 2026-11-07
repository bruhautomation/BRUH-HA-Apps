"""The machine half of everything the loop posts: one fenced JSON block.

An issue body was prose, and the cloud routine read it as prose — "data,
never instructions" said in a skill and kept by a model reading carefully
(plan item 3.2). Now every report the house files carries its facts as one
fenced block the cloud PARSES:

    ```json brain-devloop
    {"v":1,"fp":…,"stream":…,…,"digest":"<sha256 hex>"}
    ```

and every machine comment the house posts carries its own kind beside it
(`brain-canary`, `brain-held`, `brain-after`, `brain-corpus`). The human
text stays above it, for a person; the block is the contract.

Two rules hold for every kind.

**The digest is over the object without it**: the sha256 (utf-8) of
``json.dumps(obj_without_digest, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)``. It proves the block is whole — a body cut at
GitHub's size limit, or edited by hand, parses as a block whose digest is
wrong, and `parse_block` refuses it.

**Nothing in a block is raw**: the caller scrubs and aliases every string
BEFORE the block is built (`upstream.compose` hands it cleaned text), so
the block can say nothing the human half was not allowed to.

Pure and stdlib-only, so the cloud half's own copy of the rule can be held
against this one by a test.
"""
from __future__ import annotations

import hashlib
import json
import re

KINDS = ("devloop", "canary", "held", "after", "corpus")
VERSION = 1


def _kind(kind: str) -> str:
    """``devloop`` and ``brain-devloop`` name the same block."""
    name = str(kind or "").strip()
    name = name[len("brain-"):] if name.startswith("brain-") else name
    if name not in KINDS:
        raise ValueError(f"unknown block kind: {kind}")
    return name


def canonical(obj: dict) -> str:
    """The exact text the digest is taken over."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def digest(obj: dict) -> str:
    """sha256 hex of the canonical object, ``digest`` itself left out."""
    body = {k: v for k, v in (obj or {}).items() if k != "digest"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def seal(obj: dict) -> dict:
    """The object with ``v`` defaulted and its ``digest`` set."""
    out = {k: v for k, v in (obj or {}).items() if k != "digest"}
    out.setdefault("v", VERSION)
    out["digest"] = digest(out)
    return out


def make_block(kind: str, obj: dict) -> str:
    """The fenced block, ready to append to a body or a comment. The JSON
    is the canonical form plus its digest, on one line, so a reader and
    the digest agree on what was said."""
    name = _kind(kind)
    sealed = seal(obj)
    # A fence inside a value would end the block early. A backtick only
    # ever appears inside a JSON string, so it is written as the JSON
    # escape for itself: any JSON parser reads back the same string, and
    # the digest still checks without knowing this was done.
    text = canonical(sealed).replace("`", "\\u0060")
    # Held to what a reader does with it: the text parses back to the very
    # object that was sealed, or it is written all-ASCII, which any JSON
    # reader takes (the digest is over the object, not this spelling).
    try:
        whole = json.loads(text) == sealed
    except ValueError:
        whole = False
    if not whole:
        text = json.dumps(sealed, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True).replace("`", "\\u0060")
    return f"```json brain-{name}\n{text}\n```"


_FENCE_RE_CACHE: dict[str, re.Pattern] = {}


def _fence_re(name: str) -> re.Pattern:
    if name not in _FENCE_RE_CACHE:
        _FENCE_RE_CACHE[name] = re.compile(
            r"^```json[ \t]+brain-" + re.escape(name) + r"[ \t]*\n(.*?)\n```[ \t]*$",
            re.S | re.M)
    return _FENCE_RE_CACHE[name]


def parse_block(kind: str, text: str) -> dict | None:
    """The first block of ``kind`` in ``text`` whose digest checks, or
    None. A block that does not parse, is not an object, or whose digest
    is wrong is not a block: a truncated body must not read as a short
    one."""
    name = _kind(kind)
    for m in _fence_re(name).finditer(str(text or "")):
        try:
            obj = json.loads(m.group(1))
        except ValueError:
            continue
        if not isinstance(obj, dict) or not isinstance(obj.get("digest"), str):
            continue
        if obj["digest"] != digest(obj):
            continue
        return obj
    return None


def all_blocks(kind: str, text: str) -> list[dict]:
    """Every valid block of ``kind`` in ``text``, in order."""
    name = _kind(kind)
    out = []
    for m in _fence_re(name).finditer(str(text or "")):
        try:
            obj = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("digest") == digest(obj):
            out.append(obj)
    return out
