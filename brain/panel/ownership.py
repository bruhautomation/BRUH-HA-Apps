"""Hand Home Assistant's config files to the ``claude`` user, safely.

Claude Code runs as the ``claude`` user (``claude-run`` drops to it with
su-exec, because the CLI refuses some of its own flags as root), while
Home Assistant Core and this panel run as root. ``run.sh`` gives the
``claude`` user ``/config`` itself, ``/config/.brain`` and
``/config/custom_components`` at boot, and the user-editable config besides
(``own_ha_config``) — and that is not enough on its own, because ownership
drifts back. Core's UI editors save ``automations.yaml``, ``scripts.yaml``
and ``scenes.yaml`` by writing a temporary file and renaming it over the
old one, as root, so a file handed over at boot is root's again after the
next save from the automation editor. The run that met one of those
answered the only way it could: *"Run sudo chown claude /config/scenes.yaml
/config/scripts.yaml and I'll apply the rest."* Nobody should have to type
that, and nobody should have to know why.

So there are three doors and one implementation:

* the ``PreToolUse`` edit hook asks, before a Write or Edit reaches a file
  it cannot write (``scripts/brain_own.py``, called from
  ``brain-edit-snapshot.py``);
* ``brain own <path...>`` asks, for anything else — a shell redirect, a
  ``sed -i`` into a root-owned file;
* the scheduler sweeps the top-level YAML about once a minute
  (``SWEEP_INTERVAL_S``), which is what catches a UI save before anybody
  meets it — and it gives each ``/addon_configs/<slug>`` folder back too,
  so an add-on installed after boot is covered.

The shell has its own half of the first door: ``brain-protect-hook.py``,
which already reads every Bash command, asks about the paths a command
names (``brain_own.ensure_writable_command``), because a shell redirect
or ``open(..., "w")`` writes in place and the Edit tool's rename does not.

It is not only ``/config``. ``run.sh`` hands ``/addon_configs``,
``/share``, ``/media`` and ``/addons`` to the ``claude`` user too when
their mapping is on, and they drift back the same way — an add-on
installed after boot gets a root-owned ``/addon_configs/<slug>``, and
Zigbee2MQTT and Node-RED rewrite their own config as root — so every
check below is made against whichever of those trees the path is in
(``atomic_write.handover_roots``, the one list).

The first two reach ``POST /api/own`` on loopback; the panel is the one
process here that is root, and ``own`` is the one function that chowns.

What it will and will not hand over is the whole of the design, because a
root process that chowns paths a less-privileged user names is exactly the
shape of a privilege escalation. Every path is checked on the object it
finally names, not on the string it arrived as:

* **Inside a handed-over tree, on the real path.** ``/config/../etc/shadow``
  is lexically under ``/config`` and is not in it, and a folder inside
  ``/config`` can itself be a link somewhere else. The file is opened
  ``O_NOFOLLOW`` and the location is read back off the open descriptor, so
  what is checked and what is chowned are the same inode — a name swapped
  for a link between the check and the chown changes nothing.
* **A symbolic link is answered for its target, never through it.** A
  ``scenes.yaml`` that links into a git-managed folder is resolved once and
  the target is checked exactly as if it had been named — the real path,
  the refuse list, the hard links, the inode — so a link that leads
  outside is refused as the outside path it is. A walk never descends into
  a link.
* **A file or a folder, nothing else.** A FIFO, a socket or a device has no
  business being handed to anybody, and opening one can have side effects;
  the type is read with ``lstat`` before anything is opened.
* **One name only.** A regular file with more than one hard link has a name
  somewhere this cannot see.
* **Not on the refuse list.** ``.storage`` is Core's own state, rewritten
  continuously, and editing it under a running Core is wrong whoever owns
  it; ``.cloud`` is the Home Assistant Cloud sign-in; ``.brain/secrets`` is
  where brAIn keeps credentials; ``secrets.yaml`` is somewhere brAIn keeps
  its hands off (the context file says so, and the edit journal never
  snapshots it); the recorder's database is written by Core every second.

Nothing here gives the ``claude`` user anything it could not already take:
it owns ``/config``, and the owner of a folder can rename a new file over
any entry in it. What changes is that an in-place write — the one a shell
redirect makes, and the one a person was asked to fix with sudo — works.
That is also why a hand-over gives the owner the write bit (``_writable``):
a file somebody made read-only (a Samba copy, a restored backup, a
``chmod``) is still unwritable once it is ``claude``'s, and an answer of
"handed over" about a file Claude still cannot write is the edit failing
with nothing left to try.

Stdlib plus ``atomic_write`` (for the one answer to "where is the config
folder"); importable by the panel and by nothing that runs as ``claude``.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import stat
import time

import atomic_write

log = logging.getLogger("brain.ownership")

# The user Claude Code runs as. run.sh creates it as UID 1000; a box with
# no such user (a dev checkout) hands nothing to anybody.
OWNER_USER = "claude"

# How often the scheduler re-owns the top-level YAML Core's editors rewrite:
# about every tick (the tick is a minute, and asyncio may wake a hair early).
# It is one scandir of /config and one of /addon_configs, and the window it
# leaves is the window a shell write into a just-saved scenes.yaml meets.
SWEEP_INTERVAL_S = 50

# Bounds on one request, and on a recursive one's walk.
MAX_PATHS = 50
MAX_RECURSIVE = 5000

# Relative to the config folder, compared component by component. The
# other trees have none of these; the names and prefixes apply everywhere.
REFUSED_DIRS = {
    ".storage": "Home Assistant rewrites .storage all the time, and editing it "
                "under a running Home Assistant is not safe; the registry "
                "tools are the way to change what is in there",
    ".cloud": "that is the Home Assistant Cloud sign-in",
    ".brain/secrets": "that is where brAIn keeps credentials",
}
REFUSED_NAMES = {
    "secrets.yaml": "brAIn does not take over secrets.yaml",
}
REFUSED_PREFIXES = {
    "home-assistant_v2.db": "the recorder writes its database continuously",
}
YAML_SUFFIXES = (".yaml", ".yml")

LOOPBACK_ONLY = ("forbidden: /api/own answers only processes inside the "
                 "add-on (the edit hook and `brain own`)")

# The add-on config folder's variable: the sweep gives each add-on's own
# folder back, because the Supervisor creates it root-owned on install.
ADDON_CONFIG_VAR = "ADDON_CONFIG_DIR"

# What a Claude run that edits files is told — the chat's appended prompt
# carries it, and /config/CLAUDE.md (ha-context-gen.sh) says the same.
AGENT_RULE = ("If a file under /config (or /addon_configs, /share or /media) "
              "is not writable, run `brain own <path>` (the edit hooks "
              "usually do it for you first). Never ask the person to run "
              "sudo or chown.")


class Refused(Exception):
    """The whole request cannot be honoured; carries the HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def config_dir() -> str:
    """The config folder, spelled once — `atomic_write` owns the answer."""
    return atomic_write.CONFIG_DIR


