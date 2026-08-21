"""Named sets: a saved answer to "put the usual thing on".

A set is the handful of decisions somebody would otherwise make in the
panel every time — which speaker, which songs (and which of each song's
shows), which lights are allowed to join in, and what the room should
look like when it ends. Named, so an automation, a dashboard button or a voice command
can ask for one by name and get exactly the evening that was set up
rather than the defaults.

There is deliberately NO vibe here any more. It steered the director,
which is a COMPILE-time decision, and it only ever reached a track that
had no show yet — so on a library you had already built shows for it did
nothing at all, and on a fresh one it silently changed what was written
to disk forever without saying so. Two parties naming different vibes
over one track gave whichever ran first. That is not a rough edge on a
feature; it is a field that cannot have a coherent meaning where it was.
It lives on the Shows tab now, beside the button that compiles.

The end scene is the part that is not obvious. Stopping a show restores
every light to what it was before the show started, which is right when
the show was an interruption and wrong at 1am — what people want then is
"everything off" or "night lights", and that is a Home Assistant scene
they already have. So a party may name one, and stopping it calls that
scene INSTEAD of restoring: two answers to "put the room back" would
fight, and the one a person configured wins.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import atomic_write
from analyzer import library

PARTIES_FILE = (Path(os.environ.get("BRIGHT_STATE", "/data"))
                / "parties.json")

MAX_PARTIES = 50
_NAME_RE = re.compile(r"^[\w \-'&().,!]{1,48}$")
_ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def load() -> list[dict]:
    try:
        data = json.loads(PARTIES_FILE.read_text())
    except (OSError, ValueError):
        return []
    parties = data.get("parties") if isinstance(data, dict) else data
    return parties if isinstance(parties, list) else []


def _save(parties: list[dict]) -> None:
    atomic_write.write_json(PARTIES_FILE,
                            {"version": 1, "updated_at": time.time(),
                             "parties": parties}, indent=2)


def clean(raw: dict) -> dict:
    """One party off the wire. Raises ValueError with a showable message."""
    if not isinstance(raw, dict):
        raise ValueError("a party must be an object")
    name = str(raw.get("name", "")).strip()
    if not _NAME_RE.fullmatch(name):
        raise ValueError("give the party a name (letters, digits, spaces and "
                         "simple punctuation, up to 48 characters)")
    party: dict = {"name": name}

    for key, domain in (("media_player", "media_player"),
                        ("end_scene", "scene")):
        value = str(raw.get(key, "") or "")
        if value:
            if not _ENTITY_RE.fullmatch(value) or not value.startswith(domain + "."):
                raise ValueError(f"{key} must be a {domain} entity id")
            party[key] = value

    folder = str(raw.get("folder", "") or "")
    if folder:
        if not folder.startswith("/media"):
            raise ValueError("a party's folder must live under /media")
        party["folder"] = folder[:200]

    party["note"] = str(raw.get("note", "") or "")[:200]

    # The playlist: exact tracks, in order, by content hash. When set it
    # REPLACES the folder scan — a playlist is a choice of songs, and
    # merging it with "everything in the folder" would un-choose them.
    # Hashes rather than paths, because identity survives a rename and a
    # playlist is a thing people keep. Order is the order given: that is
    # what makes it a playlist rather than a filter.
    tracks = raw.get("tracks")
    party["tracks"] = ([str(t) for t in tracks
                        if isinstance(t, str)
                        and library.is_track_hash(t)][:500]
                       if isinstance(tracks, list) else [])

    # Which show each song plays, when it is not simply the live one.
    #
    # A pin, not a copy of the show: the version stays where it is and
    # keeps its own name, and un-pinning is deleting a key. Only songs
    # in the playlist may be pinned — a pin for a song this set does not
    # play is a line that can never do anything, and it would survive
    # every edit that removed the song it was about.
    wanted = raw.get("versions")
    party["versions"] = {}
    if isinstance(wanted, dict):
        allowed = set(party["tracks"])
        for track, version in list(wanted.items())[:500]:
            if (isinstance(version, str) and track in allowed
                    and re.fullmatch(r"[0-9a-z]{1,24}", version)):
                party["versions"][track] = version

    # Shuffle defaults OFF the moment a playlist exists: its order IS the
    # request, and a default that randomizes what somebody just ordered
    # is the feature contradicting itself. A folder party still shuffles
    # by default — a folder has no order to defend. Explicitly asking is
    # still honoured either way.
    party["shuffle"] = bool(raw.get("shuffle", not party["tracks"]))

    # Which lights this party is allowed to use. Empty means every light
    # on the map — the same "unset means all" rule an effect's selection
    # follows, so there is one thing to learn rather than two.
    fixtures = raw.get("fixtures")
    party["fixtures"] = ([str(f)[:80] for f in fixtures if isinstance(f, str)][:200]
                         if isinstance(fixtures, list) else [])
    return party


def save(raw: dict) -> dict:
    party = clean(raw)
    parties = [p for p in load() if p.get("name") != party["name"]]
    if len(parties) >= MAX_PARTIES:
        raise ValueError(f"the party list is full ({MAX_PARTIES})")
    party["saved_at"] = time.time()
    parties.append(party)
    _save(sorted(parties, key=lambda p: p["name"].lower()))
    return party


def remove(name: str) -> bool:
    parties = load()
    kept = [p for p in parties if p.get("name") != name]
    if len(kept) == len(parties):
        return False
    _save(kept)
    return True


def get(name: str) -> dict | None:
    """A party by name, matched case-insensitively.

    Because the name is what an automation or a voice command types, and
    "Saturday Night" and "saturday night" are the same party to everyone
    except a string comparison.
    """
    wanted = str(name or "").strip().lower()
    for party in load():
        if str(party.get("name", "")).lower() == wanted:
            return party
    return None
