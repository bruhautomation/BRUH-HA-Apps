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

from . import beats, decode, features, library, lyrics, music, sections
# One definition, two readers: `scan` decides staleness with it and every
# analysis is stamped with it. See library.ANALYSIS_VERSION for why a
# version that nothing compares against is not a version.
from .library import ANALYSIS_VERSION


def analyze_track(path: Path) -> dict:
    """Blocking. Returns the analysis dict it also persisted."""
    path = Path(path)
    hash_hex = library.track_hash(path)
    pcm = decode.pcm(path)
    duration_s = len(pcm) / decode.SAMPLE_RATE
    tags = decode.tags(path)
    # The measured length REPLACES whatever the header claimed. mutagen's
    # `info.length` is read from the file's header, and a VBR file without
    # a proper Xing header reports an estimate from the first frame's
    # bitrate — wrong by whole multiples, which is how a four-minute song
    # analysed as twenty-six. The PCM was just decoded; its length is not
    # an estimate. Everything downstream schedules against this number:
    # the compiler lays the show out over it, and the conductor sleeps out
    # its tail after the last cue, so a lying header did not just draw a
    # long waveform — it parked the party queue for the difference.
    tags["duration"] = round(duration_s, 2)

    rhythm = beats.analyze_beats(pcm, decode.SAMPLE_RATE)
    bands = features.band_energies(pcm, decode.SAMPLE_RATE)
    beat_s = 60.0 / max(1.0, float(rhythm.get("bpm") or 120.0))
    # What the song is PLAYING, as opposed to when it hits: chords, the
    # melodic line, its phrases, and the passages that come back. One
    # extra STFT pass over audio that is already decoded.
    musical = music.analyze_music(pcm, decode.SAMPLE_RATE,
                                  rhythm.get("beats") or [], beat_s)
    analysis = {
        "version": ANALYSIS_VERSION,
        "file": str(path),
        "hash": hash_hex,
        "analyzed_at": time.time(),
        # The one authoritative length, measured from the decoded audio.
        # `tags["duration"]` carries the same value for older readers, but
        # this is the field new code should reach for — see
        # `library.duration_of`, which also heals analyses from before it.
        "duration_s": round(duration_s, 2),
        "tags": tags,
        "bpm": rhythm["bpm"],
        "beats": rhythm["beats"],
        "downbeats": rhythm["downbeats"],
        "onsets": rhythm["onsets"],
        # Ranked accents with their place against the beat grid — what a
        # stab lands on. `onsets` says where something happened; `hits`
        # says what was worth a light.
        "hits": rhythm.get("hits", []),
        "beat_method": rhythm["method"],
        # The musical map: `key`, `chords` (changes only), `notes` (the
        # melodic line), `phrases`, `repeats`. Rhythm says when the song
        # hits; this says what it is playing, and it is what lets a show
        # follow the tune instead of only marking the structure.
        "music": musical,
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
    # An out-of-date analysis is re-run without being asked twice. This is
    # the whole point of the version: a person who has already scanned
    # their library is exactly the person a new analyzer field can never
    # reach otherwise, and "press Analyze again" is not something anybody
    # knows to do about a feature they were never told they were missing.
    todo = [t for t in tracks
            if force or not t["analyzed"] or t.get("stale")]
    stale = sum(1 for t in todo if t["analyzed"] and t.get("stale"))
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
              # Named separately because it is a different sentence: nine
              # new tracks and nine re-read ones are the same number and
              # not the same news.
              "refreshed": stale, "failed": failed}
    if progress:
        progress({"total": len(todo), "done": done, "failed": len(failed),
                  "current": None})
    return result