def owner() -> tuple[int, int] | None:
    """The uid and gid files are handed to, or None where there is no such
    user."""
    try:
        import pwd
        entry = pwd.getpwnam(OWNER_USER)
    except (KeyError, ImportError, OSError):
        return None
    return entry.pw_uid, entry.pw_gid


def _inside(path: str, root: str) -> bool:
    root = root.rstrip(os.sep) or os.sep
    return path == root or path.startswith(root + os.sep)


def roots() -> list[str]:
    """Every tree a path may be handed over in, the config folder first —
    `atomic_write.handover_roots`, so there is one list."""
    return atomic_write.handover_roots()


def roots_named() -> str:
    """The trees, as a sentence names them."""
    names = roots() or [config_dir()]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " or " + names[-1]


def refused_dirs_for(root: str) -> dict:
    """The refused folders inside one tree: the config folder's list there,
    nothing anywhere else."""
    return REFUSED_DIRS if root == os.path.normpath(config_dir()) else {}


def _root_holding(path: str, real: bool = False) -> str | None:
    """The tree a path is in — compared lexically, or on the trees' real
    paths when ``real`` — answered as the tree's lexical name; the deepest
    wins, so a tree inside another is still its own. None when outside all
    of them."""
    best = None
    for root in roots():
        top = os.path.realpath(root) if real else root
        if top.rstrip(os.sep) and _inside(path, top):
            if best is None or len(top) > len(best[1]):
                best = (root, top)
    return best[0] if best else None


def _writable(st) -> int | None:
    """The mode that lets the owner write this file (or make entries in this
    folder), or None when it already does."""
    want = stat.S_IRUSR | stat.S_IWUSR
    if stat.S_ISDIR(st.st_mode):
        want |= stat.S_IXUSR
    mode = stat.S_IMODE(st.st_mode)
    return None if mode & want == want else mode | want


