"""The dashboard's history: /config/morph is a git repository.

Every change is one commit, whoever made it — Edit, brAIn, an approved
suggestion, or somebody with a text editor — and Undo is a revert of that
commit. This is the reason Morph is an add-on with a service at all: Home
Assistant's own container does not promise a ``git`` binary, and the files
brAIn edits have to have a history brAIn's edits cannot skip.

Only this service runs ``git`` here. brAIn edits the files and leaves the
committing to Morph, which is told what each change was for (the request
that caused it) so the log reads as what happened rather than as "edit".

Three rules:

* **A change nobody announced is still committed** (`commit_pending`), as
  "Edited outside Morph", so a revert never takes somebody's hand edit with
  the next one.
* **Undo is a revert, never a reset.** Reset rewrites history; a revert is
  itself a commit, so undoing an undo is possible and the log stays the
  record of what the dashboard went through.
* **A commit's author says which face made it** (``person``, ``brain``,
  ``learning``, ``outside``), which is what the learning loop reads to tell
  a change brAIn made that a person then undid from one a person made.
"""
from __future__ import annotations

import os
import subprocess
import threading

import morphcode
import paths

AUTHORS = {
    "person": "Morph Edit <edit@morph.local>",
    "brain": "brAIn <brain@morph.local>",
    "learning": "Morph learning <learning@morph.local>",
    "outside": "Outside Morph <outside@morph.local>",
    "morph": "Morph <morph@morph.local>",
}

# git refuses two writers at once (index.lock) and a tell's commit, a save
# and the watcher run in different threads, so every mutation takes this.
_LOCK = threading.RLock()

GITIGNORE = "# Morph's own scratch files\n.morph-*\n*.tmp\n"


def _git(*args: str, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    return subprocess.run(
        ["git", "-c", "safe.directory=*", "-c", "core.quotepath=off", *args],
        cwd=str(paths.MORPH_DIR), capture_output=True, text=True,
        timeout=timeout, env=env, check=check)


def ensure() -> None:
    paths.MORPH_DIR.mkdir(parents=True, exist_ok=True)
    if not (paths.MORPH_DIR / ".git").is_dir():
        _git("init", "-q")
        _git("config", "user.name", "Morph")
        _git("config", "user.email", "morph@morph.local")
    ignore = paths.MORPH_DIR / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE, encoding="utf-8")


