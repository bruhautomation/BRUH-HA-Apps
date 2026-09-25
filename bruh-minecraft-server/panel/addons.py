#!/usr/bin/env python3
"""The add-on browser: server-side content from Modrinth, for every device.

What Realms calls an add-on is a Bedrock *behavior pack*, and a Java
server cannot run one. What it can do is better suited to a house full of
iPads: anything that runs on the SERVER reaches every player whatever they
play on, because Geyser translates the result and nothing is installed on
the device. So the browser offers four kinds, each with an honest answer to
"will the iPad get this":

* **plugin** (Paper / Purpur / Folia) — server code. Every Java and Bedrock
  player gets it, nothing to install. The Realms feel exactly.
* **datapack** — recipes, loot, world generation, advancements. Server
  side, so every player gets it; it lives in the world's own `datapacks/`.
* **mod** (Fabric / Forge) — only the ones Modrinth marks as needing
  nothing on the client, because a mod the client must also have is a mod
  an iPad can never join with.
* **resourcepack** — textures. Java clients are offered it on join through
  `server.properties`; Bedrock clients get a converted copy pushed by
  Geyser, and the conversion is best-effort (flat textures convert, custom
  models and sounds do not) — which the card says rather than promising.

Four rules, each a place this could quietly go wrong.

* **The server decides what is offered, not the search box.** A plugin on
  a Fabric server is a jar nothing loads; the kinds offered, the loaders
  asked for and the game version filtered on all come off the running
  server (`server_type` and `.server-meta.json`), so a result the browser
  shows is one this server can run.
* **A download is only what Modrinth said it was.** The URL has to be on
  Modrinth's CDN, the size is capped, and the file's SHA-512 has to match
  the hash the API published beside it — a mismatch is a refusal, not a
  warning, because the file is about to be executed by the JVM.
* **Required dependencies come with it**, and are recorded as such, so
  removing the thing you asked for does not leave a library you never
  chose, and removing a library something still needs is refused.
* **The record is per world** (`.bruh-addons.json` in the world folder),
  because plugins, datapacks and mods are per world here; switching worlds
  shows that world's own list.

Nothing here touches a running server; the panel says what needs a restart
and does the reload a datapack can take live.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

MODRINTH_API = os.environ.get("MODRINTH_API", "https://api.modrinth.com/v2")
USER_AGENT = "bruhautomation/BRUH-HA-Apps (bruh-minecraft-server; https://github.com/bruhautomation/BRUH-HA-Apps)"
# Where a download may come from. Modrinth serves every file off its CDN;
# anything else in a `url` field is not something this browser vouches for.
DOWNLOAD_HOSTS = {"cdn.modrinth.com"}
MAX_DOWNLOAD = 150 * 1024 * 1024
MAX_DEPENDENCY_DEPTH = 3
MANIFEST_NAME = ".bruh-addons.json"
PAGE_SIZE = 20

PLUGIN_LOADERS = {
    "paper": ["paper", "spigot", "bukkit"],
    "purpur": ["purpur", "paper", "spigot", "bukkit"],
    "folia": ["folia"],
}
MOD_LOADERS = {"fabric": ["fabric"], "forge": ["forge"]}

KINDS = ("plugin", "datapack", "mod", "resourcepack")
KIND_LABELS = {
    "plugin": "Plugins",
    "datapack": "Data packs",
    "mod": "Server mods",
    "resourcepack": "Resource packs",
}
# The one sentence each kind owes somebody deciding whether the iPad will
# see it. Shown on every card, so it is short.
REACH = {
    "plugin": "Runs on the server — every player gets it, iPad and console included.",
    "datapack": "Runs on the server — every player gets it, iPad and console included.",
    "mod": "Server-side only — every player gets it, nothing to install on a device.",
    "resourcepack": "Java players are offered it on join; Bedrock/iPad players get a "
                    "converted copy (flat textures only — custom models do not convert).",
}

SAFE_FILE = re.compile(r"^[A-Za-z0-9._+-]{1,128}\.(jar|zip)$")
PROJECT_ID = re.compile(r"^[A-Za-z0-9]{2,64}$")
VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


class AddonError(Exception):
    """A refusal with a sentence a person can act on."""


# ---------------------------------------------------------------------------
# What this server can run
# ---------------------------------------------------------------------------
def kinds_for(server_type: str) -> list[str]:
    """The kinds this server can load, in the order the browser shows them."""
    st = (server_type or "").lower()
    out = []
    if st in PLUGIN_LOADERS:
        out.append("plugin")
    if st in MOD_LOADERS:
        out.append("mod")
    out += ["datapack", "resourcepack"]
    return out


def loaders_for(kind: str, server_type: str) -> list[str]:
    st = (server_type or "").lower()
    if kind == "plugin":
        return PLUGIN_LOADERS.get(st, [])
    if kind == "mod":
        return MOD_LOADERS.get(st, [])
    if kind == "datapack":
        return ["datapack"]
    if kind == "resourcepack":
        return ["minecraft"]
    return []


def game_version(meta: dict | None, stats: dict | None) -> str:
    """The Minecraft version this server runs, or "" when nothing says.

    `.server-meta.json` is what the downloader resolved and is exact;
    the status ping's version name ("Paper 1.21.4") is the fallback. An
    empty answer turns the version filter off rather than guessing one,
    because a wrong version filter hides every correct result.
    """
    for raw in ((meta or {}).get("version"), (stats or {}).get("version")):
        m = VERSION_RE.search(str(raw or ""))
        if m:
            return m.group(1)
    return ""


def search_params(kind: str, query: str, server_type: str, version: str,
                  offset: int = 0) -> dict[str, str]:
    """The query string for Modrinth's /search, facets and all."""
    if kind not in kinds_for(server_type):
        raise AddonError(
            f"This server runs {server_type or 'an unknown server type'}, which "
            f"cannot load {KIND_LABELS.get(kind, kind).lower()}.")
    facets: list[list[str]] = [[f"project_type:{kind}"]]
    loaders = loaders_for(kind, server_type)
    if kind in ("plugin", "mod") and loaders:
        facets.append([f"categories:{loader}" for loader in loaders])
    if kind == "mod":
        # Only what a vanilla client (and so a Bedrock one through Geyser)
        # can join without: the client side may be optional, never required.
        facets.append(["client_side:optional", "client_side:unsupported"])
        facets.append(["server_side:required", "server_side:optional"])
    if version:
        facets.append([f"versions:{version}"])
    return {
        "query": (query or "").strip()[:100],
        "facets": json.dumps(facets),
        "index": "relevance" if (query or "").strip() else "downloads",
        "limit": str(PAGE_SIZE),
        "offset": str(max(0, int(offset or 0))),
    }