def _hand_over(fd: int, st, uid: int, gid: int) -> int:
    """Give an open file or folder to (uid, gid) and let the owner write
    it. 1 when anything changed, 0 when it was already so."""
    changed = 0
    if (st.st_uid, st.st_gid) != (uid, gid):
        os.fchown(fd, uid, gid)
        changed = 1
    mode = _writable(st)
    if mode is not None:
        os.fchmod(fd, mode)
        changed = 1
    return changed


_OPEN = (os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY
         | getattr(os, "O_CLOEXEC", 0))


def _hand_over_entry(name: str, dirfd: int, st, uid: int, gid: int) -> int:
    """`_hand_over` for a regular file named in an open folder, on the inode
    ``st`` described: opened ``O_NOFOLLOW`` and compared, so a name swapped
    for a link (or another file) after it was looked at is left alone."""
    if (st.st_uid, st.st_gid) == (uid, gid) and _writable(st) is None:
        return 0
    fd = os.open(name, _OPEN, dir_fd=dirfd)
    try:
        now = os.fstat(fd)
        if ((now.st_dev, now.st_ino) != (st.st_dev, st.st_ino)
                or not stat.S_ISREG(now.st_mode) or now.st_nlink > 1):
            return 0
        return _hand_over(fd, now, uid, gid)
    finally:
        os.close(fd)


def refusal_for(rel: str, refused_dirs: dict | None = None) -> str:
    """Why a path — relative to its tree, real — may not be handed over, or
    '' when it may. ``refused_dirs`` defaults to the config folder's."""
    parts = [p for p in rel.split(os.sep) if p and p != "."] if rel else []
    refused_dirs = REFUSED_DIRS if refused_dirs is None else refused_dirs
    for folder, why in refused_dirs.items():
        want = folder.split("/")
        if parts[:len(want)] == want:
            return why
    name = parts[-1] if parts else ""
    if name in REFUSED_NAMES:
        return REFUSED_NAMES[name]
    for prefix, why in REFUSED_PREFIXES.items():
        if name.startswith(prefix):
            return why
    return ""


def _fd_path(fd: int, fallback: str) -> str:
    """Where an open descriptor really is. `/proc` answers for the inode
    itself; the fallback is only for a system without it."""
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return os.path.realpath(fallback)


def _answer(raw, ok: bool, reason: str = "", changed: int = 0,
            skipped: int = 0, truncated: bool = False) -> dict:
    row = {"path": raw if isinstance(raw, str) else repr(raw)[:200],
           "ok": ok, "changed": changed}
    if reason:
        row["reason"] = reason
    if skipped:
        row["skipped"] = skipped
    if truncated:
        row["truncated"] = True
    return row


def _walk(fd: int, rel: str, uid: int, gid: int,
          refused_dirs: dict | None = None) -> tuple[int, int, bool]:
    """Hand over everything under an already-checked folder.

    `os.fwalk` from the folder's own descriptor, never its name, and never
    following a link — the walk is the same inode the checks were made on,
    all the way down. Refused subtrees are pruned rather than visited, a
    link or a special file is skipped, and a file with other hard links is
    skipped and counted.
    """
    changed = skipped = seen = 0
    for dirpath, dirnames, filenames, dirfd in os.fwalk(
            ".", dir_fd=fd, follow_symlinks=False):
        here = os.path.normpath(os.path.join(rel, dirpath))
        dirnames[:] = [d for d in dirnames
                       if not refusal_for(os.path.join(here, d), refused_dirs)]
        if dirpath != ".":
            seen += 1
            changed += _hand_over(dirfd, os.fstat(dirfd), uid, gid)
        for name in filenames:
            seen += 1
            if seen > MAX_RECURSIVE:
                return changed, skipped, True
            try:
                st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or refusal_for(
                    os.path.join(here, name), refused_dirs):
                continue
            if st.st_nlink > 1:
                skipped += 1
                continue
            try:
                changed += _hand_over_entry(name, dirfd, st, uid, gid)
            except OSError:
                continue
        if seen > MAX_RECURSIVE:
            return changed, skipped, True
    return changed, skipped, False


def _through_link(raw: str, path: str, uid: int, gid: int,
                  recursive: bool) -> dict:
    """A symbolic link, answered for its target.

    Resolved once, and the target is then handed over exactly as if it had
    been named — every check below runs on it — so this grants nothing
    naming the target would not. A link out of the trees is refused as the
    outside path it leads to, and the answer says where it leads, which is
    the one thing a refusal about a link has to say to be acted on.
    """
    target = os.path.realpath(path)
    row = own_one(target, uid, gid, recursive, _follow=False)
    row["path"] = raw
    row["target"] = target
    if not row["ok"]:
        row["reason"] = (f"it is a link to {target}, and "
                         f"{row.get('reason') or 'that was refused'}")
    return row


