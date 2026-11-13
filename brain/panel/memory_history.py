#!/usr/bin/env python3
"""Versioned memory: every change to memory.md is a checked, attributed,
undoable version (plan 2.2–2.4, `docs/design/self-learning-plan-2026-11.md`).

The owner decided there is no human in the loop (the plan's section 0), so
a memory change is never queued for a person to approve. What replaces the
person is this module, which the consolidator calls under its own lock —
so memory.md still has exactly one writer, the consolidator process, and
this is a helper it runs rather than a second writer:

  * **A deterministic check** (`check`) on every proposed document
    (`memory.next.md`) before it is applied: the size cap, every line a
    person gave still present verbatim (whitespace aside) unless newer words
    from a person supersede it, and no `(unverified)` line silently promoted
    to a plain one. A failure keeps the current document, leaves the inbox
    pending and records why (`rejections.jsonl`); the consolidator feeds the
    reason back to the model once, because a guard that refuses has to
    change the next attempt (`docs/notes/brain-core.md`).
  * **A structured diff** with each line's source: added, merged, dropped,
    evicted, and the lines marked `(unverified)`.
  * **History** (`record`): every applied version is kept with its diff in
    the history folder (`/data/memory-history/`, the last `KEEP_VERSIONS`),
    and `undo` restores the previous one *as a new version*, so an undo is
    itself undoable.
  * **Provenance** (`memory.provenance.json` beside memory.md): which class
    each line belongs to — `person` (a correction, a confirmed guess, a line
    somebody typed: never dropped, never rewritten, never evicted, never
    offered for clean-up), `machine` (brAIn's own runs), `untrusted` (another
    add-on, an automation, a web page, a file, a tool's output — filed
    ending `(unverified)`), or `legacy` (in the document before versioning,
    origin unknown).
  * **Eviction** (`evict`): when a document will not fit its cap after the
    model's own retry, whole lines are evicted rather than the inbox
    stalling — unverified lines first, then the oldest unreferenced machine
    lines, then legacy ones; never a person's line and never a fact the
    pass is filing for the first time. The eviction is part of that pass's
    version, so `undo` brings the lines back.
  * **The nightly self-check** (`selfcheck`): the latest machine-made
    version is re-checked against its predecessor, and a failure rolls
    memory back one version — never over a person's own edit.

Stdlib plus `atomic_write`, so the shell consolidator can run it as a
script (`python3 /opt/panel/memory_history.py <command>`) and the panel
can import it.

Diff format (``<version>.json``, also written as ``memory.next.diff.json``
for the pass in flight)::

    {"seq": 12, "ts": 1762300000, "kind": "consolidation", "sha": "…",
     "bytes": 4210, "checked": true, "reason": "",
     "diff": {"added":   [{"line", "class", "sources"}],
              "merged":  [{"line", "class", "sources", "from": [lines]}],
              "dropped": [{"line", "class", "sources", "why"}],
              "evicted": [{"line", "class", "sources", "why"}],
              "marked_unverified": [lines],
              "superseded": [person lines newer person words replaced],
              "corroborated": [unverified lines a person confirmed]},
     "person_keys": [...], "unverified_keys": [...]}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import atomic_write  # beside this file in the image and in a checkout

DEFAULT_MEMORY_DIR = "/config/.brain/memory"
DEFAULT_HISTORY_DIR = "/data/memory-history"
KEEP_VERSIONS = 30
KEEP_REJECTIONS = 50
LEDGER_NAME = "memory.provenance.json"
NEXT_NAME = "memory.next.md"
NEXT_DIFF_NAME = "memory.next.diff.json"
UNVERIFIED = "(unverified)"

# Exit codes the shell tells apart.
RC_OK = 0
RC_ERROR = 2
RC_RETRY = 3      # the check refused; stdout is the note to feed back
RC_FULL = 4       # nothing left to evict and still over the cap

# ---------------------------------------------------------------------------
# Provenance: who a line came from
# ---------------------------------------------------------------------------

# What a person said. A correction, a confirmed guess, the teach box, a line
# typed with `brain memory add` (its file ends `-typed.jsonl`), a removal
# typed with `brain memory forget`, and a line somebody typed into the
# document itself (`person-edit`, read off the version history).
PERSON_SOURCES = frozenset({
    "correction", "person", "homeowner", "confirmed", "hypothesis-confirmed",
    "terminal-forget", "you", "user", "person-edit", "panel",
})
# Text from outside brAIn's own judgement of the house: another add-on (the
# /share inbox, a sibling's own source word), an automation's service call,
# a web page, a file, a tool's output, or the assistant's own words with no
# person behind them. Filed `(unverified)` and never a core fact until a
# person's own words corroborate it (plan 2.3).
UNTRUSTED_SOURCES = frozenset({
    "service", "automation", "web", "webfetch", "fetch", "file", "tool",
    "addon", "assistant", "share", "external", "unknown", "gardenrx",
    "minecraft", "bambu", "bruh_bambu", "print", "bruh_print", "bright",
    "cooking", "bruh_cooking", "task_manager", "bruh_task_manager",
    "browser", "bruh_browser",
})
UNTRUSTED_PREFIXES = ("addon:", "tool:", "web:", "file:", "mcp:", "share:")
UNTRUSTED_VIA = frozenset({"tool", "web", "file", "addon", "assistant"})
# A file every line of which a person typed (`brain memory add`).
TYPED_SUFFIX = "-typed.jsonl"
# A file the consolidator swept in from /share: another add-on wrote it,
# whatever source word its lines carry.
SHARE_PREFIX = "share-"
CLASS_RANK = {"person": 3, "machine": 2, "legacy": 1, "untrusted": 0}


def provenance(record: dict, filename: str = "") -> str:
    """`person`, `machine` or `untrusted` for one inbox record."""
    if not isinstance(record, dict):
        return "untrusted"
    source = str(record.get("source") or "").strip().lower()
    if record.get("origin") == "addon":
        return "untrusted"
    if str(record.get("via") or "").lower() in UNTRUSTED_VIA:
        return "untrusted"
    if not source or source in UNTRUSTED_SOURCES \
            or source.startswith(UNTRUSTED_PREFIXES):
        return "untrusted"
    if filename.startswith(SHARE_PREFIX):
        return "untrusted"
    if source in PERSON_SOURCES:
        return "person"
    if filename.endswith(TYPED_SUFFIX):
        return "person"
    return "machine"


def is_person_source(source: str) -> bool:
    return str(source or "").strip().lower() in PERSON_SOURCES


def is_untrusted(record: dict) -> bool:
    return provenance(record) == "untrusted"


# ---------------------------------------------------------------------------
# Lines and their words
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9]+")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_OBSERVED = re.compile(r"\s*\(observed \d{4}-\d{2}-\d{2}\)\s*$", re.I)
_STOP = frozenset((
    "the", "and", "for", "that", "this", "with", "are", "was", "were", "has",
    "have", "had", "not", "but", "its", "it's", "from", "into", "onto", "our",
    "you", "your", "they", "their", "them", "there", "here", "when", "then",
    "than", "also", "only", "just", "all", "any", "each", "every", "one",
    "observed", "unverified", "verify", "before", "asserting", "about",
    "what", "which", "who", "whom", "will", "would", "should", "could", "can",
    "been", "being", "does", "did", "doing", "very", "more", "most", "some",
    "forget", "homeowner", "says", "said",
))


def norm(line: str) -> str:
    """A line as the check compares it: whitespace collapsed, ends trimmed."""
    return _WS.sub(" ", str(line or "")).strip()


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s", "ly"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> set[str]:
    out = set()
    for w in _WORD.findall(str(text or "").lower()):
        if len(w) < 3 or w in _STOP or w.isdigit():
            continue
        out.add(_stem(w))
    return out


def share(a: set[str], b: set[str]) -> float:
    """How much two claims overlap, over the shorter one."""
    if not a or not b:
        return 0.0
    common = len(a & b)
    if common < min(2, len(a), len(b)):
        return 0.0
    return common / min(len(a), len(b))


MATCH_SHARE = 0.5


def fact_lines(text: str) -> list[str]:
    """The document's fact lines, raw: not a heading, not blank, not inside
    an HTML comment. The structure survives any rewrite; the facts are what
    a check has to account for."""
    out: list[str] = []
    in_comment = False
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith("<!--"):
            if "-->" not in line:
                in_comment = True
            continue
        if not line or line.startswith("#") or line.startswith("-->"):
            continue
        out.append(raw.rstrip())
    return out


def without_mark(line: str) -> str:
    return norm(str(line).replace(UNVERIFIED, " "))


def marked(line: str) -> bool:
    return UNVERIFIED in str(line or "")


def mark_unverified(line: str) -> str:
    """The line ending `(unverified)`, ahead of its observed-at marker."""
    if marked(line):
        return line
    m = _OBSERVED.search(line)
    if m:
        return line[: m.start()].rstrip() + f" {UNVERIFIED}" + line[m.start():]
    return line.rstrip() + f" {UNVERIFIED}"


def sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", "replace")).hexdigest()


_OBS_DATE = re.compile(r"\(observed (\d{4})-(\d{2})-(\d{2})\)")


def observed_ts(line: str) -> float:
    m = _OBS_DATE.search(str(line or ""))
    if not m:
        return 0.0
    try:
        return time.mktime((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            0, 0, 0, 0, 0, -1))
    except (OverflowError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def memory_dir() -> Path:
    return Path(os.environ.get("BRAIN_MEMORY_DIR", DEFAULT_MEMORY_DIR))


def history_dir(mem: Path | None = None) -> Path:
    """Where versions are kept.

    `BRAIN_MEMORY_HISTORY_DIR` when set. Otherwise `/data/memory-history`
    for the real memory folder — outside `/config`, so the history is not
    another thing in Home Assistant's config tree — and `<memory>/history`
    for any other memory folder (a dev checkout, a test), so nothing a test
    drives ever writes into the real `/data`: `publish_state`'s rule. The
    real folder falls back to `<memory>/history` too when `/data` cannot be
    written by this process (run.sh creates it for the `claude` user).
    """
    mem = Path(mem) if mem is not None else memory_dir()
    env = os.environ.get("BRAIN_MEMORY_HISTORY_DIR", "").strip()
    if env:
        return Path(env)
    fallback = mem / "history"
    if os.path.normpath(str(mem)) != os.path.normpath(DEFAULT_MEMORY_DIR):
        return fallback
    # One answer for every process, whoever asks first: the panel (root)
    # and the consolidator (`claude`) must not keep two histories. A
    # folder that exists wins, the primary first; with neither, the
    # primary only when this process can create it.
    primary = Path(DEFAULT_HISTORY_DIR)
    if primary.is_dir():
        return primary
    if fallback.is_dir():
        return fallback
    if primary.parent.is_dir() and os.access(primary.parent, os.W_OK | os.X_OK):
        return primary
    return fallback


def _make_hist(hist: Path, mem: Path | None = None) -> None:
    """Create the history folder, handed to whoever owns the memory folder
    when root creates it — the consolidator runs as `claude` and must be
    able to add the next version to a folder the panel made."""
    existed = hist.is_dir()
    hist.mkdir(parents=True, exist_ok=True)
    if existed or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    try:
        st = os.stat(mem if mem is not None else memory_dir())
        os.chown(hist, st.st_uid, st.st_gid)
    except OSError:
        # Not root after all, or a filesystem that will not: the folder is
        # still this process's, which is what it was before the chown.
        pass


def ledger_path(mem: Path | None = None) -> Path:
    return (Path(mem) if mem is not None else memory_dir()) / LEDGER_NAME


def _write_text(path: Path, text: str) -> None:
    atomic_write.write_text(path, text)


def _write_json(path: Path, data) -> None:
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=1))


def _read_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _read_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


def load_ledger(mem: Path | None = None) -> dict:
    data = _read_json(ledger_path(mem), {})
    lines = data.get("lines") if isinstance(data.get("lines"), dict) else {}
    return {"head": str(data.get("head") or ""), "lines": lines,
            "exists": ledger_path(mem).exists()}


def save_ledger(ledger: dict, mem: Path | None = None) -> None:
    _write_json(ledger_path(mem), {"version": 1, "head": ledger.get("head", ""),
                                   "lines": ledger.get("lines", {})})


def person_keys(document: str, ledger: dict | None = None,
                mem: Path | None = None) -> set[str]:
    """The lines of `document` a person gave: the ledger's `person` lines,
    and — when the document has moved since the last version brAIn wrote —
    every line the ledger has never seen, because the only other writer of
    memory.md is a person (the editor, `brain memory edit`, an import)."""
    ledger = ledger if ledger is not None else load_ledger(mem)
    known = ledger.get("lines") or {}
    out = set()
    edited = bool(ledger.get("head")) and ledger.get("head") != sha(document)
    for line in fact_lines(document):
        key = norm(line)
        entry = known.get(key)
        if entry is not None:
            if entry.get("class") == "person":
                out.add(key)
        elif edited:
            out.add(key)
    return out


# ---------------------------------------------------------------------------
# The inbox, as the check reads it
# ---------------------------------------------------------------------------


def read_inbox(inbox_dir) -> list[dict]:
    """Every pending record, each with its class and words."""
    out: list[dict] = []
    if not inbox_dir:
        return out
    try:
        files = sorted(p for p in Path(inbox_dir).glob("*.jsonl") if p.is_file())
    except OSError:
        return out
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            fact = str(rec.get("fact") or "").strip()
            if not fact:
                continue
            forget = fact.upper().startswith("FORGET:")
            body = fact[len("FORGET:"):].strip() if forget else fact
            out.append({"source": str(rec.get("source") or ""),
                        "class": provenance(rec, path.name),
                        "fact": body, "forget": forget,
                        "tokens": tokens(body)})
    return out


def untrusted_facts(inbox_dir) -> list[str]:
    return [r["fact"] for r in read_inbox(inbox_dir)
            if r["class"] == "untrusted" and not r["forget"]]


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


def _best(records, line_tokens, *, want=None, forget=None):
    hits = []
    for rec in records:
        if want is not None and rec["class"] not in want:
            continue
        if forget is not None and rec["forget"] != forget:
            continue
        s = share(line_tokens, rec["tokens"])
        if s >= MATCH_SHARE:
            hits.append((s, rec))
    hits.sort(key=lambda h: -h[0])
    return [h[1] for h in hits]


def _sources(recs) -> list[str]:
    return sorted({r["source"] or "unknown" for r in recs})


def _class_of(recs) -> str:
    classes = {r["class"] for r in recs}
    if "person" in classes:
        return "person"
    if "machine" in classes:
        return "machine"
    return "untrusted" if classes else "machine"


def check(current: str, proposed: str, records: list[dict], *,
          max_bytes: int, ledger: dict | None = None, evict: bool = False,
          now: float | None = None) -> dict:
    """Judge one proposed document against the one on disk.

    Returns ``{ok, full, violations, note, text, diff, attribution}``:
    ``text`` is the document to apply (the proposal with untrusted additions
    marked and, under ``evict``, lines evicted to fit), ``attribution`` maps
    each fact line of it to ``{class, sources}`` for the ledger.
    """
    now = time.time() if now is None else float(now)
    ledger = ledger if ledger is not None else {"head": "", "lines": {}}
    known = ledger.get("lines") or {}
    cur_lines = fact_lines(current)
    cur_keys = {norm(x): x for x in cur_lines}
    protected = person_keys(current, ledger)
    person_recs = [r for r in records if r["class"] == "person"]

    out_lines = str(proposed or "").splitlines()
    facts = set(fact_lines(proposed))
    next_keys = {norm(x) for x in facts}
    next_bare = {without_mark(x) for x in facts}
    violations: list[str] = []
    diff = {"added": [], "merged": [], "dropped": [], "evicted": [],
            "marked_unverified": [], "superseded": [], "corroborated": []}

    # 1. Every line a person gave is still there, or newer words from a
    #    person replaced it (a correction is newer and wins).
    for key in sorted(protected):
        if key in next_keys:
            continue
        line_toks = tokens(key)
        newer = _best(person_recs, line_toks)
        if newer:
            diff["superseded"].append(key)
            continue
        violations.append(f"a line a person gave was dropped or reworded: {key}")

    # 2. No (unverified) line becomes a plain one without a person saying so.
    for line in cur_lines:
        if not marked(line):
            continue
        bare = without_mark(line)
        if bare in next_bare and not any(
                without_mark(x) == bare and marked(x) for x in facts):
            if _best(person_recs, tokens(bare)):
                diff["corroborated"].append(bare)
                continue
            violations.append(
                f"the (unverified) mark was taken off without a person "
                f"confirming it: {bare}")

    # 3. What was added and from whom; untrusted additions are marked.
    attribution: dict[str, dict] = {}
    dropped_cur = [x for x in cur_lines if norm(x) not in next_keys]
    for i, raw in enumerate(out_lines):
        if raw not in facts:
            continue
        key = norm(raw)
        if key in cur_keys:
            entry = known.get(key) or {}
            line_toks = tokens(raw)
            refs = _best(records, line_toks, forget=False)
            cls = entry.get("class") or ("person" if key in protected else "legacy")
            attribution[key] = {"class": cls,
                                "sources": entry.get("sources") or [],
                                "refs": bool(refs)}
            continue
        line_toks = tokens(raw)
        recs = _best(records, line_toks, forget=False)
        parents = [x for x in dropped_cur if share(tokens(x), line_toks) >= MATCH_SHARE]
        cls = _class_of(recs) if recs else "machine"
        if not recs and parents:
            pclasses = [(known.get(norm(p)) or {}).get("class", "legacy")
                        for p in parents]
            cls = max(pclasses, key=lambda c: CLASS_RANK.get(c, 1))
            if cls == "person":
                cls = "machine"     # a reworded person line is brAIn's words
        if cls == "untrusted" and not marked(raw):
            raw = mark_unverified(raw)
            out_lines[i] = raw
            diff["marked_unverified"].append(norm(raw))
            key = norm(raw)
        if marked(raw) and cls != "person":
            cls = "untrusted"
        sources = _sources(recs) if recs else (
            ["consolidator"] if not parents else
            sorted({s for p in parents
                    for s in (known.get(norm(p)) or {}).get("sources") or []})
            or ["consolidator"])
        attribution[key] = {"class": cls, "sources": sources, "refs": False}
        item = {"line": key, "class": cls, "sources": sources}
        if parents:
            diff["merged"].append({**item, "from": [norm(p) for p in parents]})
        else:
            diff["added"].append(item)
    merged_from = {f for m in diff["merged"] for f in m["from"]}
    for line in dropped_cur:
        key = norm(line)
        if key in merged_from:
            continue
        entry = known.get(key) or {}
        forgets = _best(records, tokens(line), forget=True)
        why = ("asked to forget" if forgets else
               "superseded by a person" if key in diff["superseded"] else
               "left out by the consolidator")
        diff["dropped"].append({
            "line": key,
            "class": entry.get("class") or ("person" if key in protected else "legacy"),
            "sources": entry.get("sources") or [], "why": why})

    text = "\n".join(out_lines)
    full = False
    # 4. The size cap, with eviction instead of a stalled inbox.
    if _size(text) > max_bytes:
        if evict:
            text, evicted = _evict(text, max_bytes, protected=protected,
                                   current_keys=set(cur_keys), known=known,
                                   attribution=attribution, now=now)
            diff["evicted"] = evicted
            for e in evicted:
                attribution.pop(e["line"], None)
        if _size(text) > max_bytes:
            full = True
            violations.append(
                f"memory.md is {_size(text)} bytes, over the {max_bytes} byte "
                f"cap, and nothing more may be evicted (a person's lines and "
                f"the facts being filed now are never evicted)")
    ok = not violations
    return {"ok": ok, "full": full, "violations": violations,
            "note": retry_note(violations) if not ok and not full else "",
            "text": text + ("\n" if text and not text.endswith("\n") else ""),
            "diff": diff, "attribution": attribution}


def _size(text: str) -> int:
    # The same measure the consolidator's own cap check uses: characters of
    # the document with its trailing newlines stripped (`${#new_memory}`).
    return len(str(text or "").rstrip("\n"))


def _evict(text, max_bytes, *, protected, current_keys, known, attribution,
           now):
    """Whole lines out, lowest value first, until the document fits.

    Unverified lines first (new or old), then lines already in the document
    that a machine wrote — oldest and least referenced first — then legacy
    lines of unknown origin. Never a person's line, and never a fact this
    pass is filing for the first time: eviction makes room FOR the inbox.
    """
    lines = text.splitlines()
    facts = set(fact_lines(text))
    candidates = []
    for idx, raw in enumerate(lines):
        if raw not in facts:
            continue
        key = norm(raw)
        if key in protected:
            continue
        att = attribution.get(key) or {}
        cls = att.get("class") or "legacy"
        if cls == "person":
            continue
        entry = known.get(key) or {}
        if marked(raw):
            tier = 0
        elif key in current_keys and cls == "machine":
            tier = 1
        elif key in current_keys:
            tier = 2
        else:
            continue
        refs = int(entry.get("refs") or 0) + (1 if att.get("refs") else 0)
        age = float(entry.get("first") or 0) or observed_ts(raw)
        candidates.append((tier, refs, age, idx, raw, cls, entry))
    candidates.sort(key=lambda c: c[:4])
    gone: set[int] = set()
    evicted = []
    for tier, refs, age, idx, raw, cls, entry in candidates:
        if _size("\n".join(l for i, l in enumerate(lines) if i not in gone)) <= max_bytes:
            break
        gone.add(idx)
        why = ("unverified" if tier == 0 else
               "oldest unreferenced line brAIn wrote" if tier == 1 else
               "oldest line of unknown origin")
        evicted.append({"line": norm(raw), "class": cls,
                        "sources": entry.get("sources") or [], "why": why,
                        "refs": refs})
    kept = [l for i, l in enumerate(lines) if i not in gone]
    return "\n".join(kept), evicted


def retry_note(violations: list[str]) -> str:
    """What the model is told after the check refused its answer — the
    measured reason, last in the prompt, so the next attempt differs."""
    lines = "\n".join(f"- {v}" for v in violations[:20])
    return ("\nYOUR PREVIOUS ATTEMPT WAS REJECTED AND NOTHING WAS SAVED. "
            "A deterministic check found:\n" + lines + "\nProduce the merge "
            "again. Copy every protected line EXACTLY as given (no new "
            "markers, no rewording), and keep the (unverified) mark on every "
            "line that carries it unless a correction or a person's own words "
            "in this batch confirm it.")


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"^v(\d{6})-(\d+)-([a-z-]+)\.json$")


def versions(hist: Path | None = None) -> list[dict]:
    """Every kept version's metadata, oldest first."""
    hist = Path(hist) if hist is not None else history_dir()
    out = []
    try:
        names = os.listdir(hist)
    except OSError:
        return out
    for name in names:
        m = _VERSION_RE.match(name)
        if not m:
            continue
        meta = _read_json(hist / name, {})
        if not meta:
            continue
        meta.setdefault("seq", int(m.group(1)))
        meta["_json"] = str(hist / name)
        meta["_md"] = str(hist / name[:-5]) + ".md"
        out.append(meta)
    out.sort(key=lambda v: int(v.get("seq") or 0))
    return out