def pick_version(versions: list[dict], loaders: list[str], version: str) -> dict | None:
    """The newest release (else newest anything) this server can load."""
    fits = []
    for v in versions or []:
        if not isinstance(v, dict):
            continue
        if loaders and not set(v.get("loaders") or []) & set(loaders):
            continue
        if version and version not in (v.get("game_versions") or []):
            continue
        if not any(isinstance(f, dict) and f.get("url") for f in v.get("files") or []):
            continue
        fits.append(v)
    if not fits:
        return None
    fits.sort(key=lambda v: str(v.get("date_published") or ""), reverse=True)
    for v in fits:
        if v.get("version_type") == "release":
            return v
    return fits[0]


def primary_file(version: dict) -> dict:
    files = [f for f in version.get("files") or [] if isinstance(f, dict) and f.get("url")]
    for f in files:
        if f.get("primary"):
            return f
    return files[0]


def safe_filename(name: str, slug: str, kind: str) -> str:
    """The file name to write, or one made from the slug when it is not safe."""
    ext = ".jar" if kind in ("plugin", "mod") else ".zip"
    name = os.path.basename(str(name or ""))
    if SAFE_FILE.match(name) and name.endswith(ext):
        return name
    stem = re.sub(r"[^A-Za-z0-9._+-]", "-", str(slug or "addon"))[:100].strip(".-") or "addon"
    return stem + ext