def own_one(raw, uid: int, gid: int, recursive: bool = False,
            _follow: bool = True) -> dict:
    """Hand one path to (uid, gid), or say why not. Never raises."""
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        return _answer(raw, False, "not a path")
    if not os.path.isabs(raw):
        return _answer(raw, False, "give the whole path, starting with "
                                   + config_dir())
    path = os.path.normpath(raw)
    # Lexical first, for a cheap answer to `../`; the real path read off
    # the open descriptor below is the one that decides.
    if _root_holding(path) is None and _root_holding(path, real=True) is None:
        return _answer(raw, False, f"it is outside {roots_named()}")
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return _answer(raw, False, "there is nothing there")
    except OSError as exc:
        return _answer(raw, False, exc.strerror or str(exc))
    if stat.S_ISLNK(before.st_mode):
        if not _follow:
            return _answer(raw, False, "it is still a symbolic link after "
                                       "following one, and brAIn follows one "
                                       "at most")
        return _through_link(raw, path, uid, gid, recursive)
    if not (stat.S_ISREG(before.st_mode) or stat.S_ISDIR(before.st_mode)):
        return _answer(raw, False, "it is not a file or a folder")
    try:
        fd = os.open(path, _OPEN)
    except OSError as exc:
        return _answer(raw, False, exc.strerror or str(exc))
    try:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) != (before.st_dev, before.st_ino):
            return _answer(raw, False, "it changed while brAIn was looking")
        real = _fd_path(fd, path)
        root = _root_holding(real, real=True)
        if root is None:
            return _answer(raw, False, f"it leads outside {roots_named()}")
        top = os.path.realpath(root)
        rel = os.path.relpath(real, top) if real != top else ""
        refused = refused_dirs_for(root)
        why = refusal_for(rel, refused)
        if why:
            return _answer(raw, False, why)
        if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
            return _answer(raw, False, "it has other hard links, and brAIn "
                                       "will not hand over a file it cannot "
                                       "see every name of")
        if recursive and stat.S_ISDIR(st.st_mode) and not rel:
            return _answer(raw, False, f"name a folder inside {root}, not "
                                       "the whole of it")
        changed = _hand_over(fd, st, uid, gid)
        if recursive and stat.S_ISDIR(st.st_mode):
            more, skipped, truncated = _walk(fd, rel, uid, gid, refused)
            return _answer(raw, True, changed=changed + more,
                           skipped=skipped, truncated=truncated)
        return _answer(raw, True, changed=changed)
    except OSError as exc:
        return _answer(raw, False, exc.strerror or str(exc))
    finally:
        os.close(fd)


def own(paths, recursive: bool = False) -> dict:
    """Hand each named path to the `claude` user; one answer per path.

    Raises `Refused` for a request that cannot be honoured at all — a body
    with no paths, too many, a panel that is not root, or a box with no
    `claude` user — and otherwise answers every path, ok or not, in order.
    """
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not paths:
        raise Refused("name at least one path: {\"paths\": [\"/config/...\"]}")
    if len(paths) > MAX_PATHS:
        raise Refused(f"at most {MAX_PATHS} paths at a time")
    if os.geteuid() != 0:
        raise Refused("the panel is not running as root here, so it cannot "
                      "hand files over", status=503)
    who = owner()
    if who is None:
        raise Refused(f"there is no {OWNER_USER} user to hand files to",
                      status=503)
    uid, gid = who
    results = [own_one(p, uid, gid, recursive) for p in paths]
    changed = sum(r["changed"] for r in results)
    if changed:
        log.info("handed %d path(s) to %s", changed, OWNER_USER)
    return {"ok": all(r["ok"] for r in results), "user": OWNER_USER,
            "results": results}


