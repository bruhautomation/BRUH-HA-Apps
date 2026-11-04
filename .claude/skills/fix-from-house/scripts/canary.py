#!/usr/bin/env python3
"""Read the house's canary for a release and say which PRs to revert.

Section 0 of the self-learning plan: with no person in the loop, the house
is the judge of a release. Within hours of installing one it files (or
rewrites) an issue titled ``[canary] <product> <version>`` whose body holds

    ```json brain-canary
    {"v":1,"product":…,"release":…,"installed_at":ISO,"checked_at":ISO,
     "window_hours":24,"new_faults":[{"fp","what"[,"where"]}],"came_back":[fp],
     "scorecard_drops":[{"producer","before","after"}],"start_crash":bool,
     "verdict":"pending"|"healthy"|"regressed","digest":…}
    ```

signed like every house block (``ffh_common``). On ``regressed`` this works
out the revert plan, deterministically:

- each signal is attributed to the PR it points at: a came-back fingerprint
  to the PR that closed it (``fps``); a new fault's ``where`` or a dropped
  producer to the PR whose files it names;
- when every signal is attributed, only those PRs are reverted;
- when any signal is not (a crash on start always is not), every devloop PR
  of the release is.

Each revert is a whole-PR revert PR (``devloop/revert-<n>``, tier B), its
issues reopened with ``devloop:came-back`` and what broke, and retried one
model tier higher, never past Opus: an Opus (or Fable) fix that broke is
``decline`` unless the run spends its one Fable attempt on it by hand.

    canary.py plan --config .claude/devloop.json --issue CANARY.json --prs PRS.json
                   [--since-release X.Y.Z]

PRS.json lists the merged devloop PRs: ``{"number", "title", "head_ref",
"product", "release", "files": [...], "issues": [n...], "fps": [...],
"model", "reverted"}`` (``release`` is the version the PR bumped to).
Without ``--since-release`` the release's own PRs are candidates; with it,
every PR after that release up to this one (a house that skipped versions).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ffh_common as C  # noqa: E402

TAG = "brain-canary"
TITLE = re.compile(r"^\[canary\]\s+(?P<product>.+?)\s+(?P<release>\d+(?:\.\d+)+)\s*$")

REQUIRED = {
    "v": int, "product": str, "release": str, "installed_at": str,
    "checked_at": str, "window_hours": (int, float), "new_faults": list,
    "came_back": list, "scorecard_drops": list, "start_crash": bool,
    "verdict": str,
}
VERDICTS = ("pending", "healthy", "regressed")
REVERT_TIER = "B"
FILE_EXTS = {"py", "js", "mjs", "ts", "css", "html", "sh", "json", "yaml", "yml",
             "md", "conf", "txt", "java", "kt"}


def _vkey(version: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", version or ""))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def same_product(a: str, b: str) -> bool:
    sa, sb = _slug(a), _slug(b)
    return bool(sa) and (sa == sb or sa.replace("-", "") == sb.replace("-", ""))


def read_canary(issue: dict, house_login: str | None) -> tuple[dict | None, str]:
    author = C.author_of(issue)
    obj, why = C.one_verified(issue.get("body"), TAG, author, house_login, REQUIRED)
    if obj is None:
        return None, why
    if obj["verdict"] not in VERDICTS:
        return None, f"unknown verdict {obj['verdict']!r}"
    m = TITLE.match((issue.get("title") or "").strip())
    if not m:
        return None, "title is not [canary] <product> <version>"
    if (not same_product(m.group("product"), obj["product"])
            or m.group("release") != obj["release"]):
        return None, "title and block disagree"
    return obj, "ok"


def _where_tokens(where: str) -> list[str]:
    """The path-ish forms a ``where`` can name a file by."""
    w = (where or "").strip().strip("`")
    w = re.sub(r":\d+(?::\d+)?$", "", w)          # path:line
    w = re.sub(r"\s.*$", "", w)                    # "path (detail)"
    if not w:
        return []
    out = [w.strip("/")]
    if "/" not in w and "." in w and w.rsplit(".", 1)[1].lower() not in FILE_EXTS:
        out.append(w.replace(".", "/"))            # module form a.b.c
    return [t for t in out if len(t) >= 3]


def file_matches(path: str, token: str) -> bool:
    path = path.strip("/")
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", path)
    return (path == token or path.endswith("/" + token)
            or stem == token or stem.endswith("/" + token)
            or path.startswith(token.rstrip("/") + "/")
            or ("/" + token.rstrip("/") + "/") in ("/" + path))


def _prs_for_where(where: str, prs: list[dict]) -> list[int]:
    hits = []
    for token in _where_tokens(where):
        for pr in prs:
            if any(file_matches(f, token) for f in pr.get("files") or []):
                hits.append(pr["number"])
    return sorted(set(hits))


def _signals(canary: dict) -> list[dict]:
    out = []
    if canary.get("start_crash"):
        out.append({"kind": "start_crash", "what": "the add-on crashed on start"})
    for fault in canary.get("new_faults") or []:
        if isinstance(fault, dict):
            out.append({"kind": "new_fault", "fp": fault.get("fp"),
                        "what": fault.get("what") or "",
                        "where": fault.get("where") or ""})
    for fp in canary.get("came_back") or []:
        out.append({"kind": "came_back", "fp": fp, "what": f"came back: {fp}"})
    for drop in canary.get("scorecard_drops") or []:
        if isinstance(drop, dict):
            out.append({"kind": "scorecard_drop", "producer": drop.get("producer"),
                        "what": (f"{drop.get('producer')} fell from "
                                 f"{drop.get('before')} to {drop.get('after')}"),
                        "where": drop.get("producer") or ""})
    return out


def candidates(prs: list[dict], product: str, release: str,
               since: str | None) -> list[dict]:
    out = []
    top = _vkey(release)
    low = _vkey(since) if since else None
    for pr in prs:
        if not same_product(pr.get("product") or "", product):
            continue
        if pr.get("reverted") or (pr.get("head_ref") or "").startswith("devloop/revert-"):
            continue
        v = _vkey(pr.get("release") or "")
        if low is None and v != top:
            continue
        if low is not None and not (low < v <= top):
            continue
        out.append(pr)
    return sorted(out, key=lambda p: p["number"])


def attribute(signal: dict, prs: list[dict]) -> list[int]:
    if signal["kind"] == "start_crash":
        return []
    if signal["kind"] == "came_back":
        return sorted(p["number"] for p in prs if signal["fp"] in (p.get("fps") or []))
    return _prs_for_where(signal.get("where") or "", prs)


def plan(canary: dict | None, why: str, prs: list[dict],
         since: str | None = None) -> dict:
    if canary is None:
        return {"action": "none", "reason": f"unverified canary: {why}"}
    base = {"product": canary["product"], "release": canary["release"],
            "verdict": canary["verdict"]}
    if canary["verdict"] == "pending":
        return {**base, "action": "wait", "reason": "the house has not decided yet"}
    if canary["verdict"] == "healthy":
        return {**base, "action": "none", "reason": "healthy"}
    pool = candidates(prs, canary["product"], canary["release"], since)
    signals = _signals(canary)
    if not pool:
        return {**base, "action": "none",
                "reason": "regressed, but no unreverted devloop PR is in this release",
                "signals": signals}
    blamed: dict[int, list[str]] = {}
    unattributed = []
    for signal in signals:
        who = attribute(signal, pool)
        if not who:
            unattributed.append(signal)
        for n in who:
            blamed.setdefault(n, []).append(signal["what"])
    if unattributed or not signals:
        mode = "all"
        chosen = pool
        for pr in pool:
            blamed.setdefault(pr["number"], []).extend(s["what"] for s in unattributed)
    else:
        mode = "attributed"
        chosen = [p for p in pool if p["number"] in blamed]
    reverts = []
    for pr in chosen:
        up = C.escalate_model(pr.get("model"))
        reverts.append({
            "pr": pr["number"],
            "branch": f"devloop/revert-{pr['number']}",
            "tier": REVERT_TIER,
            "title": f"Revert #{pr['number']}: {pr.get('title') or ''}".strip(),
            "reopen": list(pr.get("issues") or []),
            "label": "devloop:came-back",
            "what_broke": blamed.get(pr["number"]) or ["the release regressed"],
            "retry_model": up,
            "decline": up is None,
        })
    return {**base, "action": "revert", "mode": mode, "signals": signals,
            "unattributed": unattributed, "reverts": reverts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--config", default=".claude/devloop.json")
    p.add_argument("--house-login", default=None)
    p.add_argument("--issue", required=True)
    p.add_argument("--prs", required=True)
    p.add_argument("--since-release", default=None)
    args = ap.parse_args(argv)
    house = args.house_login or C.load_config(args.config).get("house_login")
    canary, why = read_canary(C.load_json(args.issue), house)
    out = plan(canary, why, C.load_json(args.prs), args.since_release)
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