def version_text(meta: dict) -> str:
    return _read_text(Path(meta.get("_md") or ""))


def add_version(text: str, *, kind: str, diff: dict | None = None,
                reason: str = "", checked: bool = True, extra: dict | None = None,
                ledger: dict | None = None, hist: Path | None = None,
                now: float | None = None) -> dict:
    hist = Path(hist) if hist is not None else history_dir()
    _make_hist(hist)
    now = time.time() if now is None else float(now)
    have = versions(hist)
    seq = (int(have[-1]["seq"]) + 1) if have else 1
    kind = re.sub(r"[^a-z-]", "-", str(kind or "change").lower()) or "change"
    stem = f"v{seq:06d}-{int(now)}-{kind}"
    ledger = ledger or {"lines": {}}
    lines = ledger.get("lines") or {}
    present = {norm(x) for x in fact_lines(text)}
    meta = {
        "seq": seq, "ts": int(now), "kind": kind, "sha": sha(text),
        "bytes": len(text.encode("utf-8")), "checked": bool(checked),
        "reason": str(reason or "")[:500],
        "diff": diff or {},
        "person_keys": sorted(k for k in present
                              if (lines.get(k) or {}).get("class") == "person"),
        "unverified_keys": sorted(without_mark(k) for k in present if marked(k)),
    }
    if extra:
        meta.update(extra)
    _write_text(hist / f"{stem}.md", text)
    _write_json(hist / f"{stem}.json", meta)
    _prune(hist)
    meta["_json"] = str(hist / f"{stem}.json")
    meta["_md"] = str(hist / f"{stem}.md")
    return meta