def _open_root(root: str) -> int | None:
    """A descriptor on a tree's real folder, or None. The trees are run.sh's
    own choice, so the root itself may be a link; nothing under it is
    followed."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    try:
        return os.open(os.path.realpath(root), flags)
    except OSError:
        return None


def _sweep_top_yaml(root: str, uid: int, gid: int) -> int:
    """The config folder's own regular .yaml/.yml files that are not the
    `claude` user's — never a link, never `secrets.yaml`, never a file with
    other names."""
    dirfd = _open_root(root)
    if dirfd is None:
        return 0
    count = 0
    try:
        with os.scandir(dirfd) as entries:
            for entry in entries:
                name = entry.name
                if not name.endswith(YAML_SUFFIXES) or refusal_for(name):
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    st = entry.stat(follow_symlinks=False)
                    if st.st_nlink > 1 or (st.st_uid, st.st_gid) == (uid, gid):
                        continue
                    count += _hand_over_entry(name, dirfd, st, uid, gid)
                except OSError as exc:
                    log.debug("could not hand over %s: %s", name, exc)
    except OSError as exc:
        log.debug("ownership sweep could not read %s: %s", root, exc)
    finally:
        os.close(dirfd)
    return count


def _sweep_addon_folders(root: str, uid: int, gid: int) -> int:
    """Each add-on's own folder under /addon_configs that is not the
    `claude` user's — the folder only, so a new file can be made in it and
    a tool's rename can land; what is inside is the edit hook's and
    `brain own`'s, asked for one file at a time."""
    dirfd = _open_root(root)
    if dirfd is None:
        return 0
    count = 0
    flags = _OPEN | getattr(os, "O_DIRECTORY", 0)
    try:
        with os.scandir(dirfd) as entries:
            for entry in entries:
                try:
                    if (entry.name.startswith(".")
                            or not entry.is_dir(follow_symlinks=False)):
                        continue
                    st = entry.stat(follow_symlinks=False)
                    if (st.st_uid, st.st_gid) == (uid, gid):
                        continue
                    fd = os.open(entry.name, flags, dir_fd=dirfd)
                    try:
                        now = os.fstat(fd)
                        if (now.st_dev, now.st_ino) == (st.st_dev, st.st_ino):
                            count += _hand_over(fd, now, uid, gid)
                    finally:
                        os.close(fd)
                except OSError as exc:
                    log.debug("could not hand over %s: %s", entry.name, exc)
    except OSError as exc:
        log.debug("ownership sweep could not read %s: %s", root, exc)
    finally:
        os.close(dirfd)
    return count


def sweep() -> int:
    """Re-own what Home Assistant and the Supervisor wrote as root.

    The config folder's top-level YAML (what the UI editors rewrite), and
    each ``/addon_configs/<slug>`` folder when that tree is mapped (what an
    add-on installed after boot is given). Only where the owner is not
    already the `claude` user, and with the owner's write bit, since a
    hand-over that leaves the file read-only hands over nothing. Never
    raises; answers how many it handed over.
    """
    if os.geteuid() != 0:
        return 0
    who = owner()
    if who is None:
        return 0
    uid, gid = who
    count = _sweep_top_yaml(config_dir(), uid, gid)
    addons = os.environ.get(ADDON_CONFIG_VAR, "").strip()
    if addons and os.path.normpath(addons) in roots():
        count += _sweep_addon_folders(addons, uid, gid)
    if count:
        log.info("handed %d config file(s) and folder(s) written as root "
                 "back to %s", count, OWNER_USER)
    return count


_LAST_SWEEP: list[float] = []


def maybe_sweep(now: float | None = None) -> int | None:
    """`sweep` at most every `SWEEP_INTERVAL_S`; None when it was not due.
    Never raises — this rides the scheduler's tick."""
    now = time.monotonic() if now is None else now
    if _LAST_SWEEP and now - _LAST_SWEEP[0] < SWEEP_INTERVAL_S:
        return None
    _LAST_SWEEP[:] = [now]
    try:
        return sweep()
    except Exception as exc:  # noqa: BLE001 — a sweep is never the tick
        log.debug("ownership sweep failed: %s", exc)
        return 0


def peer_is_loopback(peer) -> bool:
    """Is a socket's peername this machine? Read off the socket, never a
    header — `X-Forwarded-For` is whatever a direct caller says it is. A
    unix-socket peer (a string) or a closed transport (None) is not."""
    if not isinstance(peer, tuple) or not peer or not isinstance(peer[0], str):
        return False
    host = peer[0].split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(addr, "ipv4_mapped", None)
    return bool((mapped or addr).is_loopback)


def from_loopback(request) -> bool:
    """Did this request arrive over loopback, from inside the add-on?

    Ingress requests come from the Supervisor's address, so the panel's
    own pages can never reach this — only the edit hook and `brain own`,
    which run in this container."""
    transport = getattr(request, "transport", None)
    peer = transport.get_extra_info("peername") if transport else None
    return peer_is_loopback(peer)
