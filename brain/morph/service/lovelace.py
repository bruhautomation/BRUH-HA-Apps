"""Home Assistant dashboards brAIn may change, kept in git (docs/design/morph-on-lovelace.md §2.1).

Home Assistant holds the dashboard and draws it. The integration mirrors
what it holds into ``/config/.morph/lovelace/<key>.json`` whenever it is
saved, and saves whatever this module drops in ``/config/.morph/lovelace-apply``.
Here each Morphed dashboard is ``/config/morph/dashboards/<key>.yaml``: the
file brAIn edits, a person may edit, and git keeps.

``sync`` reconciles the two sides against the hash they last agreed on:

* Home Assistant moved and the file did not: somebody used HA's own editor.
  The file is rewritten from HA (and morphd commits it as *Edited in Home
  Assistant*).
* The file moved and HA did not: brAIn, Undo or a text editor. It is sent
  to HA to save, and every open screen reloads that dashboard.
* Both moved: Home Assistant wins, because that is what everybody sees.
  The file's version is already in git (morphd commits pending edits first).
* A file that does not parse is somebody mid-edit: nothing is sent.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

import yaml

import convert
import paths

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
RESEND_S = 30
MAX_SHOWS = 8
HEADER = ("# {title} — a Home Assistant dashboard, kept in step by brAIn.\n"
          "# Edit it here or in Home Assistant: each change is saved to Home Assistant at once,\n"
          "# and every change is a git commit in /config/morph (Undo puts one back).\n")


def config_hash(config) -> str:
    """Canonical JSON, the integration's own rule (custom_components/brain/morph/lovelace.py)."""
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def file_of(key: str):
    return paths.DASHBOARDS_DIR / f"{key}.yaml"


def rel(key: str) -> str:
    return f"dashboards/{key}.yaml"


def morphed() -> list[str]:
    data = paths.read_json(paths.LL_MIRROR / "morphed.json", {}) or {}
    keys = data.get("keys") if isinstance(data, dict) else None
    return [k for k in keys if isinstance(k, str) and KEY_RE.match(k)] if isinstance(keys, list) else []


def mirror(key: str) -> dict:
    data = paths.read_json(paths.LL_MIRROR / f"{key}.json", {}) or {}
    return data if isinstance(data, dict) else {}


def title_of(cfg, key: str) -> str:
    t = cfg.get("title") if isinstance(cfg, dict) else None
    return str(t or ("Overview" if key == "default" else key))[:80]


def dump(cfg: dict, key: str) -> str:
    return HEADER.format(title=title_of(cfg, key)) + yaml.safe_dump(
        cfg, sort_keys=False, allow_unicode=True, width=100)


def load_text(text: str) -> tuple[dict | None, str]:
    """(config, problem). A file that does not parse, or is not a mapping, is
    a problem in words and no config."""
    try:
        cfg = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        return None, f"The dashboard file could not be read{where}: {getattr(exc, 'problem', None) or exc}"
    if not isinstance(cfg, dict):
        return None, "The dashboard file must be a mapping with `views:` at the top."
    if not isinstance(cfg.get("views", []), list):
        return None, "`views:` must be a list."
    return cfg, ""


def read(key: str) -> tuple[dict | None, str, str]:
    """(config, problem, text) of the file kept in git."""
    try:
        text = file_of(key).read_text(encoding="utf-8")
    except OSError:
        return None, "missing", ""
    cfg, problem = load_text(text)
    return cfg, problem, text


def _state() -> dict:
    data = paths.read_json(paths.LL_SYNC, {}) or {}
    return data if isinstance(data, dict) else {}


def _apply(key: str, cfg: dict, h: str) -> None:
    paths.write_json(paths.LL_APPLY / f"{key}.json", {"key": key, "config": cfg, "hash": h, "at": time.time()})