def _prune(hist: Path) -> None:
    have = versions(hist)
    for meta in have[:-KEEP_VERSIONS] if len(have) > KEEP_VERSIONS else []:
        for key in ("_json", "_md"):
            try:
                os.unlink(meta[key])
            except OSError:
                # Already pruned by another process: the cap holds either way.
                pass


def reject(reasons, *, kind: str = "consolidation", hist: Path | None = None,
           now: float | None = None) -> None:
    """Why a proposed version was refused, kept for `brain memory history`."""
    hist = Path(hist) if hist is not None else history_dir()
    path = hist / "rejections.jsonl"
    try:
        _make_hist(hist)
        old = _read_text(path).splitlines()
        row = json.dumps({"ts": int(time.time() if now is None else now),
                          "kind": kind, "reasons": list(reasons)[:20]},
                         ensure_ascii=False)
        _write_text(path, "\n".join((old + [row])[-KEEP_REJECTIONS:]) + "\n")
    except OSError:
        # The record of a refusal is bookkeeping; the refusal itself (the
        # document and the inbox kept) has already happened and is logged.
        pass


def rejections(hist: Path | None = None) -> list[dict]:
    hist = Path(hist) if hist is not None else history_dir()
    out = []
    for line in _read_text(hist / "rejections.jsonl").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _bootstrap_classes(mem: Path, document: str) -> dict:
    """The ledger for a document versioning has never seen.

    Origin unknown is `legacy`, except where the facts store or the inbox's
    archive (the last 30 days of filed lines) says a person gave it — so a
    correction filed before this existed is protected from its first pass.
    """
    records: list[dict] = []
    stored = _read_json(mem / "facts.json", {})
    rows = stored.get("facts") if isinstance(stored.get("facts"), list) else []
    for row in rows:
        if isinstance(row, dict) and row.get("text"):
            records.append({"class": provenance(row), "source": str(row.get("source") or ""),
                            "tokens": tokens(row.get("text")), "forget": False})
    processed = mem / "inbox" / "processed"
    for rec in read_inbox(processed):
        if not rec["forget"]:
            records.append(rec)
    person = [r for r in records if r["class"] == "person"]
    untrusted = [r for r in records if r["class"] == "untrusted"]
    out = {}
    for line in fact_lines(document):
        key = norm(line)
        toks = tokens(line)
        hits = _best(person, toks)
        if hits:
            out[key] = {"class": "person", "sources": _sources(hits),
                        "first": 0, "refs": 0}
        elif marked(line) or _best(untrusted, toks):
            out[key] = {"class": "untrusted" if marked(line) else "legacy",
                        "sources": _sources(_best(untrusted, toks)) or ["legacy"],
                        "first": 0, "refs": 0}
        else:
            out[key] = {"class": "legacy", "sources": ["legacy"],
                        "first": 0, "refs": 0}
    return out


