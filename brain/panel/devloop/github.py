"""The GitHub calls the loop makes, and nothing else.

urllib rather than a client library: five requests do not earn a
dependency, and the base URL is an environment variable so the tests can
point it at a real local HTTP server — a fake that accepts whatever it is
handed proves only that it matches the code that mocked it.

Every call answers ``(status, body)`` and never raises; the queue decides
what a failure means, because "GitHub is down" and "the token was
revoked" lead to different sentences on the screen.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import REPO_RE

API = os.environ.get("BRAIN_GITHUB_API", "https://api.github.com").rstrip("/")
TIMEOUT_S = 20
LABEL = "from-house"
# The marker the queue finds its own issue by, after a reinstall has lost
# the local record of which number it was. Inside an HTML comment, so it
# is in the body and not on the page.
MARKER = "<!-- brain-devloop-fp: {fp} -->"
# A body GitHub will take, with room left over. Its own limit is 65,536.
MAX_BODY = 60_000


def _call(token: str, method: str, path: str, payload: dict | None = None,
          ) -> tuple[int, object]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API + path, data=data, method=method, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "brain-devloop",
            **({"Content-Type": "application/json"} if data is not None else {}),
        })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 — fixed host
            raw = resp.read(2_000_000)
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read(200_000) if exc.fp else b""
        status = exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, {"message": f"could not reach GitHub: {exc}"}
    try:
        body = json.loads(raw.decode("utf-8", "replace")) if raw else {}
    except ValueError:
        body = {"message": raw[:200].decode("utf-8", "replace")}
    return status, body


def _message(status: int, body) -> str:
    msg = body.get("message") if isinstance(body, dict) else ""
    if status == 401:
        return "GitHub refused the token (expired or revoked) — set a new one"
    if status == 403:
        return ("the token cannot do this — it needs Issues: read and write "
                "on that repository" + (f" ({msg})" if msg else ""))
    if status == 404:
        return ("GitHub does not show this token that repository — check "
                "the name, and that the token was given access to it")
    if status == 0:
        return str(msg or "could not reach GitHub")
    return f"GitHub answered {status}" + (f": {msg}" if msg else "")


def check_repo(token: str, repo: str) -> tuple[bool, str]:
    """Whether reports may be sent there. A public repository is refused:
    a report is evidence about somebody's home, aliased or not."""
    if not REPO_RE.match(repo or ""):
        return False, "no repository set"
    status, body = _call(token, "GET", f"/repos/{repo}")
    if status != 200 or not isinstance(body, dict):
        return False, _message(status, body)
    if not body.get("private"):
        return False, (f"{repo} is public. Reports go only to a private "
                       "repository — make it private or pick another")
    return True, ""


def find_issue(token: str, repo: str, fp: str) -> tuple[int | None, str]:
    """The issue already filed for ``fp``, found by its marker in the body.

    Not by the label: GitHub drops labels on a new issue silently when the
    token's account may not set them, so a label filter would miss the
    loop's own issues and file every fault twice. Only the newest pages
    are read, which is enough for a queue that holds sixty fingerprints in
    a repository that exists for these reports."""
    marker = MARKER.format(fp=fp)
    for page in (1, 2, 3):
        status, body = _call(
            token, "GET", f"/repos/{repo}/issues?state=all&sort=created"
            f"&direction=desc&per_page=100&page={page}")
        if status != 200 or not isinstance(body, list):
            return None, _message(status, body)
        for row in body:
            if isinstance(row, dict) and marker in str(row.get("body") or ""):
                return int(row.get("number") or 0) or None, ""
        if len(body) < 100:
            break
    return None, ""


def list_issues(token: str, repo: str, pages: int = 3
                ) -> tuple[list[dict] | None, str]:
    """The newest issues with their state and labels: the request
    `find_issue` already makes, read for the verdict the cloud left on
    each one rather than for a marker. No new call, no new permission —
    Issues: read is what the token was given."""
    out: list[dict] = []
    for page in range(1, max(1, int(pages)) + 1):
        status, body = _call(
            token, "GET", f"/repos/{repo}/issues?state=all&sort=created"
            f"&direction=desc&per_page=100&page={page}")
        if status != 200 or not isinstance(body, list):
            return None, _message(status, body)
        out += [row for row in body if isinstance(row, dict)]
        if len(body) < 100:
            break
    return out, ""


def label_names(issue: dict) -> set[str]:
    """GitHub answers labels as objects; a string is read too, so a
    caller handing back what it sent is not read as unlabelled."""
    names = set()
    for label in (issue or {}).get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str):
            names.add(name)
    return names


def create_issue(token: str, repo: str, title: str, body: str,
                 labels: list[str] | None = None) -> tuple[dict | None, str]:
    status, out = _call(token, "POST", f"/repos/{repo}/issues", {
        "title": title[:250], "body": body[:MAX_BODY],
        "labels": labels or [LABEL]})
    if status != 201 or not isinstance(out, dict):
        return None, _message(status, out)
    return out, ""


def get_issue(token: str, repo: str, number: int) -> tuple[dict | None, str]:
    status, out = _call(token, "GET", f"/repos/{repo}/issues/{int(number)}")
    if status != 200 or not isinstance(out, dict):
        return None, _message(status, out)
    return out, ""


def comment(token: str, repo: str, number: int, text: str,
            reopen: bool = False) -> tuple[bool, str]:
    if reopen:
        status, out = _call(token, "PATCH", f"/repos/{repo}/issues/{int(number)}",
                            {"state": "open"})
        if status != 200:
            return False, _message(status, out)
    status, out = _call(token, "POST",
                        f"/repos/{repo}/issues/{int(number)}/comments",
                        {"body": text[:MAX_BODY]})
    if status != 201:
        return False, _message(status, out)
    return True, ""


def update_issue(token: str, repo: str, number: int, title: str, body: str
                 ) -> tuple[bool, str]:
    status, out = _call(token, "PATCH", f"/repos/{repo}/issues/{int(number)}",
                        {"title": title[:250], "body": body[:MAX_BODY]})
    if status != 200:
        return False, _message(status, out)
    return True, ""
