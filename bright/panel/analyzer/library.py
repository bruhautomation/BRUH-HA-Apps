"""The music library: what is in the folder, and what has been analyzed.

Track identity is a content hash (size + first megabyte), not the path —
renaming a file must not cost its analysis, and two copies of one track
are one analysis. Everything derived lives under /data/shows/<hash>/.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import atomic_write

SHOWS_DIR = Path(os.environ.get("BRIGHT_STATE", "/data")) / "shows"

# What the analyzer knows how to hear. **Bump this whenever an analysis
# gains a field**, because a track is re-analysed on nothing else.
#
# It lives here rather than in `pipeline` because `scan` is what has to
# read it — and reading it is the whole point. It sat at 1 while the
# analyzer gained ranked accents, and `scan` marked a track analysed if an
# analysis file existed at all, so every library that had ever been
# scanned went on answering with the old analyzer's output forever. The
# feature shipped, its tests passed, and it could not reach one person who
# had already used the add-on: their shows had no accents to place because
# their analyses had no accents in them, and from the outside that is
# indistinguishable from a feature that does nothing. A version nothing
# compares against is not a version, it is a comment.
#
# 2: `hits` — ranked accents with their place against the beat.
# 3: `music` — harmony, melody, phrases, repetition.
# 4: `hits` gain `band`/`tone` — which drum, so the kick and the snare
#    can drive different lights instead of one undifferentiated "accent".
ANALYSIS_VERSION = 4


def is_stale(analysis: dict | None) -> bool:
    """Was this analysis made by an older analyzer than the one running?

    Stale is not unusable: the track still has beats, sections and a
    duration, so it still plays and its show still runs. It means the
    library is answering a question the current analyzer would answer
    better, which is a thing to re-run and never a thing to refuse.
    """
    if not analysis:
        return False
    try:
        return int(analysis.get("version") or 0) < ANALYSIS_VERSION
    except (TypeError, ValueError):
        return True

# Where a show script is mirrored so a person can open it.
#
# /data belongs to the add-on and Home Assistant cannot see into it, so a
# script living only there is a file nobody can read without a shell. Every
# compile republishes the script here, under a name with the track in it,
# and the panel can read one back on request ("Load the edited file").
#
# The mirror is a COPY, and the copy is not the record: /data is. Editing
# the mirror changes nothing until it is imported, which is deliberate —
# a half-typed JSON file being picked up by a party at 11pm is not a
# feature. The panel's editor writes both at once, so the two only differ
# while somebody is deliberately editing the file by hand.
SHARED_SHOWS = (Path(os.environ.get("BRIGHT_SHARED", "/config/.bright"))
                / "shows")

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}

_HASH_RE = re.compile(r"^[0-9a-f]{40}$")


def track_hash(path: Path) -> str:
    """sha1 of (size, first 1MB). Fast enough to hash a folder on every
    scan, stable across renames, and collision-proof enough for a music
    library."""
    digest = hashlib.sha1()
    stat = path.stat()
    digest.update(str(stat.st_size).encode())
    with open(path, "rb") as handle:
        digest.update(handle.read(1024 * 1024))
    return digest.hexdigest()


# Where the answer to "what is this file's hash" is remembered between
# scans, keyed by the two things that change when a file does.
HASH_CACHE = Path(os.environ.get("BRIGHT_STATE", "/data")) / "track-hashes.json"


class _HashCache:
    """A megabyte read per file per scan, paid once instead.

    `track_hash` reads the first megabyte of every track, and the library
    is scanned far more often than anyone would guess from the Library
    tab: the Shows tab lists it, the effect builder lists it, the sync
    proof lists it, and the Library tab is about to list it on open rather
    than on a button. On a Pi reading a network share that is the whole
    reason the tab felt like it was loading the music each time — the file
    list really was being re-read from the disk up, every time.

    Size and mtime are what the cache is keyed on, because they are what
    change when a file changes. The risk in that trade is a file edited so
    that its length and timestamp both survive unchanged, which is not a
    thing music files do; and the cost of being wrong is one stale hash,
    not a corrupt library — the hash only has to be *stable*, and a track
    whose entry is wrong analyses again under a new identity rather than
    breaking. `st_mtime_ns` rather than `st_mtime` so the comparison is
    integer equality and not a float that a filesystem may round.
    """

    def __init__(self) -> None:
        self._entries: dict[str, list] = {}
        self._seen: set[str] = set()
        self._dirty = False
        try:
            data = json.loads(HASH_CACHE.read_text())
            if isinstance(data.get("entries"), dict):
                self._entries = {k: v for k, v in data["entries"].items()
                                 if isinstance(v, list) and len(v) == 3}
        except (OSError, ValueError):
            # No cache, or an unreadable one. Both mean the same thing —
            # hash everything this time — and the next save rewrites it.
            pass

    def hash_for(self, path: Path, stat_result) -> str:
        key = str(path)
        self._seen.add(key)
        entry = self._entries.get(key)
        if (entry and entry[0] == stat_result.st_size
                and entry[1] == stat_result.st_mtime_ns):
            return entry[2]
        digest = track_hash(path)
        self._entries[key] = [stat_result.st_size, stat_result.st_mtime_ns,
                              digest]
        self._dirty = True
        return digest

    def save(self, prune: bool = True) -> None:
        """Persist. `prune` drops anything this scan did not see.

        Pruning keeps the file bounded to the library rather than to every
        track that has ever been in it, and it is only correct after a
        walk of ALL the folders: a scan of one folder has no idea what the
        others were about to claim, and evicting on its say-so throws away
        every entry it did not happen to visit. So a lone `scan` still
        records what it learned — the speed is worth having either way —
        and simply never evicts. `scan_all` is the only caller that prunes.
        """
        stale = (set(self._entries) - self._seen) if prune else set()
        if not self._dirty and not stale:
            return
        for key in stale:
            self._entries.pop(key, None)
        try:
            atomic_write.write_json(HASH_CACHE, {"entries": self._entries})
        except OSError:
            # A cache that cannot be written costs speed and nothing else.
            pass


def is_track_hash(hash_hex: str) -> bool:
    """Is this the shape of a track identity?

    Public because callers need to tell "you asked for something that is
    not a hash" from "there is no analysis for that track", and
    `load_analysis` cannot: it swallows the ValueError along with the
    missing-file case, so both arrive as None and both used to be reported
    as "not analysed yet".
    """
    return bool(_HASH_RE.fullmatch(str(hash_hex)))


def _track_dir(hash_hex: str) -> Path:
    if not _HASH_RE.fullmatch(hash_hex):
        raise ValueError(f"not a track hash: {hash_hex!r}")
    return SHOWS_DIR / hash_hex


def analysis_path(hash_hex: str) -> Path:
    return _track_dir(hash_hex) / "analysis.json"


def duration_of(analysis: dict) -> float:
    """How long the track actually is, from the best evidence on hand.

    New analyses carry `duration_s`, measured from the decoded PCM, and
    that is the answer. Older ones only have `tags["duration"]`, which is
    mutagen's header read — and a VBR file without a proper Xing header
    reports an estimate wrong by whole multiples, which is where the
    twenty-six-minute four-minute songs came from. For those, the beat
    grid is the witness: the tracker walked the whole file, so the last
    beat is near the real end, and a claimed duration far past it is the
    header lying rather than a long quiet outro. Sixty seconds of
    tolerance is a generous outro and nowhere near a header's error,
    which is measured in multiples.
    """
    measured = analysis.get("duration_s")
    if measured:
        return float(measured)
    beats = analysis.get("beats") or []
    floor = (float(beats[-1]) + 5.0) if beats else 0.0
    tagged = (analysis.get("tags") or {}).get("duration")
    if tagged:
        tagged = float(tagged)
        if not beats or tagged <= floor + 60.0:
            return tagged
    return floor or float(tagged or 0.0)


def load_analysis(hash_hex: str) -> dict | None:
    try:
        return json.loads(analysis_path(hash_hex).read_text())
    except (OSError, ValueError):
        return None


def save_analysis(hash_hex: str, analysis: dict) -> None:
    atomic_write.write_json(analysis_path(hash_hex), analysis)


# ---------------------------------------------------------------- versions
#
# A track has MANY shows, and one of them is the one that plays.
#
# Every compile used to overwrite `show.json`, so asking Claude to try
# again destroyed the show you had — including the one you had spent an
# evening editing. That is not a risk people take twice: it makes the
# rewrite button something you avoid, which is the opposite of what a
# director is for. So every save lands in its own directory and a pointer
# says which one is live.
#
# The pointer, not a copy, is what makes this cheap. A compiled show is
# most of a megabyte on a busy track, and keeping the active one as a
# second copy beside the archive would double every track's storage on a
# machine that is usually a Pi with an SD card. `show_path` resolves
# through `versions.json` instead, so every existing caller — the
# conductor, the party queue, the editor, the mirror — goes on asking for
# "this track's show" and gets the active one without knowing versions
# exist.
#
# Names are what make an archive usable, and a name is also a decision:
# naming a version PINS it, because the only reason to name something is
# to be able to come back to it. Unnamed versions are the ones the prune
# eats when there are too many.
VERSIONS_FILE = "versions.json"
MAX_VERSIONS = 12

# What made this show. Kept as data rather than prose because the list is
# sorted and filtered by it, and because "who wrote this" is the first
# question anyone asks of a version they do not recognise.
SOURCES = ("algorithmic", "claude", "revision", "edit", "import")


def versions_path(hash_hex: str) -> Path:
    return _track_dir(hash_hex) / VERSIONS_FILE


def _version_dir(hash_hex: str, version_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-z]{1,24}", str(version_id)):
        raise ValueError(f"not a version id: {version_id!r}")
    return _track_dir(hash_hex) / "versions" / version_id


def _read_versions(hash_hex: str) -> dict:
    """The version index, migrating a pre-versions track on the way past.

    Migration moves the legacy files rather than copying them, which is
    the whole reason it is safe to do lazily on a read: `os.replace`
    within one directory tree is atomic, so a track is either migrated or
    not, never half of each, however the add-on dies in the middle.
    """
    try:
        data = json.loads(versions_path(hash_hex).read_text())
        if isinstance(data, dict) and isinstance(data.get("versions"), list):
            return data
    except (OSError, ValueError):
        # No index yet (a track compiled before versions existed, or one
        # that has never been compiled at all) or an unreadable one.
        # Every case has the same answer and it is below rather than
        # here: adopt whatever show is on disk, or return an empty
        # index. Raising would mean a single corrupt file made a track
        # impossible to compile for, which is a worse failure than
        # rebuilding the index from what is actually there.
        pass

    legacy_show = _track_dir(hash_hex) / "show.json"
    legacy_script = _track_dir(hash_hex) / "script.json"
    if not legacy_show.exists():
        return {"version": 1, "active": None, "versions": []}
    entry = _new_entry("import", note="the show that was here before "
                                      "BRight kept versions")
    target = _version_dir(hash_hex, entry["id"])
    try:
        target.mkdir(parents=True, exist_ok=True)
        os.replace(legacy_show, target / "show.json")
        if legacy_script.exists():
            os.replace(legacy_script, target / "script.json")
    except OSError:
        return {"version": 1, "active": None, "versions": []}
    index = {"version": 1, "active": entry["id"], "versions": [entry]}
    _write_versions(hash_hex, index)
    return index


def _write_versions(hash_hex: str, index: dict) -> None:
    atomic_write.write_json(versions_path(hash_hex), index, indent=2)


def _new_entry(source: str, note: str = "", name: str = "") -> dict:
    # The id is time-ordered and short: it sorts by age without anybody
    # parsing a date out of it, and it is a directory name a person may
    # end up reading in a shell.
    stamp = format(int(time.time()), "x")
    salt = hashlib.sha1(os.urandom(8)).hexdigest()[:4]
    return {"id": f"{stamp}{salt}", "name": str(name or "")[:60],
            "created_at": time.time(),
            "source": source if source in SOURCES else "edit",
            "note": str(note or "")[:300], "pinned": bool(name)}


def list_versions(hash_hex: str) -> dict:
    """Every show this track has, newest first, and which one is live."""
    index = _read_versions(hash_hex)
    rows = []
    for entry in index.get("versions") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        row = dict(entry)
        row["active"] = entry["id"] == index.get("active")
        rows.append(row)
    rows.sort(key=lambda r: r.get("created_at") or 0, reverse=True)
    return {"active": index.get("active"), "versions": rows}


def show_path(hash_hex: str) -> Path:
    return _active_dir(hash_hex) / "show.json"


def script_path(hash_hex: str) -> Path:
    return _active_dir(hash_hex) / "script.json"


def _active_dir(hash_hex: str) -> Path:
    """Where the live show lives, or where it would live if there were one.

    The fallback matters: `load_show` on a track with no show at all has
    always answered None by failing to read a file, and every caller is
    written against that. Returning the track's own directory keeps that
    true — nothing is there either — rather than raising a new kind of
    error into paths that have never had to handle one.
    """
    index = _read_versions(hash_hex)
    active = index.get("active")
    if not active:
        return _track_dir(hash_hex)
    try:
        return _version_dir(hash_hex, active)
    except ValueError:
        return _track_dir(hash_hex)


def load_show(hash_hex: str) -> dict | None:
    try:
        return json.loads(show_path(hash_hex).read_text())
    except (OSError, ValueError):
        return None


def save_show(hash_hex: str, script: dict, show: dict,
              title: str = "", *, source: str = "edit",
              note: str = "", name: str = "") -> str:
    """Save a new version and make it the live one. Returns its id.

    New versions are always live, because every route into here is
    somebody asking for this show: a compile, a revision, a hand edit. An
    old version becoming live again is `activate`, which is a different
    verb a person presses on purpose.
    """
    index = _read_versions(hash_hex)
    entry = _new_entry(source, note=note, name=name)
    entry["cues"] = len((show or {}).get("cues") or [])
    entry["scenes"] = len((script or {}).get("scenes") or [])
    directory = _version_dir(hash_hex, entry["id"])
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write.write_json(directory / "script.json", script)
    atomic_write.write_json(directory / "show.json", show)

    index["versions"] = [e for e in (index.get("versions") or [])
                         if isinstance(e, dict) and e.get("id")] + [entry]
    index["active"] = entry["id"]
    _prune(hash_hex, index)
    _write_versions(hash_hex, index)
    publish_script(hash_hex, script, title)
    return entry["id"]


def _prune(hash_hex: str, index: dict) -> None:
    """Drop the oldest unnamed versions over the cap.

    Named and active ones are never eaten — naming is how a person says
    "keep this", and eating the live show would leave a track playing
    nothing. A track whose versions are ALL named simply goes over the
    cap: refusing the save instead would mean the archive filling up
    stops you working, which is a worse failure than a long list.
    """
    entries = sorted(index.get("versions") or [],
                     key=lambda e: e.get("created_at") or 0)
    droppable = [e for e in entries
                 if not e.get("pinned") and not e.get("name")
                 and e.get("id") != index.get("active")]
    while len(entries) > MAX_VERSIONS and droppable:
        victim = droppable.pop(0)
        entries.remove(victim)
        _remove_dir(hash_hex, victim["id"])
    index["versions"] = entries


def _remove_dir(hash_hex: str, version_id: str) -> None:
    try:
        directory = _version_dir(hash_hex, version_id)
    except ValueError:
        return
    for name in ("script.json", "show.json"):
        (directory / name).unlink(missing_ok=True)
    try:
        directory.rmdir()
    except OSError:
        # Something else is in there — a file this version of BRight does
        # not write, or a half-finished write from another process. The
        # version is already out of the index and its two files are gone,
        # so the deletion HAS happened; an empty directory left behind
        # costs a few bytes and nothing else. Failing here would report a
        # delete that actually succeeded as an error.
        pass


def activate_version(hash_hex: str, version_id: str, title: str = "") -> dict:
    """Make an old show the live one again.

    The mirror is republished from it, because the mirror is a copy of
    the live show and a stale one is the file somebody hand-edits by
    mistake.
    """
    index = _read_versions(hash_hex)
    entry = next((e for e in index.get("versions") or []
                  if e.get("id") == version_id), None)
    if entry is None:
        raise ValueError("no such version")
    if not (_version_dir(hash_hex, version_id) / "show.json").exists():
        raise ValueError("that version's files are gone")
    index["active"] = version_id
    _write_versions(hash_hex, index)
    try:
        script = json.loads(
            (_version_dir(hash_hex, version_id) / "script.json").read_text())
    except (OSError, ValueError):
        script = None
    if isinstance(script, dict):
        publish_script(hash_hex, script, title)
    return entry


def rename_version(hash_hex: str, version_id: str, name: str) -> dict:
    """Name a version, which also pins it.

    Clearing the name unpins it — the two are one decision said twice,
    and a version with no name that survives the prune forever would be a
    pin nobody can see or undo.
    """
    index = _read_versions(hash_hex)
    entry = next((e for e in index.get("versions") or []
                  if e.get("id") == version_id), None)
    if entry is None:
        raise ValueError("no such version")
    entry["name"] = str(name or "").strip()[:60]
    entry["pinned"] = bool(entry["name"])
    _write_versions(hash_hex, index)
    return entry


def delete_version(hash_hex: str, version_id: str) -> None:
    """Remove a version for good. The live one is refused."""
    index = _read_versions(hash_hex)
    entry = next((e for e in index.get("versions") or []
                  if e.get("id") == version_id), None)
    if entry is None:
        raise ValueError("no such version")
    if index.get("active") == version_id:
        raise ValueError("that is the show this track plays — make another "
                         "one live first, then delete this")
    index["versions"] = [e for e in index["versions"] if e is not entry]
    _write_versions(hash_hex, index)
    _remove_dir(hash_hex, version_id)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return slug[:48] or "track"


def mirror_name(hash_hex: str, title: str = "") -> str:
    """`<track>-<hash8>.json`. The hash is in the name because it is the
    identity, and the title is in it because a folder of hashes is a
    folder nobody can find anything in."""
    return f"{_slug(title)}-{hash_hex[:8]}.json"


def find_mirror(hash_hex: str) -> Path | None:
    """The mirrored script for a track, whatever it ended up called."""
    _track_dir(hash_hex)  # validates the hash before it becomes a glob
    try:
        matches = sorted(SHARED_SHOWS.glob(f"*-{hash_hex[:8]}.json"))
    except OSError:
        return None
    return matches[0] if matches else None


def publish_script(hash_hex: str, script: dict, title: str = "") -> Path | None:
    """Mirror the script to the shared volume. Never fatal.

    A failed mirror costs the ability to hand-edit that one show; the
    show itself is already saved. Skipped entirely when the shared
    volume's parent is missing, so a dev checkout does not grow a stray
    /config.
    """
    if not SHARED_SHOWS.parent.parent.is_dir():
        return None
    target = SHARED_SHOWS / mirror_name(hash_hex, title)
    try:
        SHARED_SHOWS.mkdir(parents=True, exist_ok=True)
        # A retitled track would otherwise leave its old file behind, and
        # two files for one show is two answers to "which one do I edit".
        for stale in SHARED_SHOWS.glob(f"*-{hash_hex[:8]}.json"):
            if stale != target:
                stale.unlink(missing_ok=True)
        atomic_write.write_json(target, script, indent=2)
    except OSError:
        return None
    return target


def read_mirrored_script(hash_hex: str) -> dict | None:
    """What is in the hand-edited file right now, or None.

    Raises ValueError with the JSON parser's own complaint when the file
    is there and unreadable — "expecting ',' delimiter: line 42" is the
    single most useful sentence you can hand somebody who has just edited
    a thousand-line JSON file.
    """
    path = find_mirror(hash_hex)
    if path is None:
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{path.name} is not valid JSON — {exc}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} does not hold a show script object")
    return data


def scan_all(folders) -> list[dict]:
    """Every audio file under every folder, listed once.

    De-duplicated by track hash, because one track can be reachable twice:
    a folder nested inside another one, or the same file copied into both.
    Identity is the content hash everywhere else in this add-on, so it is
    the content hash here — two paths to one track are one track, and it
    keeps the one found first.
    """
    cache = _HashCache()
    seen: set[str] = set()
    tracks: list[dict] = []
    for folder in folders:
        for entry in scan(folder, cache):
            if entry["hash"] in seen:
                continue
            seen.add(entry["hash"])
            tracks.append(entry)
    cache.save()
    return tracks


def scan(folder: Path, cache: "_HashCache | None" = None) -> list[dict]:
    """Every audio file under `folder`, with its hash and analysis state."""
    tracks = []
    folder = Path(folder)
    if not folder.is_dir():
        return tracks
    # A scan of one folder gets a throwaway cache it never saves: pruning
    # is only safe once every folder has been walked, and a lone folder
    # cannot know what the others were going to claim.
    owned = cache is None
    if cache is None:
        cache = _HashCache()
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        try:
            hash_hex = cache.hash_for(path, path.stat())
        except OSError:
            continue
        analysis = load_analysis(hash_hex)
        entry = {
            "file": str(path),
            "name": path.stem,
            "hash": hash_hex,
            # `analyzed` stays true for an out-of-date analysis: it still
            # has beats and a duration, so the track still plays and the
            # party queue must not lose it over a field it never needed.
            # `stale` is the separate, narrower claim — this one is worth
            # running again — and it is what the Analyze pass picks up.
            "analyzed": analysis is not None,
            "stale": is_stale(analysis),
        }
        if analysis:
            entry["summary"] = {
                "bpm": analysis.get("bpm"),
                # duration_of, not the tag: the listing is where a person
                # checks their music, and it must not be the one view
                # still repeating a lying VBR header.
                "duration": duration_of(analysis),
                "sections": len(analysis.get("sections") or []),
                "drops": len(analysis.get("drops") or []),
                # What the current analyzer heard beyond the structure.
                # Zero here on a stale row is the visible half of the
                # version check: the number a person can point at.
                "hits": len(analysis.get("hits") or []),
                "chords": len(((analysis.get("music") or {})
                               .get("chords")) or []),
                "notes": len(((analysis.get("music") or {})
                              .get("notes")) or []),
                "lyrics": bool((analysis.get("lyrics") or {}).get("synced")),
            }
            show = load_show(hash_hex)
            if show:
                entry["show"] = {
                    "tier": show.get("tier"),
                    "palette": show.get("palette_name"),
                    "cues": (show.get("stats") or {}).get("cues"),
                }
        tracks.append(entry)
    if owned:
        cache.save(prune=False)
    return tracks