def ensure_baseline(previous: str, *, mem: Path, hist: Path,
                    now: float | None = None) -> dict:
    """Before a new version lands: the history and the ledger are brought up
    to the document as it stands — a `baseline` the first time, and a
    `person-edit` version when somebody changed memory.md by hand since the
    last version brAIn wrote, so an undo of the next change goes back to
    their edit rather than past it."""
    ledger = load_ledger(mem)
    have = versions(hist)
    now = time.time() if now is None else float(now)
    if not ledger["exists"] and not have:
        ledger["lines"] = _bootstrap_classes(mem, previous)
        ledger["head"] = sha(previous)
        if fact_lines(previous) or previous.strip():
            add_version(previous, kind="baseline", ledger=ledger, hist=hist,
                        reason="the document before versioning", now=now - 1)
        save_ledger(ledger, mem)
        return ledger
    head_sha = ledger.get("head") or (have[-1].get("sha") if have else "")
    if head_sha and head_sha != sha(previous):
        before = version_text(have[-1]) if have else ""
        typed = person_keys(previous, {**ledger, "head": head_sha})
        lines = dict(ledger.get("lines") or {})
        present = {norm(x) for x in fact_lines(previous)}
        for key in list(lines):
            if key not in present:
                lines.pop(key)
        for key in typed:
            if key not in lines or lines[key].get("class") != "person":
                lines[key] = {"class": "person", "sources": ["person-edit"],
                              "first": int(now), "refs": 0}
        ledger["lines"] = lines
        ledger["head"] = sha(previous)
        old = {norm(x) for x in fact_lines(before)}
        add_version(previous, kind="person-edit", ledger=ledger, hist=hist,
                    diff={"added": [{"line": k, "class": "person",
                                     "sources": ["person-edit"]}
                                    for k in sorted(present - old)],
                          "dropped": [{"line": k, "class": "person",
                                       "sources": ["person-edit"],
                                       "why": "removed by hand"}
                                      for k in sorted(old - present)]},
                    reason="memory.md was changed by hand", now=now - 1)
        save_ledger(ledger, mem)
    elif not ledger["exists"]:
        ledger["lines"] = _bootstrap_classes(mem, previous)
        ledger["head"] = sha(previous)
        save_ledger(ledger, mem)
    return ledger


