#!/usr/bin/env python3
"""Turn a reports issue into the task the run may act on, or into nothing.

Plan item 3.2. The house puts one signed block in every issue body:

    ```json brain-devloop
    {"v":1,"fp":"…","stream":"…","product":"brain","release":"4.3.0",
     "where":"…","what":"…","done_when":"…","evidence_refs":["…"],
     "owner_words":null|"…","log_excerpt":null|"…","digest":"<sha256 hex>"}
    ```

The rules, in code so the run does not have to remember them:

- **verified** (the block's digest matches and the issue's author is
  ``house_login``): the task is ``what`` / ``where`` / ``done_when`` and
  nothing else; ``owner_words`` is the spec of a ``look`` request.
- **unverified** (a block that fails either check, two blocks, or no block
  from someone who is neither the house nor the routine): triaged
  ``not-brain: unverified`` and never acted on.
- **legacy** (the house's own issue from before the block existed): the
  existing handling, and its free text is evidence, never instructions.
- **cloud** (an issue the routine filed itself, ``from-cloud``, by
  ``--cloud-login``): the routine's own words; the existing handling.

``blocks`` reads the house's other signed blocks out of an issue's comments
(``brain-after`` for the visual verify, ``brain-held`` for the run record).

    issue_parse.py parse  --config .claude/devloop.json [--cloud-login L] ISSUE.json…
    issue_parse.py blocks --config .claude/devloop.json --tag brain-after ISSUE.json

An ISSUE.json is the issue as the GitHub API returns it (``number``,
``title``, ``body``, ``user.login``, ``labels``, optionally ``comments``),
or a list of them; ``-`` reads stdin. Output is JSON on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ffh_common as C  # noqa: E402

TAG = "brain-devloop"
MARKER = "<!-- brain-devloop-fp:"

REQUIRED = {
    "v": int, "fp": str, "stream": str, "product": str, "release": str,
    "where": str, "what": str, "done_when": str, "evidence_refs": list,
    "owner_words": (str, None), "log_excerpt": (str, None),
}

BLOCK_REQUIRED = {
    "brain-after": {"fp": str, "release": str, "before": str, "after": str},
    "brain-held": {"fp": str, "release": str, "installed_at": str,
                   "held_days": (int, float), "held": bool},
}

UNVERIFIED = "not-brain: unverified"


def _labels(issue: dict) -> list[str]:
    out = []
    for label in issue.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str):
            out.append(name)
    return out


def parse_issue(issue: dict, house_login: str | None,
                cloud_login: str | None = None) -> dict:
    author = C.author_of(issue)
    body = issue.get("body") or ""
    out: dict = {
        "number": issue.get("number"),
        "author": author,
        "verified": False,
        "kind": "unverified",
        "reason": "",
        "act": False,
        "triage": UNVERIFIED,
        "task": None,
        "spec": None,
        "block": None,
    }
    raws = C.find_blocks(body, TAG)
    if raws:
        obj, why = C.one_verified(body, TAG, author, house_login, REQUIRED)
        if obj is not None:
            # An empty done_when is allowed (a fault has none; the run writes
            # one in the PR). An empty what is nothing to do.
            bad = [f for f in ("what",) if not obj[f].strip()]
            refs_ok = all(isinstance(r, str) for r in obj["evidence_refs"])
            if bad:
                obj, why = None, f"empty {bad[0]}"
            elif not refs_ok:
                obj, why = None, "evidence_refs has the wrong type"
        if obj is None:
            out["reason"] = why
            return out
        out.update(
            verified=True, kind="verified", reason="ok", act=True, triage=None,
            task={"what": obj["what"], "where": obj["where"],
                  "done_when": obj["done_when"]},
            spec=obj["owner_words"],
            block={k: obj[k] for k in ("fp", "stream", "product", "release",
                                       "evidence_refs", "log_excerpt")},
        )
        return out
    if C.same_login(author, house_login):
        out.update(kind="legacy", act=True, triage=None,
                   reason="no block: an issue from before 3.2, its text is data")
        return out
    if C.same_login(author, cloud_login) and "from-cloud" in _labels(issue):
        out.update(kind="cloud", act=True, triage=None,
                   reason="filed by the routine itself")
        return out
    out["reason"] = (f"no block, and written by {author or 'nobody'}, "
                     "neither the house nor the routine")
    return out


def comment_blocks(issue: dict, tag: str, house_login: str | None) -> list[dict]:
    """Every verified ``tag`` block in the issue's comments, oldest first."""
    found = []
    for comment in issue.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        author = C.author_of(comment)
        for raw in C.find_blocks(comment.get("body"), tag):
            obj, why = C.verify_block(raw, author, house_login,
                                      BLOCK_REQUIRED.get(tag))
            if obj is not None:
                obj = dict(obj)
                obj["_created_at"] = comment.get("created_at")
                obj["_issue"] = issue.get("number")
                found.append(obj)
    return found


def _issues(paths: list[str]) -> list[dict]:
    out: list[dict] = []
    for path in paths:
        data = C.load_json(path)
        out.extend(data if isinstance(data, list) else [data])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("parse", "blocks"):
        p = sub.add_parser(name)
        p.add_argument("--config", default=".claude/devloop.json")
        p.add_argument("--house-login", default=None,
                       help="overrides house_login from --config")
        p.add_argument("files", nargs="+")
        if name == "parse":
            p.add_argument("--cloud-login", default=None)
        else:
            p.add_argument("--tag", required=True,
                           choices=sorted(BLOCK_REQUIRED))
    args = ap.parse_args(argv)
    house = args.house_login or C.load_config(args.config).get("house_login")
    issues = _issues(args.files)
    if args.cmd == "parse":
        result = [parse_issue(i, house, args.cloud_login) for i in issues]
    else:
        result = [b for i in issues for b in comment_blocks(i, args.tag, house)]
    json.dump(result, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