def sync(now: float | None = None) -> list[dict]:
    """One pass over every Morphed dashboard. Returns what happened, one row
    per dashboard that moved: ``{key, title, what}`` where ``what`` is
    ``new`` (first kept), ``outside`` (HA's editor), ``both`` (HA's editor,
    over an edit here), ``apply`` (sent to HA), ``held`` (the file does not
    read) or ``sections`` (Morph's views became HA's sections views, once)."""
    now = time.time() if now is None else now
    state = _state()
    events: list[dict] = []
    for key in morphed():
        m = mirror(key)
        ha_cfg = m.get("config")
        if not isinstance(ha_cfg, dict):
            continue  # nothing stored yet (an untouched default dashboard)
        ha_h = config_hash(ha_cfg)
        st = state.setdefault(key, {})
        last = st.get("hash", "")
        title = title_of(ha_cfg, key)
        cfg, problem, _text = read(key)
        if problem == "missing":
            paths.write_text(file_of(key), dump(ha_cfg, key))
            paths.hand_to_brain(file_of(key))
            st.update(hash=ha_h, applying="")
            events.append({"key": key, "title": title, "what": "new"})
            continue
        if problem:
            if st.get("held") != problem:
                events.append({"key": key, "title": title, "what": "held", "problem": problem})
            st["held"] = problem
            continue
        st.pop("held", None)
        # Once per dashboard (5.1): a view 5.0's conversion wrote as Morph's
        # own view becomes Home Assistant's sections view, so HA's editor,
        # sizes and sections work on it; its switches stay as `morph:`. A
        # house that sets `custom:morph-view` again afterwards keeps it.
        if not st.get("sections_view"):
            st["sections_view"] = 1
            new, n = convert.migrate(cfg)
            if n:
                paths.write_text(file_of(key), dump(new, key))
                paths.hand_to_brain(file_of(key))
                cfg = new
                events.append({"key": key, "title": title, "what": "sections"})
        fh = config_hash(cfg)
        if fh == ha_h:
            st.update(hash=fh, applying="")
            continue
        if st.get("applying") == fh:
            if now - float(st.get("applying_at") or 0) > RESEND_S:
                _apply(key, cfg, fh)
                st["applying_at"] = now
            continue
        file_moved, ha_moved = fh != last, ha_h != last
        if file_moved and not ha_moved:
            _apply(key, cfg, fh)
            st.update(applying=fh, applying_at=now)
            events.append({"key": key, "title": title, "what": "apply"})
            continue
        paths.write_text(file_of(key), dump(ha_cfg, key))
        paths.hand_to_brain(file_of(key))
        st.update(hash=ha_h, applying="")
        events.append({"key": key, "title": title, "what": "both" if file_moved else "outside"})
    paths.write_json(paths.LL_SYNC, state)
    return events


# ------------------------------------------------------- what a person sees

def _label(card: dict) -> str:
    if not isinstance(card, dict):
        return "card"
    t = str(card.get("type") or "card")
    t = t[7:] if t.startswith("custom:") else t
    who = card.get("name") or card.get("title") or card.get("heading") or card.get("entity")
    ents = card.get("entities")
    if not who and isinstance(ents, list) and ents:
        first = ents[0]
        who = first if isinstance(first, str) else (first or {}).get("entity") if isinstance(first, dict) else None
        if who and len(ents) > 1:
            who = f"{who} and {len(ents) - 1} more"
    return f"{t} card ({who})" if who else f"{t} card"


def _view_name(view: dict, i: int) -> str:
    return str((view or {}).get("title") or (view or {}).get("path") or f"view {i + 1}")


def _section_name(sec: dict, j: int) -> str:
    for c in (sec or {}).get("cards") or []:
        if isinstance(c, dict) and c.get("type") == "heading" and c.get("heading"):
            return str(c["heading"])
    return str((sec or {}).get("title") or f"section {j + 1}")


def places(cfg: dict) -> list[tuple[str, dict]]:
    """Every card with where it is, in words."""
    out = []
    for i, view in enumerate((cfg or {}).get("views") or []):
        if not isinstance(view, dict):
            continue
        vn = _view_name(view, i)
        for c in view.get("cards") or []:
            out.append((vn, c))
        for j, sec in enumerate(view.get("sections") or []):
            if not isinstance(sec, dict):
                continue
            sn = _section_name(sec, j)
            for c in sec.get("cards") or []:
                out.append((f"{vn} › {sn}", c))
    return out


