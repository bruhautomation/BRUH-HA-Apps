"""Download Bambu Studio and unpack it into /data.

Bambu Lab publishes Linux builds as an AppImage on each GitHub release,
one built on Ubuntu 22.04 and one on 24.04. This container is Debian
bookworm, whose glibc is newer than 22.04's and older than 24.04's, so the
22.04 build is the one that runs — picked by name, not by "the first
AppImage in the list", which is a coin flip between a working slicer and
one that dies on a missing symbol.

The AppImage is EXTRACTED (`--appimage-extract`), never run as itself: an
AppImage normally mounts its own squashfs with FUSE, and a container that
could mount a filesystem is a container that has given up on its sandbox
(apparmor.txt denies `mount` outright).

Everything happens in a background thread with a state the panel polls,
because the download is 200+ MB and a request that waits for it is a
request ingress cuts off half-way.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import bambu_atomic

DATA = Path(os.environ.get("BAMBU_DATA", "/data"))
INSTALL_ROOT = DATA / "bambu-studio"
MARKER = INSTALL_ROOT / "installed.json"
API = "https://api.github.com/repos/bambulab/BambuStudio/releases"
ASSET = re.compile(r"ubuntu[-_]?22\.04.*\.AppImage$", re.IGNORECASE)
TAG = re.compile(r"^v?\d+(\.\d+){1,4}$")
TIMEOUT = 60
UA = "BRUH-Bambu-Studio (Home Assistant add-on)"

STATE: dict = {"phase": "idle", "progress": None, "version": None,
               "error": "", "started": None}
_LOCK = threading.Lock()


def installed() -> dict | None:
    """The unpacked install, if its launcher is really there."""
    data = bambu_atomic.read_json(MARKER, None)
    if not isinstance(data, dict):
        return None
    apprun = Path(str(data.get("apprun") or ""))
    return data if apprun.is_file() else None


def pick_asset(release: dict) -> dict | None:
    for asset in release.get("assets") or []:
        if isinstance(asset, dict) and ASSET.search(str(asset.get("name") or "")):
            return asset
    return None


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode())


def resolve(version: str, url: str = "") -> tuple[str, str]:
    """(version label, download url) for what the options ask for."""
    if url:
        if not url.startswith("https://"):
            raise ValueError("The AppImage link must be an https:// URL.")
        label = re.search(r"v?\d+\.\d+\.\d+\.\d+", url)
        return (label.group(0) if label else "custom"), url
    version = (version or "latest").strip()
    if version == "latest":
        release = _get_json(f"{API}/latest")
    elif TAG.match(version):
        tag = version if version.startswith("v") else f"v{version}"
        release = _get_json(f"{API}/tags/{tag}")
    else:
        raise ValueError(f"{version!r} is not a release tag (for example v02.08.02.61).")
    asset = pick_asset(release)
    if asset is None:
        raise LookupError(
            f"Bambu Studio {release.get('tag_name')} has no Ubuntu 22.04 AppImage "
            f"to download. Pin an older version, or give a link in appimage_url.")
    return str(release.get("tag_name") or version), str(asset["browser_download_url"])


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            out.write(block)
            done += len(block)
            STATE["progress"] = round(done / total * 100) if total else None


def _extract(appimage: Path, target: Path) -> Path:
    """Unpack into `target`/squashfs-root, and return its AppRun."""
    appimage.chmod(0o755)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    result = subprocess.run([str(appimage), "--appimage-extract"], cwd=target,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            timeout=900, check=False,
                            env={**os.environ, "APPIMAGE_EXTRACT_AND_RUN": "0"})
    apprun = target / "squashfs-root" / "AppRun"
    if result.returncode != 0 or not apprun.exists():
        tail = result.stderr.decode(errors="replace").strip().splitlines()[-1:]
        raise RuntimeError("Unpacking the AppImage failed"
                           + (f": {tail[0]}" if tail else "."))
    return apprun


def install(version: str = "latest", url: str = "", *, force: bool = False) -> None:
    """Blocking: resolve, download, unpack, record. Updates STATE throughout."""
    STATE.update(phase="resolving", progress=None, error="", started=time.time())
    try:
        label, link = resolve(version, url)
        current = installed()
        if current and current.get("version") == label and not force:
            STATE.update(phase="ready", version=label)
            return
        STATE.update(phase="downloading", version=label)
        INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
        scratch = INSTALL_ROOT / f".download-{os.getpid()}.AppImage"
        _download(link, scratch)
        STATE.update(phase="extracting", progress=None)
        safe_label = re.sub(r"[^A-Za-z0-9._-]", "_", label)
        apprun = _extract(scratch, INSTALL_ROOT / safe_label)
        scratch.unlink(missing_ok=True)
        previous = current.get("dir") if current else None
        bambu_atomic.write_json(MARKER, {"version": label, "url": link,
                                         "dir": str(INSTALL_ROOT / safe_label),
                                         "apprun": str(apprun),
                                         "installed_at": int(time.time())})
        if previous and previous != str(INSTALL_ROOT / safe_label):
            shutil.rmtree(previous, ignore_errors=True)
        STATE.update(phase="ready", progress=100)
    except (OSError, ValueError, LookupError, RuntimeError,
            subprocess.SubprocessError, urllib.error.URLError) as exc:
        STATE.update(phase="failed", error=str(exc))
        if installed():
            STATE["error"] += " The version already installed is still in use."


def start_install(version: str, url: str, *, force: bool = False,
                  after=None) -> bool:
    """Run `install` on a thread; False if one is already running."""
    with _LOCK:
        if STATE["phase"] in ("resolving", "downloading", "extracting"):
            return False
        STATE["phase"] = "resolving"

    def _run():
        install(version, url, force=force)
        if after:
            after()

    threading.Thread(target=_run, name="bambu-install", daemon=True).start()
    return True


def apprun() -> Path | None:
    data = installed()
    return Path(data["apprun"]) if data else None


def resources() -> Path | None:
    run = apprun()
    if run is None:
        return None
    for candidate in (run.parent / "resources", run.parent / "usr" / "share" / "BambuStudio"):
        if candidate.is_dir():
            return candidate
    return None