def head() -> str:
    r = _git("rev-parse", "--short=12", "HEAD", check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def dirty() -> bool:
    r = _git("status", "--porcelain", check=False)
    return bool(r.stdout.strip())


def commit(message: str, who: str = "morph") -> str:
    with _LOCK:
        return _commit_locked(message, who)


def _commit_locked(message: str, who: str = "morph") -> str:
    """Commit everything that changed. Returns the new head, or "" when
    there was nothing to commit — which is an answer, not a failure."""
    ensure()
    # A change to Morph's own code is committed with the record of which
    # Morph it was written against (morphcode.py), so Undo puts both back.
    try:
        morphcode.record_bases()
    except Exception:  # noqa: BLE001 — a record is a convenience; the commit is not
        pass
    _git("add", "-A")
    if not _git("diff", "--cached", "--quiet", check=False).returncode:
        return ""
    _git("commit", "-q", "--author", AUTHORS.get(who, AUTHORS["morph"]),
         "-m", (message or "Changed the dashboard").strip()[:2000])
    _give_back()
    return head()


def commit_pending() -> str:
    with _LOCK:
        return _commit_pending_locked()


def _commit_pending_locked() -> str:
    if not dirty():
        return ""
    return commit("Edited outside Morph", "outside")


def _give_back() -> None:
    """Everything outside .git goes to brAIn's uid, so its next edit is an
    in-place write it is allowed to make."""
    if os.geteuid() != 0:
        return
    for root, dirs, files in os.walk(paths.MORPH_DIR):
        if ".git" in dirs:
            dirs.remove(".git")
        for name in dirs + files:
            full = os.path.join(root, name)
            try:
                if not os.path.islink(full):
                    os.chown(full, paths.BRAIN_UID, paths.BRAIN_UID)
            except OSError:
                pass  # ownership is a convenience; brAIn's edit hook hands a file back anyway


def revert(sha: str, message: str = "") -> tuple[bool, str]:
    with _LOCK:
        return _revert_locked(sha, message)


def _revert_locked(sha: str, message: str = "") -> tuple[bool, str]:
    """Revert one commit. Refuses a sha that is not a commit in this
    repository, and backs out cleanly when the revert conflicts with what
    came after (the person is told which, rather than left with a file full
    of conflict markers that the dashboard cannot read)."""
    if not sha or not all(c in "0123456789abcdef" for c in sha.lower()) or len(sha) > 40:
        return False, "That is not a version of this dashboard."
    if _git("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode:
        return False, "That version is not in this dashboard's history."
    commit_pending()
    r = _git("revert", "--no-edit", "--no-commit", sha, check=False)
    if r.returncode:
        _git("revert", "--abort", check=False)
        _git("reset", "-q", "--hard", "HEAD", check=False)
        return False, ("A later change touched the same lines, so this one cannot be "
                       "undone on its own. Restore an earlier version from Settings → History.")
    subject = _git("log", "-1", "--format=%s", sha, check=False).stdout.strip()
    full = _git("rev-parse", sha, check=False).stdout.strip()
    new = commit(f"{message or 'Undid: ' + subject}\n\nThis reverts commit {full}.", "person")
    return True, new


def restore(sha: str) -> tuple[bool, str]:
    with _LOCK:
        return _restore_locked(sha)


def _restore_locked(sha: str) -> tuple[bool, str]:
    """Put the dashboard back as it was at one version — as a NEW commit,
    so restoring is itself undoable."""
    if not sha or not all(c in "0123456789abcdef" for c in sha.lower()) or len(sha) > 40:
        return False, "That is not a version of this dashboard."
    if _git("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode:
        return False, "That version is not in this dashboard's history."
    commit_pending()
    _git("checkout", sha, "--", ".")
    subject = _git("log", "-1", "--format=%s", sha, check=False).stdout.strip()
    new = commit(f"Restored the version from “{subject}”", "person")
    return True, new


def log(limit: int = 60, path: str = "") -> list[dict]:
    """The newest commits (only those touching ``path`` when given)."""
    args = ["log", f"-{max(1, min(500, limit))}", "--abbrev=12", "--format=%h%x1f%an%x1f%at%x1f%s"]
    if path:
        args += ["--", path]
    r = _git(*args, check=False)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        who = next((k for k, v in AUTHORS.items() if v.split(" <")[0] == parts[1]), "outside")
        out.append({"sha": parts[0], "who": who, "at": int(parts[2] or 0), "message": parts[3]})
    return out


def changed_files(sha: str) -> list[str]:
    r = _git("show", "--name-only", "--format=", sha, check=False)
    return [x for x in r.stdout.splitlines() if x.strip()]


def diff(sha: str, prefix: str = "", limit: int = 12000, exclude: str = "") -> str:
    """What one commit changed, as a patch (under ``prefix`` only when
    given, and never under ``exclude``), cut at ``limit`` characters with a
    line saying so."""
    args = ["show", "--format=", "--no-color", sha]
    if prefix or exclude:
        args += ["--", prefix or "."]
        if exclude:
            args.append(f":(exclude){exclude}")
    out = _git(*args, check=False).stdout
    return out if len(out) <= limit else out[:limit] + f"\n… (cut: {len(out) - limit} more characters)\n"


def file_at(sha: str, path: str) -> str | None:
    """A file's text as it was at ``sha``; None when it did not exist then
    (or there is no such commit), which is a different answer from empty."""
    if not sha:
        return None
    r = _git("show", f"{sha}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def is_reverted(sha: str) -> bool:
    """Whether a later commit undid this one — the signal the learning loop
    reads as "a person did not keep this"."""
    r = _git("log", "--format=%s%n%b", f"{sha}..HEAD", check=False)
    full = _git("rev-parse", sha, check=False).stdout.strip()
    text = r.stdout
    return bool(full and f"This reverts commit {full}" in text)
