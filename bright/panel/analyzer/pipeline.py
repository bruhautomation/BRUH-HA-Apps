"""One track, analyzed end to end: decode → beats → features → sections →
lyrics → analysis.json. And the folder loop the Library tab runs.

Analysis is the expensive step that happens BEFORE the party — the whole
architecture precomputes here so playback is only a clock and a cue list.
Everything below runs in a worker thread (numpy releases the GIL for the
heavy parts) via the jobs registry.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable

from . import beats, decode, features, library, lyrics, sections

ANALYSIS_VERSION = 1


def analyze_track(path: Path) -> dict:
    """Blocking. Returns the analysis dict it also persisted."""
    path = Path(path)
    hash_hex = library.track_hash(path)
    pcm = decode.pcm(path)
    duration_s = len(pcm) / decode.SAMPLE_RATE
    tags = decode.tags(path)
    tags.setdefault("duration", round(duration_s, 2))
    if not tags.get("duration"):
        tags["duration"] = round(duration_s, 2)

    rhythm = beats.analyze_beats(pcm, decode.SAMPLE_RATE)
    bands = features.band_energies(pcm, decode.SAMPLE_RATE)
    analysis = {
        "version": ANALYSIS_VERSION,
        "file": str(path),
        "hash": hash_hex,
        "analyzed_at": time.time(),
        "tags": tags,
        "bpm": rhythm["bpm"],
        "beats": rhythm["beats"],
        "downbeats": rhythm["downbeats"],
        "onsets": rhythm["onsets"],
        "beat_method": rhythm["method"],
        "features": bands,
        "brightness": features.brightness_hint(pcm, decode.SAMPLE_RATE),
        # The picture of the song, computed here because the decode has
        # already happened — asking for it later means running ffmpeg over
        # the whole track again to draw a few hundred pixels.
        "envelope": features.envelope(pcm),
        "sections": sections.find_sections(bands, duration_s),
        "drops": sections.find_drops(bands),
        "lyrics": lyrics.fetch(tags.get("artist", ""), tags.get("title", ""),
                               tags.get("album", ""), tags.get("duration")),
    }
    library.save_analysis(hash_hex, analysis)
    return analysis


async def analyze_folder(folder: Path,
                         progress: Callable[[dict], None] | None = None,
                         force: bool = False) -> dict:
    """One folder — `analyze_folders` with a list of one."""
    return await analyze_folders([folder], progress=progress, force=force)


async def analyze_folders(folders,
                          progress: Callable[[dict], None] | None = None,
                          force: bool = False) -> dict:
    """The Library tab's job: every unanalyzed track in every folder, one at
    a time (analysis is CPU-bound; two at once just thrash), reporting
    progress after each.

    The folders are scanned together and de-duplicated before any work
    starts, so the count the progress bar counts down from is the number of
    tracks there are — not the number of paths they can be reached by, which
    is what a per-folder loop would have made it.
    """
    tracks = await asyncio.to_thread(library.scan_all, list(folders))
    todo = [t for t in tracks if force or not t["analyzed"]]
    done, failed = 0, []
    for index, track in enumerate(todo):
        if progress:
            progress({"total": len(todo), "done": done, "failed": len(failed),
                      "current": track["name"]})
        try:
            await asyncio.to_thread(analyze_track, Path(track["file"]))
            done += 1
        except Exception as exc:  # noqa: BLE001 — one bad file must not end the folder
            failed.append({"file": track["file"], "error": str(exc)})
    result = {"analyzed": done, "skipped": len(tracks) - len(todo),
              "failed": failed}
    if progress:
        progress({"total": len(todo), "done": done, "failed": len(failed),
                  "current": None})
    return result