def describe_change(old: dict, new: dict) -> list[str]:
    """The difference between two configs as a person would see it."""
    shows: list[str] = []
    ov = [_view_name(v, i) for i, v in enumerate((old or {}).get("views") or []) if isinstance(v, dict)]
    nv = [_view_name(v, i) for i, v in enumerate((new or {}).get("views") or []) if isinstance(v, dict)]
    for v in nv:
        if v not in ov:
            shows.append(f"Added the {v} tab")
    for v in ov:
        if v not in nv:
            shows.append(f"Removed the {v} tab")
    if ov != nv and sorted(ov) == sorted(nv):
        shows.append("Reordered the tabs")
    key = lambda c: json.dumps(c, sort_keys=True)  # noqa: E731
    before = [(w, c, key(c)) for w, c in places(old)]
    after = [(w, c, key(c)) for w, c in places(new)]
    left = list(after)
    gone = []
    for row in before:
        hit = next((x for x in left if x[2] == row[2]), None)
        if hit:
            if hit[0] != row[0]:
                shows.append(f"Moved the {_label(row[1])} from {row[0]} to {hit[0]}")
            left.remove(hit)
        else:
            gone.append(row)
    for row in list(gone):
        same = next((x for x in left if x[0] == row[0] and isinstance(x[1], dict) and isinstance(row[1], dict)
                     and x[1].get("type") == row[1].get("type")), None)
        if same:
            shows.append(f"Changed the {_label(same[1])} in {same[0]}")
            left.remove(same)
            gone.remove(row)
    shows += [f"Removed the {_label(c)} from {w}" for w, c, _ in gone]
    shows += [f"Added a {_label(c)} to {w}" for w, c, _ in left]
    if not shows and json.dumps(old, sort_keys=True) != json.dumps(new, sort_keys=True):
        shows.append("Changed the dashboard's settings")
    if len(shows) > MAX_SHOWS:
        shows = shows[:MAX_SHOWS - 1] + [f"and {len(shows) - MAX_SHOWS + 1} more changes"]
    return shows


def at_path(cfg, at) -> object:
    """The part of a config at a list path such as ["views", 0, "sections", 1,
    "cards", 2], or None."""
    node = cfg
    for step in at or []:
        if isinstance(node, list) and isinstance(step, int) and 0 <= step < len(node):
            node = node[step]
        elif isinstance(node, dict) and isinstance(step, str) and step in node:
            node = node[step]
        else:
            return None
    return node


def where(cfg, at) -> str:
    """A path in words: "Home › Kitchen › tile card (light.kitchen)"."""
    at = list(at or [])
    words = []
    if len(at) >= 2 and at[0] == "views":
        view = at_path(cfg, at[:2])
        words.append(_view_name(view if isinstance(view, dict) else {}, at[1] if isinstance(at[1], int) else 0))
        if len(at) >= 4 and at[2] == "sections":
            sec = at_path(cfg, at[:4])
            words.append(_section_name(sec if isinstance(sec, dict) else {}, at[3] if isinstance(at[3], int) else 0))
    node = at_path(cfg, at)
    if isinstance(node, dict) and (node.get("type") or node.get("entity")) and len(at) > 2 and at[-2] in ("cards", "badges"):
        words.append(_label(node))
    return " › ".join(words)


def clean_at(at) -> list:
    out = []
    for step in at if isinstance(at, list) else []:
        if isinstance(step, bool):
            return []
        if isinstance(step, int) and 0 <= step < 1000:
            out.append(step)
        elif isinstance(step, str) and re.fullmatch(r"[a-z_]{1,20}", step):
            out.append(step)
        else:
            return []
    return out[:12]


# ------------------------------------------------------------ card types

TYPE_PREFIX = "custom:morph-type-"


def _walk(node, found: list) -> None:
    if isinstance(node, dict):
        t = node.get("type")
        if isinstance(t, str) and t.startswith(TYPE_PREFIX):
            found.append(t[len(TYPE_PREFIX):])
        for v in node.values():
            _walk(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk(v, found)


def type_usage(cfg: dict, key: str) -> dict[str, list[str]]:
    """Where each card type is used on one dashboard: slug -> places in
    words, a copy inside a stack counted at its stack's place."""
    out: dict[str, list[str]] = {}
    for w, card in places(cfg):
        found: list[str] = []
        _walk(card, found)
        for slug in found:
            out.setdefault(slug, []).append(f"{title_of(cfg, key)} › {w}")
    return out


def write_usage() -> dict:
    """types-usage.json: every type's copies across every dashboard brAIn
    keeps, read by the integration (the picker's description, the layer's
    "this one or every copy")."""
    every: dict[str, list[dict]] = {}
    for key in morphed():
        cfg, problem, _ = read(key)
        if problem or not cfg:
            continue
        for slug, wheres in type_usage(cfg, key).items():
            every.setdefault(slug, []).extend({"dashboard": key, "where": w} for w in wheres)
    data = {"types": every}
    if paths.read_json(paths.SHARED / "types-usage.json", {}) != data:
        paths.write_json(paths.SHARED / "types-usage.json", data)
    return data