def record(previous: str, applied: str, *, kind: str, check_result: dict | None,
           mem: Path | None = None, hist: Path | None = None,
           reason: str = "", checked: bool = True,
           now: float | None = None) -> dict:
    """Keep `applied` as the newest version and bring the ledger up to it."""
    mem = Path(mem) if mem is not None else memory_dir()
    hist = Path(hist) if hist is not None else history_dir(mem)
    now = time.time() if now is None else float(now)
    ledger = ensure_baseline(previous, mem=mem, hist=hist, now=now)
    attribution = (check_result or {}).get("attribution") or {}
    lines_before = ledger.get("lines") or {}
    once_person = {k for v in versions(hist) for k in v.get("person_keys") or []}
    lines_after: dict[str, dict] = {}
    for raw in fact_lines(applied):
        key = norm(raw)
        old = lines_before.get(key)
        att = attribution.get(key) or {}
        if old is not None:
            entry = dict(old)
            if att.get("refs"):
                entry["refs"] = int(entry.get("refs") or 0) + 1
                entry["last_ref"] = int(now)
        else:
            cls = att.get("class") or (
                "person" if key in once_person else
                "untrusted" if marked(raw) else "machine")
            if cls == "restored":
                cls = "person" if key in once_person else "legacy"
            entry = {"class": cls, "sources": att.get("sources") or [kind],
                     "first": int(now), "refs": 0}
        if marked(raw) and entry.get("class") != "person":
            entry["class"] = "untrusted"
        lines_after[key] = entry
    ledger = {"head": sha(applied), "lines": lines_after}
    meta = add_version(applied, kind=kind,
                       diff=(check_result or {}).get("diff") or {},
                       reason=reason, checked=checked, ledger=ledger,
                       hist=hist, now=now)
    save_ledger(ledger, mem)
    return meta