def download_allowed(url: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("https", "http") and parts.hostname in DOWNLOAD_HOSTS


def normalise_hit(hit: dict, kind: str, installed: dict) -> dict:
    pid = str(hit.get("project_id") or "")
    return {
        "id": pid,
        "slug": hit.get("slug") or "",
        "title": hit.get("title") or hit.get("slug") or pid,
        "description": (hit.get("description") or "")[:300],
        "author": hit.get("author") or "",
        "icon": hit.get("icon_url") or "",
        "downloads": int(hit.get("downloads") or 0),
        "kind": kind,
        "reach": REACH[kind],
        "installed": pid in installed,
        "url": f"https://modrinth.com/{kind}/{hit.get('slug') or pid}",
    }


# ---------------------------------------------------------------------------
# The per-world record
# ---------------------------------------------------------------------------
def manifest_path(server_dir: Path) -> Path:
    return Path(server_dir) / MANIFEST_NAME


def read_manifest(server_dir: Path) -> dict[str, dict]:
    try:
        data = json.loads(manifest_path(server_dir).read_text())
    except (OSError, ValueError):
        return {}
    items = data.get("installed") if isinstance(data, dict) else None
    return {k: v for k, v in (items or {}).items() if isinstance(v, dict)}


def write_manifest(server_dir: Path, items: dict[str, dict]) -> None:
    path = manifest_path(server_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".bruh-addons.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump({"installed": items}, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def destination(kind: str, server_dir: Path, level_name: str, packs_dir: Path) -> Path:
    server_dir = Path(server_dir)
    if kind == "plugin":
        return server_dir / "plugins"
    if kind == "mod":
        return server_dir / "mods"
    if kind == "datapack":
        level = level_name if re.fullmatch(r"[A-Za-z0-9._ -]{1,64}", level_name or "") \
            and ".." not in level_name else "world"
        return server_dir / level / "datapacks"
    return Path(packs_dir)


def needed_by(items: dict[str, dict], project_id: str) -> list[str]:
    """Titles of installed add-ons that list this one as a requirement."""
    return [v.get("title") or k for k, v in items.items()
            if project_id in (v.get("requires") or []) and k != project_id]


# ---------------------------------------------------------------------------
# Talking to Modrinth
# ---------------------------------------------------------------------------
class Modrinth:
    """The three calls the browser makes, over one aiohttp session."""

    def __init__(self, session, base: str | None = None):
        self.session = session
        self.base = (base or MODRINTH_API).rstrip("/")

    async def _get(self, path: str, params: dict | None = None) -> Any:
        async with self.session.get(f"{self.base}{path}", params=params,
                                    headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status == 404:
                raise AddonError("Modrinth has no such project.")
            if resp.status == 429:
                raise AddonError("Modrinth is rate-limiting this server; try again in a minute.")
            if resp.status != 200:
                raise AddonError(f"Modrinth answered HTTP {resp.status}.")
            return await resp.json(content_type=None)

    async def search(self, params: dict) -> dict:
        return await self._get("/search", params)

    async def project(self, project_id: str) -> dict:
        return await self._get(f"/project/{urllib.parse.quote(project_id, safe='')}")

    async def versions(self, project_id: str, loaders: list[str], version: str) -> list:
        params = {}
        if loaders:
            params["loaders"] = json.dumps(loaders)
        if version:
            params["game_versions"] = json.dumps([version])
        return await self._get(
            f"/project/{urllib.parse.quote(project_id, safe='')}/version", params)

    async def download(self, url: str, dest: Path, sha512: str) -> None:
        """Stream a file to `dest`, refusing anything Modrinth did not publish."""
        if not download_allowed(url):
            raise AddonError("That download is not on Modrinth's CDN, so it was not fetched.")
        if not re.fullmatch(r"[0-9a-f]{128}", sha512 or ""):
            raise AddonError("Modrinth published no SHA-512 for that file, so it cannot be checked.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=".download.", suffix=".part")
        digest = hashlib.sha512()
        total = 0
        try:
            with os.fdopen(fd, "wb") as fh:
                async with self.session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
                    if resp.status != 200:
                        raise AddonError(f"The download answered HTTP {resp.status}.")
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        total += len(chunk)
                        if total > MAX_DOWNLOAD:
                            raise AddonError(
                                f"That file is over {MAX_DOWNLOAD // (1024 * 1024)} MB; not installed.")
                        digest.update(chunk)
                        fh.write(chunk)
            if digest.hexdigest() != sha512:
                raise AddonError("The file did not match the hash Modrinth published; not installed.")
            os.replace(tmp, dest)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


class Context:
    """What an install needs to know about the server it is installing into."""

    def __init__(self, server_type: str, version: str, server_dir: Path,
                 level_name: str, packs_dir: Path):
        self.server_type = (server_type or "").lower()
        self.version = version
        self.server_dir = Path(server_dir)
        self.level_name = level_name or "world"
        self.packs_dir = Path(packs_dir)


async def search(client: Modrinth, ctx: Context, kind: str, query: str,
                 offset: int = 0) -> dict:
    params = search_params(kind, query, ctx.server_type, ctx.version, offset)
    data = await client.search(params)
    installed = read_manifest(ctx.server_dir)
    hits = [normalise_hit(h, kind, installed) for h in (data or {}).get("hits") or []
            if isinstance(h, dict) and h.get("project_id")]
    return {"kind": kind, "hits": hits, "total": int((data or {}).get("total_hits") or 0),
            "offset": int(params["offset"]), "game_version": ctx.version,
            "server_type": ctx.server_type}


async def install(client: Modrinth, ctx: Context, project_id: str, kind: str,
                  _depth: int = 0, _seen: set | None = None,
                  required_by: str = "") -> list[dict]:
    """Install one project and its required dependencies; what was written.

    Returns one row per file written, dependencies first, so the caller can
    say exactly what landed. An already-installed dependency is left alone;
    the project that was asked for is always re-resolved, which is how an
    update happens.
    """
    if not PROJECT_ID.match(project_id or ""):
        raise AddonError("That is not a Modrinth project id.")
    if kind not in kinds_for(ctx.server_type):
        raise AddonError(
            f"This server runs {ctx.server_type or 'an unknown server type'}, "
            f"which cannot load {KIND_LABELS.get(kind, kind).lower()}.")
    seen = _seen if _seen is not None else set()
    if project_id in seen:
        return []
    seen.add(project_id)

    project = await client.project(project_id)
    if project.get("project_type") != kind:
        raise AddonError(
            f"{project.get('title') or project_id} is a {project.get('project_type')}, "
            f"not a {kind}.")
    if kind == "mod" and project.get("client_side") == "required":
        raise AddonError(
            f"{project.get('title')} has to be installed on every player's device too, "
            "so Bedrock and iPad players could never join with it.")
    loaders = loaders_for(kind, ctx.server_type)
    versions = await client.versions(project["id"], loaders, ctx.version)
    chosen = pick_version(versions, loaders, ctx.version)
    if chosen is None:
        raise AddonError(
            f"{project.get('title') or project_id} has no build for "
            f"{ctx.server_type} {ctx.version or ''}".rstrip() + ".")

    written: list[dict] = []
    requires = []
    if _depth < MAX_DEPENDENCY_DEPTH:
        manifest = read_manifest(ctx.server_dir)
        for dep in chosen.get("dependencies") or []:
            dep_id = (dep or {}).get("project_id")
            if dep.get("dependency_type") != "required" or not dep_id:
                continue
            requires.append(dep_id)
            if dep_id in manifest:
                continue
            written += await install(client, ctx, dep_id, kind, _depth + 1, seen,
                                     required_by=project.get("title") or project_id)

    f = primary_file(chosen)
    dest_dir = destination(kind, ctx.server_dir, ctx.level_name, ctx.packs_dir)
    filename = safe_filename(f.get("filename"), project.get("slug"), kind)
    if kind == "resourcepack" and not filename.endswith(".zip"):
        filename = safe_filename("", project.get("slug"), kind)
    target = dest_dir / filename
    manifest = read_manifest(ctx.server_dir)
    old = manifest.get(project["id"])
    await client.download(f["url"], target, (f.get("hashes") or {}).get("sha512", ""))
    if old and old.get("file") and old.get("file") != filename:
        # An update with a new file name: the old jar would load beside the
        # new one and Paper would disable one of them at random.
        (dest_dir / os.path.basename(old["file"])).unlink(missing_ok=True)

    row = {
        "title": project.get("title") or project_id,
        "slug": project.get("slug") or "",
        "kind": kind,
        "file": filename,
        "version": chosen.get("version_number") or "",
        "version_id": chosen.get("id") or "",
        "icon": project.get("icon_url") or "",
        "installed_at": int(time.time()),
        "requires": requires,
        # Empty when somebody asked for it by name — including a library
        # they later chose on purpose — so the list can tell what was
        # chosen from what came along.
        "required_by": required_by,
    }
    manifest[project["id"]] = row
    write_manifest(ctx.server_dir, manifest)
    return written + [{"id": project["id"], **row}]


def remove(ctx: Context, project_id: str, force: bool = False) -> dict:
    """Take one add-on out of this world, or refuse and say what needs it."""
    items = read_manifest(ctx.server_dir)
    row = items.get(project_id)
    if row is None:
        raise AddonError("That add-on is not installed in this world.")
    users = needed_by(items, project_id)
    if users and not force:
        raise AddonError(f"{row.get('title')} is needed by {', '.join(users)}; remove that first.")
    dest = destination(row.get("kind", ""), ctx.server_dir, ctx.level_name, ctx.packs_dir)
    name = os.path.basename(str(row.get("file") or ""))
    removed = False
    if name and SAFE_FILE.match(name):
        path = dest / name
        if path.is_file():
            path.unlink()
            removed = True
    items.pop(project_id, None)
    write_manifest(ctx.server_dir, items)
    return {"id": project_id, "title": row.get("title"), "kind": row.get("kind"),
            "file": name, "file_removed": removed}


def installed(ctx: Context) -> list[dict]:
    """Every add-on this world's record holds, and whether its file is there."""
    items = read_manifest(ctx.server_dir)
    out = []
    for pid, row in sorted(items.items(), key=lambda kv: str(kv[1].get("title", "")).lower()):
        kind = row.get("kind", "")
        dest = destination(kind, ctx.server_dir, ctx.level_name, ctx.packs_dir)
        out.append({"id": pid, **row, "reach": REACH.get(kind, ""),
                    "present": (dest / os.path.basename(str(row.get("file") or ""))).is_file(),
                    "needed_by": needed_by(items, pid)})
    return out