def apply(previous: str, applied: str, *, kind: str, memory_file: Path,
          check_result: dict | None = None, reason: str = "",
          checked: bool = True, mem: Path | None = None,
          hist: Path | None = None, now: float | None = None) -> dict:
    """Write memory.md atomically, then keep the version. For the changes
    this module makes itself (undo, a rollback, a clean-up's removals);
    the consolidator's own pass writes the document in the shell and calls
    `record` after."""
    mem = Path(mem) if mem is not None else Path(memory_file).parent
    hist = Path(hist) if hist is not None else history_dir(mem)
    _write_text(Path(memory_file), applied)
    return record(previous, applied, kind=kind, check_result=check_result,
                  mem=mem, hist=hist, reason=reason, checked=checked, now=now)


# ---------------------------------------------------------------------------
# Undo, removals, the nightly self-check
# ---------------------------------------------------------------------------


def undo(memory_file: Path, *, to_seq: int | None = None,
         mem: Path | None = None, hist: Path | None = None,
         now: float | None = None) -> dict:
    """Restore the version before the newest (or `to_seq`) as a NEW version.

    Raises LookupError when there is nothing to go back to.
    """
    memory_file = Path(memory_file)
    mem = Path(mem) if mem is not None else memory_file.parent
    hist = Path(hist) if hist is not None else history_dir(mem)
    current = _read_text(memory_file)
    ensure_baseline(current, mem=mem, hist=hist, now=now)
    have = versions(hist)
    if to_seq is not None:
        target = next((v for v in have if int(v["seq"]) == int(to_seq)), None)
        if target is None:
            raise LookupError(f"no version {to_seq} is kept")
    else:
        if len(have) < 2:
            raise LookupError("there is no earlier version to go back to")
        target = have[-2]
    text = version_text(target)
    old = {norm(x) for x in fact_lines(current)}
    new = {norm(x) for x in fact_lines(text)}
    diff = {"added": [{"line": k, "class": "restored", "sources": ["undo"]}
                      for k in sorted(new - old)],
            "dropped": [{"line": k, "class": "", "sources": ["undo"],
                         "why": "undone"} for k in sorted(old - new)]}
    ledger = load_ledger(mem)
    # Lines coming back keep the class they had when that version was kept.
    restored_person = set(target.get("person_keys") or [])
    result = {"attribution": {
        k: {"class": "person" if k in restored_person else
            (ledger["lines"].get(k) or {}).get("class") or
            ("untrusted" if marked(k) else "legacy"),
            "sources": (ledger["lines"].get(k) or {}).get("sources") or ["undo"]}
        for k in new}, "diff": diff}
    return apply(current, text, kind="undo", memory_file=memory_file,
                 check_result=result, mem=mem, hist=hist, now=now,
                 reason=f"restored version {target['seq']}",
                 checked=False) | {"restored": int(target["seq"])}


def remove_lines(memory_file: Path, texts, *, max_bytes: int,
                 kind: str = "cleanup", reasons: dict | None = None,
                 lines_at=None, mem: Path | None = None,
                 hist: Path | None = None, now: float | None = None) -> dict:
    """Take exact lines out of the document as one version — the clean-up's
    removals, without a model pass to reword them. A person's line is
    refused whatever asked, which is the check's rule applied up front.

    Each request removes ONE line: the one at its 1-based line number
    (``lines_at``, parallel to ``texts``) when that line still says it, else
    the first line saying it — so a duplicate's removal leaves its copy.

    Returns ``{removed: [...], refused: [...], version}``.
    """
    memory_file = Path(memory_file)
    mem = Path(mem) if mem is not None else memory_file.parent
    hist = Path(hist) if hist is not None else history_dir(mem)
    current = _read_text(memory_file)
    ledger = load_ledger(mem)
    protected = person_keys(current, ledger)
    reasons = reasons or {}
    raws = current.splitlines()
    facts = set(fact_lines(current))
    lines_at = list(lines_at or [])

    def says(raw: str, wanted: str) -> bool:
        body = norm(_BULLET.sub("", raw))
        return bool(wanted) and (body == wanted or norm(raw) == wanted or (
            len(wanted) >= 40 and body.startswith(wanted)))

    gone: set[int] = set()
    removed, refused = [], []
    for i, text in enumerate(texts or ()):
        wanted = norm(text)
        if not wanted:
            continue
        at = None
        try:
            n = int(lines_at[i]) - 1 if i < len(lines_at) and lines_at[i] else -1
        except (TypeError, ValueError):
            n = -1
        if 0 <= n < len(raws) and n not in gone and raws[n] in facts \
                and says(raws[n], wanted):
            at = n
        else:
            at = next((j for j, raw in enumerate(raws) if j not in gone
                       and raw in facts and says(raw, wanted)), None)
        if at is None:
            continue
        key = norm(raws[at])
        if key in protected:
            refused.append(key)
            continue
        gone.add(at)
        entry = ledger["lines"].get(key) or {}
        removed.append({"line": key, "why": reasons.get(wanted, kind),
                        "class": entry.get("class", "legacy"),
                        "sources": entry.get("sources") or []})
    if not removed:
        return {"removed": [], "refused": refused, "version": None}
    text = "\n".join(r for j, r in enumerate(raws) if j not in gone) \
        + ("\n" if current.endswith("\n") else "")
    result = check(current, text, [], max_bytes=max(max_bytes, len(current) + 1),
                   ledger=ledger, now=now)
    if not result["ok"]:
        reject(result["violations"], kind=kind, hist=hist, now=now)
        return {"removed": [], "refused": refused + list(result["violations"]),
                "version": None}
    result["diff"]["dropped"] = removed
    meta = apply(current, text, kind=kind, memory_file=memory_file,
                 check_result=result, mem=mem, hist=hist, now=now,
                 reason=f"{len(removed)} line(s) removed")
    return {"removed": [r["line"] for r in removed], "refused": refused,
            "version": int(meta["seq"])}


MACHINE_KINDS = ("consolidation", "cleanup", "eviction")


def selfcheck(memory_file: Path, *, max_bytes: int, mem: Path | None = None,
              hist: Path | None = None, now: float | None = None) -> dict:
    """The nightly check of the live document: the newest machine-made
    version re-judged against the one before it, with today's rules; a
    failure rolls memory back one version.

    Never over a person: a document changed by hand since the last version
    is recorded as their edit and left alone, and a version that IS a
    person's action (an edit, an undo, a rollback) is not judged.

    Returns ``{status: ok|edited|rolled_back|skipped, reasons, version}``.
    """
    memory_file = Path(memory_file)
    mem = Path(mem) if mem is not None else memory_file.parent
    hist = Path(hist) if hist is not None else history_dir(mem)
    live = _read_text(memory_file)
    have = versions(hist)
    if not have:
        if live.strip():
            ensure_baseline(live, mem=mem, hist=hist, now=now)
        return {"status": "skipped", "reasons": ["no versions kept yet"]}
    head = have[-1]
    if head.get("sha") != sha(live):
        ensure_baseline(live, mem=mem, hist=hist, now=now)
        return {"status": "edited",
                "reasons": ["memory.md was changed by hand; that edit is kept"]}
    if head.get("kind") not in MACHINE_KINDS or len(have) < 2:
        return {"status": "ok", "reasons": []}
    prev = have[-2]
    prev_text = version_text(prev)
    diff = head.get("diff") or {}
    excused = set(diff.get("superseded") or [])
    corroborated = set(diff.get("corroborated") or [])
    live_keys = {norm(x) for x in fact_lines(live)}
    live_bare_plain = {without_mark(x) for x in fact_lines(live) if not marked(x)}
    reasons = []
    for key in prev.get("person_keys") or []:
        if key not in live_keys and key not in excused:
            reasons.append(f"a line a person gave is missing: {key}")
    for bare in prev.get("unverified_keys") or []:
        if bare in live_bare_plain and bare not in corroborated:
            reasons.append(f"an unverified line lost its mark: {bare}")
    if _size(live) > max_bytes:
        reasons.append(f"memory.md is {_size(live)} bytes, over the "
                       f"{max_bytes} byte cap")
    if not reasons:
        return {"status": "ok", "reasons": []}
    reject(reasons, kind="selfcheck", hist=hist, now=now)
    meta = apply(live, prev_text, kind="rollback", memory_file=memory_file,
                 check_result={"diff": {"dropped": [], "added": []},
                               "attribution": {}},
                 mem=mem, hist=hist, now=now, checked=False,
                 reason="nightly check failed: " + "; ".join(reasons)[:400])
    return {"status": "rolled_back", "reasons": reasons,
            "version": int(meta["seq"]), "restored": int(prev["seq"])}


# ---------------------------------------------------------------------------
# The command line the consolidator and `brain memory` run
# ---------------------------------------------------------------------------


def _fmt_ts(ts) -> str:
    try:
        return time.strftime("%b %d %H:%M", time.localtime(int(ts)))
    except (TypeError, ValueError, OverflowError):
        return "?"


def history_lines(limit: int = 15, hist: Path | None = None) -> list[str]:
    have = versions(hist)
    out = []
    for meta in reversed(have[-limit:]):
        d = meta.get("diff") or {}
        sources = sorted({s for k in ("added", "merged") for item in d.get(k) or []
                          for s in item.get("sources") or []})
        out.append(
            f"  v{meta['seq']:<4} {_fmt_ts(meta.get('ts'))}  {meta.get('kind', '?'):<13}"
            f" +{len(d.get('added') or []) + len(d.get('merged') or [])}"
            f" -{len(d.get('dropped') or [])}"
            + (f" evicted {len(d['evicted'])}" if d.get("evicted") else "")
            + (f"  [{', '.join(sources[:4])}]" if sources else "")
            + (f"  {meta['reason']}" if meta.get("reason") else ""))
    return out


def _cmd_check(a) -> int:
    mem = Path(a.memory).parent
    current = _read_text(Path(a.memory))
    proposed = _read_text(Path(a.next))
    records = read_inbox(a.inbox_dir)
    ledger = load_ledger(mem)
    if not ledger["exists"]:
        # Never versioned yet: protect what the facts store and the inbox
        # archive say a person gave, without writing anything on a check.
        ledger = {"head": "", "lines": _bootstrap_classes(mem, current)}
    result = check(current, proposed, records, max_bytes=a.max_bytes,
                   ledger=ledger, evict=a.evict)
    payload = {k: result[k] for k in ("ok", "full", "violations", "diff",
                                      "attribution")}
    if a.diff:
        _write_json(Path(a.diff), payload)
    if result["ok"]:
        _write_text(Path(a.next), result["text"])
        for e in result["diff"].get("evicted") or []:
            print(f"evicted ({e['why']}): {e['line']}", file=sys.stderr)
        return RC_OK
    reject(result["violations"], kind=a.kind, hist=history_dir(mem))
    if result["full"]:
        print("; ".join(result["violations"]))
        return RC_FULL
    print(result["note"])
    return RC_RETRY


def _cmd_record(a) -> int:
    mem = Path(a.memory).parent
    previous = _read_text(Path(a.prev)) if a.prev else ""
    applied = _read_text(Path(a.memory))
    payload = _read_json(Path(a.diff), {}) if a.diff else {}
    meta = record(previous, applied, kind=a.kind, check_result=payload,
                  mem=mem, checked=bool(payload) and not a.unchecked,
                  reason=a.reason or "")
    print(f"v{meta['seq']}")
    return RC_OK


def _cmd_protected(a) -> int:
    current = _read_text(Path(a.memory))
    keys = person_keys(current, load_ledger(Path(a.memory).parent))
    for line in fact_lines(current):
        if norm(line) in keys:
            print(line)
    return RC_OK


def _cmd_untrusted(a) -> int:
    for fact in untrusted_facts(a.inbox_dir):
        print(norm(fact)[:400])
    return RC_OK


def _cmd_undo(a) -> int:
    try:
        meta = undo(Path(a.memory), to_seq=a.to)
    except LookupError as exc:
        print(str(exc))
        return RC_ERROR
    print(f"restored version {meta['restored']} as v{meta['seq']}")
    return RC_OK


def _cmd_remove(a) -> int:
    payload = _read_json(Path(a.lines), [])
    texts, reasons, at = [], {}, []
    for item in payload if isinstance(payload, list) else []:
        if isinstance(item, dict):
            text = str(item.get("text") or "")
            texts.append(text)
            at.append(item.get("line"))
            reasons[norm(text)] = str(item.get("why") or a.kind)[:200]
        elif isinstance(item, str):
            texts.append(item)
            at.append(None)
    out = remove_lines(Path(a.memory), texts, max_bytes=a.max_bytes,
                       kind=a.kind, reasons=reasons, lines_at=at)
    print(json.dumps(out, ensure_ascii=False))
    return RC_OK if out["version"] is not None or not texts else RC_RETRY


def _cmd_selfcheck(a) -> int:
    out = selfcheck(Path(a.memory), max_bytes=a.max_bytes)
    print(json.dumps(out, ensure_ascii=False))
    return RC_OK


def _cmd_history(a) -> int:
    mem = Path(a.memory).parent if a.memory else memory_dir()
    hist = history_dir(mem)
    if a.json:
        have = versions(hist)
        for v in have:
            v.pop("_json", None)
            v.pop("_md", None)
        print(json.dumps({"dir": str(hist), "versions": have[-a.limit:],
                          "rejections": rejections(hist)[-5:]},
                         ensure_ascii=False))
        return RC_OK
    rows = history_lines(a.limit, hist)
    if not rows:
        print("No versions kept yet — the first consolidation pass keeps one.")
    else:
        print("Memory versions (newest first):")
        print("\n".join(rows))
    last = rejections(hist)[-1:]
    if last:
        print(f"\nLast refused change ({_fmt_ts(last[0].get('ts'))}, "
              f"{last[0].get('kind')}): " + "; ".join(last[0].get("reasons") or [])[:400])
    return RC_OK


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="memory_history")
    sub = p.add_subparsers(dest="cmd", required=True)
    mem_default = str(memory_dir() / "memory.md")

    c = sub.add_parser("check")
    c.add_argument("--memory", default=mem_default)
    c.add_argument("--next", required=True)
    c.add_argument("--inbox-dir", default="")
    c.add_argument("--max-bytes", type=int, required=True)
    c.add_argument("--diff", default="")
    c.add_argument("--evict", action="store_true")
    c.add_argument("--kind", default="consolidation")
    c.set_defaults(fn=_cmd_check)

    r = sub.add_parser("record")
    r.add_argument("--memory", default=mem_default)
    r.add_argument("--prev", default="")
    r.add_argument("--diff", default="")
    r.add_argument("--kind", default="consolidation")
    r.add_argument("--reason", default="")
    r.add_argument("--unchecked", action="store_true")
    r.set_defaults(fn=_cmd_record)

    pr = sub.add_parser("protected")
    pr.add_argument("--memory", default=mem_default)
    pr.set_defaults(fn=_cmd_protected)

    u = sub.add_parser("untrusted")
    u.add_argument("--inbox-dir", required=True)
    u.set_defaults(fn=_cmd_untrusted)

    un = sub.add_parser("undo")
    un.add_argument("--memory", default=mem_default)
    un.add_argument("--to", type=int, default=None)
    un.set_defaults(fn=_cmd_undo)

    rm = sub.add_parser("remove")
    rm.add_argument("--memory", default=mem_default)
    rm.add_argument("--lines", required=True)
    rm.add_argument("--max-bytes", type=int, required=True)
    rm.add_argument("--kind", default="cleanup")
    rm.set_defaults(fn=_cmd_remove)

    s = sub.add_parser("selfcheck")
    s.add_argument("--memory", default=mem_default)
    s.add_argument("--max-bytes", type=int, required=True)
    s.set_defaults(fn=_cmd_selfcheck)

    h = sub.add_parser("history")
    h.add_argument("--memory", default=mem_default)
    h.add_argument("--limit", type=int, default=15)
    h.add_argument("--json", action="store_true")
    h.set_defaults(fn=_cmd_history)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except OSError as exc:
        print(f"memory history: {exc}", file=sys.stderr)
        return RC_ERROR


if __name__ == "__main__":
    sys.exit(main())
