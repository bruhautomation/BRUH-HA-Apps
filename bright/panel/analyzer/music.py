"""What the song is PLAYING: harmony, melody, phrases and repetition.

Everything else in this package answers rhythm — where the beats are, when
the energy jumps, where a section turns over. That is enough to mark a
song's structure and nothing like enough to follow its *music*. A show
built only on sections and drops changes when the arrangement changes and
sits still through everything in between, which is most of the record.

This module answers four musical questions the lights can actually act on:

- **What chord is sounding** (`chords`). Harmony changes on its own clock —
  usually every bar or two, almost never where the energy changes — so a
  palette that follows the chord moves with the song rather than with its
  structure. This is the single biggest reason a show can look musical
  instead of merely synchronized.
- **What note the tune is on** (`melody_notes`). The dominant pitch in the
  melodic register, segmented into note events. Not a transcription and
  never claimed as one: it tracks the loudest melodic voice, which on a
  dense mix is the hook, the vocal, or the lead — exactly the line a
  person hears and expects the lights to answer.
- **Where the phrases are** (`phrases`). Notes come in breaths separated by
  rests. A phrase is the natural window for a gesture that travels; a
  sweep that starts mid-phrase reads as an accident.
- **What repeats** (`repeats`). Beat-synchronous chroma self-similarity
  finds the chorus coming back, and coming back is what a chorus is FOR.
  Giving a repeat the look it had the first time is what makes a show feel
  like it knows the song rather than reacting to it.

Pure numpy, like the rest of the analyzer (librosa drags in numba, which
is painful on musl). Everything is measured against the decoded PCM's own
timeline — the same seconds the compiler lays cues out on.

Nothing here is exact, and the shapes are chosen so that being a little
wrong is harmless: a mis-detected chord shifts a hue, a missed note drops
one flash. What must never happen is a confident answer where the audio
holds none, so every extractor has a floor below which it says nothing.
"""
from __future__ import annotations

import numpy as np

# A bigger window than the beat tracker's: pitch needs frequency
# resolution where onsets need time resolution. 4096 at 22050Hz is 5.4Hz
# per bin — about a quarter-semitone at the bottom of the melodic range —
# and the 1024 hop still samples 21.5 times a second, which is finer than
# any note a light show can answer.
FRAME = 4096
HOP = 1024

# The pitched range worth analysing. Below C2 is bass fundamentals that
# blur into the kick; above C7 is air and cymbals, which have no pitch to
# follow.
FMIN_HZ = 65.0
FMAX_HZ = 2100.0

# Where a melody lives. Deliberately narrower than the chroma range: a
# lead line, a vocal and a topline synth all sit between C3 and C6, and
# including the bass guitar is how a "melody" tracker ends up following
# the root note of every chord.
MELODY_MIN_HZ = 130.0
MELODY_MAX_HZ = 1100.0

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Caps. An analysis is a file somebody may open and a prompt somebody
# pays for, so every list here is bounded and says what it dropped.
MAX_NOTES = 600
MAX_CHORDS = 240
MAX_PHRASES = 80
MAX_REPEATS = 12

# A note has to last this long to be a note rather than a smear between
# two others. 90ms is about a 32nd note at 160bpm.
MIN_NOTE_S = 0.09

# Below this fraction of the track's peak melodic energy, a frame is not
# carrying a tune — it is a rest, a drum fill, or a breakdown.
MELODY_FLOOR = 0.10

# Chord detection needs the harmony to be clearly ONE chord. Below this
# margin between the best and second-best template the frame is
# ambiguous, and an ambiguous chord that is reported anyway is a palette
# that flickers between two colours on a held note.
CHORD_MARGIN = 0.02


def _frames(pcm: np.ndarray) -> np.ndarray | None:
    usable = (len(pcm) - FRAME) // HOP
    if usable <= 2:
        return None
    return np.lib.stride_tricks.as_strided(
        pcm, shape=(usable, FRAME),
        strides=(pcm.strides[0] * HOP, pcm.strides[0]))


def spectra(pcm: np.ndarray) -> np.ndarray | None:
    """The one STFT the rest of this module shares.

    Chroma and melody are two questions about the same numbers, and the
    transform is the expensive part — computing it per question would
    double the cost of analysing a track for nothing.
    """
    framed = _frames(pcm)
    if framed is None:
        return None
    window = np.hanning(FRAME).astype(np.float32)
    return np.abs(np.fft.rfft(framed * window, axis=1))


def frame_rate(sample_rate: int) -> float:
    return sample_rate / HOP


def chromagram(mags: np.ndarray, sample_rate: int) -> np.ndarray:
    """Energy per pitch class, per frame — the harmony, with the octave
    thrown away.

    Octave-folding is the point: a chord is the same chord whether the
    guitar voices it low or the strings high, and a lighting palette that
    changed because the arrangement moved up an octave would be reading
    the wrong thing. Each frame is normalized to its own peak so a quiet
    bar and a loud one are compared on their harmony rather than their
    volume.
    """
    freqs = np.fft.rfftfreq(FRAME, 1.0 / sample_rate)
    inside = (freqs >= FMIN_HZ) & (freqs <= FMAX_HZ)
    if not inside.any():
        return np.zeros((mags.shape[0], 12), dtype=np.float32)
    # Bin → pitch class, via MIDI number. The map is a matrix rather than
    # a loop because it is applied to every frame of the track.
    midi = 69.0 + 12.0 * np.log2(np.maximum(freqs[inside], 1e-6) / 440.0)
    classes = np.rint(midi).astype(int) % 12
    fold = np.zeros((int(inside.sum()), 12), dtype=np.float32)
    fold[np.arange(fold.shape[0]), classes] = 1.0
    chroma = (mags[:, inside] ** 2) @ fold
    peaks = chroma.max(axis=1, keepdims=True)
    return (chroma / np.maximum(peaks, 1e-9)).astype(np.float32)


# ---------------------------------------------------------------------------
# Harmony
# ---------------------------------------------------------------------------
def _templates() -> tuple[np.ndarray, list[tuple[int, str]]]:
    """24 triads as pitch-class masks: every root, major and minor.

    Only triads. Sevenths and extensions would each need their own
    template and would mostly compete with the plain triad they contain —
    more ways to be marginally right about a distinction no light can
    show. The root and the third are what a colour can carry.
    """
    rows, labels = [], []
    for root in range(12):
        for quality, intervals in (("maj", (0, 4, 7)), ("min", (0, 3, 7))):
            mask = np.zeros(12, dtype=np.float32)
            for interval in intervals:
                mask[(root + interval) % 12] = 1.0
            rows.append(mask / np.linalg.norm(mask))
            labels.append((root, quality))
    return np.stack(rows), labels


TEMPLATES, TEMPLATE_LABELS = _templates()


def _beat_chroma(chroma: np.ndarray, rate: float,
                 beats: list[float]) -> tuple[np.ndarray, list[float]]:
    """Chroma averaged between consecutive beats.

    Harmony is a per-beat fact, not a per-frame one: averaging over the
    beat suppresses passing notes and the attack transients that make a
    frame-by-frame chord track flicker. With no beat grid, half-second
    windows stand in — worse, but never nothing.
    """
    if len(beats) >= 4:
        edges = [float(b) for b in beats]
    else:
        span = chroma.shape[0] / rate
        edges = list(np.arange(0.0, span, 0.5))
    rows, times = [], []
    for start, end in zip(edges, edges[1:]):
        lo = int(start * rate)
        hi = max(lo + 1, int(end * rate))
        if lo >= chroma.shape[0]:
            break
        block = chroma[lo:min(hi, chroma.shape[0])]
        if not block.size:
            continue
        mean = block.mean(axis=0)
        norm = np.linalg.norm(mean)
        rows.append(mean / norm if norm > 1e-9 else mean)
        times.append(start)
    if not rows:
        return np.zeros((0, 12), dtype=np.float32), []
    return np.stack(rows).astype(np.float32), times


def chords(chroma: np.ndarray, rate: float, beats: list[float]) -> list[dict]:
    """Where the harmony CHANGES, and to what.

    Changes rather than a chord per beat: a show acts on the change, and
    a list with the same chord forty times running is forty rows nobody
    reads and a prompt nobody can afford. A beat whose best template
    barely beats its runner-up is left as a continuation of whatever was
    sounding, because reporting the flicker is worse than missing the
    change.
    """
    per_beat, times = _beat_chroma(chroma, rate, beats)
    if not per_beat.size:
        return []
    scores = per_beat @ TEMPLATES.T                       # [beats, 24]
    best = np.argmax(scores, axis=1)
    ordered = np.sort(scores, axis=1)
    margin = ordered[:, -1] - ordered[:, -2]
    out: list[dict] = []
    current: str | None = None
    for index, at in enumerate(times):
        if margin[index] < CHORD_MARGIN:
            continue                                      # ambiguous: hold
        root, quality = TEMPLATE_LABELS[int(best[index])]
        name = NOTE_NAMES[root] + ("m" if quality == "min" else "")
        if name == current:
            continue
        current = name
        out.append({"t": round(float(at), 3), "name": name, "root": int(root),
                    "quality": quality,
                    "confidence": round(float(scores[index, best[index]]), 3)})
        if len(out) >= MAX_CHORDS:
            break
    return out


# Krumhansl-Schmuckler key profiles, normalized. A key is one word that
# tells a director more about a song's colour than any number here — and
# unlike a chord, it cannot flicker.
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19,
                           2.39, 3.66, 2.29, 2.88], dtype=np.float32)
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75,
                           3.98, 2.69, 3.34, 3.17], dtype=np.float32)


def key_of(chroma: np.ndarray) -> str | None:
    """The track's key, by profile correlation over the whole song."""
    if not chroma.size:
        return None
    total = chroma.mean(axis=0)
    if float(total.max()) <= 0:
        return None
    total = (total - total.mean()) / (total.std() or 1e-9)
    best, best_score = None, -1e9
    for root in range(12):
        for profile, quality in ((_MAJOR_PROFILE, ""), (_MINOR_PROFILE, "m")):
            shifted = np.roll(profile, root)
            shifted = (shifted - shifted.mean()) / (shifted.std() or 1e-9)
            score = float(np.dot(total, shifted))
            if score > best_score:
                best, best_score = NOTE_NAMES[root] + quality, score
    return best


# ---------------------------------------------------------------------------
# Melody
# ---------------------------------------------------------------------------
def _harmonic_pitch(mags: np.ndarray, sample_rate: int) -> tuple[np.ndarray,
                                                                 np.ndarray]:
    """Per frame: the dominant melodic pitch (MIDI, float) and its strength.

    A plain spectral peak follows whichever partial is loudest, which on
    anything with a real timbre is routinely the second or third harmonic
    — a melody tracker built on it reports a tune an octave or a fifth
    above the one being played. Summing each candidate with its own
    harmonics fixes that: the true fundamental collects energy from every
    partial above it, and a harmonic mistaken for a fundamental collects
    only the ones it happens to share.

    Weights decay because higher partials are quieter and noisier; the
    sum form rather than the classic product form because a product is
    destroyed by one missing partial, which real instruments have all the
    time.
    """
    freqs = np.fft.rfftfreq(FRAME, 1.0 / sample_rate)
    candidates = np.where((freqs >= MELODY_MIN_HZ) & (freqs <= MELODY_MAX_HZ))[0]
    if not candidates.size:
        empty = np.zeros(mags.shape[0], dtype=np.float32)
        return empty, empty
    score = mags[:, candidates].copy()
    for harmonic, weight in ((2, 0.5), (3, 0.33), (4, 0.25)):
        index = candidates * harmonic
        keep = index < mags.shape[1]
        score[:, keep] += weight * mags[:, index[keep]]
    # And the mirror of it: a candidate sitting on top of a much louder
    # bin an octave or a twelfth BELOW is not a fundamental, it is
    # somebody else's harmonic. Without this the tracker follows the bass
    # up into the melodic range whenever the tune rests — measured on a
    # synthesized tune over a bass drone, which reported a phantom note
    # for the whole of the rest. Subtracted rather than rejected, because
    # a real melody over a loud bass has to keep winning its own frame.
    for divisor, weight in ((2, 0.6), (3, 0.35)):
        index = candidates // divisor
        keep = index >= 1
        score[:, keep] -= weight * mags[:, index[keep]]
    np.clip(score, 0.0, None, out=score)
    picked = np.argmax(score, axis=1)
    strength = score[np.arange(score.shape[0]), picked]
    hz = freqs[candidates[picked]]
    midi = 69.0 + 12.0 * np.log2(np.maximum(hz, 1e-6) / 440.0)
    return midi.astype(np.float32), strength.astype(np.float32)


def _median3(values: np.ndarray) -> np.ndarray:
    """Three-point median — one frame of octave jitter is not a note."""
    if values.size < 3:
        return values
    stacked = np.stack([values[:-2], values[1:-1], values[2:]])
    middle = np.median(stacked, axis=0)
    return np.concatenate([values[:1], middle, values[-1:]])


def melody_notes(mags: np.ndarray, sample_rate: int) -> list[dict]:
    """The melodic line as note events: when, how long, which pitch.

    Frames whose melodic energy is under the floor produce no note at all
    — that is a rest, and a light show that keeps flashing through the
    breakdown because the tracker never admits silence is worse than one
    that does nothing there.

    Each note carries its pitch class (what a hue can be derived from),
    its octave (what a register-aware effect can use to pick a fixture)
    and a strength normalized to the track's own loudest note.
    """
    if not mags.size:
        return []
    rate = frame_rate(sample_rate)
    midi, strength = _harmonic_pitch(mags, sample_rate)
    peak = float(strength.max()) or 1.0
    strength = strength / peak
    midi = _median3(midi)
    voiced = strength >= MELODY_FLOOR
    semitone = np.rint(midi).astype(int)

    notes: list[dict] = []
    start = None
    for index in range(len(semitone)):
        here = bool(voiced[index])
        same = (start is not None and here
                and semitone[index] == semitone[start])
        if same:
            continue
        if start is not None:
            end = index
            duration = (end - start) / rate
            if duration >= MIN_NOTE_S:
                pitch = int(semitone[start])
                notes.append({
                    "t": round(start / rate, 3),
                    "d": round(duration, 3),
                    "m": pitch,
                    "pc": pitch % 12,
                    "s": round(float(strength[start:end].mean()), 3),
                })
            start = None
        if here:
            start = index
    if start is not None:
        duration = (len(semitone) - start) / rate
        if duration >= MIN_NOTE_S:
            pitch = int(semitone[start])
            notes.append({"t": round(start / rate, 3),
                          "d": round(duration, 3), "m": pitch,
                          "pc": pitch % 12,
                          "s": round(float(strength[start:].mean()), 3)})

    if len(notes) > MAX_NOTES:
        # Keep the loudest, then put them back in time order: a melody
        # read out of order is not a melody, and the cap has to fall on
        # the notes nobody would have noticed.
        notes = sorted(notes, key=lambda n: n["s"], reverse=True)[:MAX_NOTES]
        notes.sort(key=lambda n: n["t"])
    return notes


def phrases(notes: list[dict], beat_s: float) -> list[dict]:
    """Notes grouped into breaths, each with the shape of its line.

    The gap that ends a phrase is musical, not absolute: at 90bpm a
    half-second rest is nothing and at 160 it is two beats of silence, so
    the threshold is beats. `dir` is the direction of the line — a rising
    phrase and a falling one want different gestures, and it is the one
    thing about a melody that survives being turned into light.
    """
    if not notes:
        return []
    gap = max(0.45, 1.75 * max(0.1, beat_s))
    groups: list[list[dict]] = [[notes[0]]]
    for note in notes[1:]:
        last = groups[-1][-1]
        if note["t"] - (last["t"] + last["d"]) > gap:
            groups.append([note])
        else:
            groups[-1].append(note)

    out = []
    for group in groups:
        if len(group) < 3:
            continue                       # two notes is a gesture, not a phrase
        pitches = np.array([n["m"] for n in group], dtype=np.float32)
        slope = float(np.polyfit(np.arange(len(pitches)), pitches, 1)[0])
        out.append({
            "start": group[0]["t"],
            "end": round(group[-1]["t"] + group[-1]["d"], 3),
            "notes": len(group),
            "lo": int(pitches.min()), "hi": int(pitches.max()),
            "dir": "rise" if slope > 0.35 else
                   ("fall" if slope < -0.35 else "flat"),
        })
        if len(out) >= MAX_PHRASES:
            break
    return out


# ---------------------------------------------------------------------------
# Repetition
# ---------------------------------------------------------------------------
MIN_REPEAT_BEATS = 8
REPEAT_THRESHOLD = 0.82


def repeats(chroma: np.ndarray, rate: float, beats: list[float]) -> list[dict]:
    """Passages that come back, and what they come back from.

    Beat-synchronous chroma compared against itself: a repeat is a run of
    beats whose harmony matches the run some fixed number of beats
    earlier. That is a coarse instrument and deliberately so — it finds
    the chorus returning, which is the repetition a show should answer,
    and misses the clever ones, which it never had to catch.

    Runs are found per lag and kept longest-first, non-overlapping, so
    what comes back is a handful of real passages rather than a hundred
    overlapping near-misses.
    """
    per_beat, times = _beat_chroma(chroma, rate, beats)
    count = per_beat.shape[0]
    if count < 2 * MIN_REPEAT_BEATS:
        return []
    similarity = per_beat @ per_beat.T
    found: list[dict] = []
    for lag in range(MIN_REPEAT_BEATS, count - MIN_REPEAT_BEATS):
        diagonal = np.array([similarity[i, i + lag]
                             for i in range(count - lag)])
        above = diagonal >= REPEAT_THRESHOLD
        run_start = None
        for index in range(len(above) + 1):
            inside = index < len(above) and bool(above[index])
            if inside and run_start is None:
                run_start = index
            elif not inside and run_start is not None:
                length = index - run_start
                if length >= MIN_REPEAT_BEATS:
                    found.append({
                        "start": round(times[run_start + lag], 2),
                        "end": round(times[min(len(times) - 1,
                                               index + lag)], 2),
                        "same_as": round(times[run_start], 2),
                        "beats": int(length),
                        "score": round(float(diagonal[run_start:index].mean()),
                                       3),
                    })
                run_start = None

    found.sort(key=lambda r: (-r["beats"], -r["score"]))
    kept: list[dict] = []
    for candidate in found:
        if any(candidate["start"] < other["end"]
               and other["start"] < candidate["end"] for other in kept):
            continue                       # one answer per stretch of song
        kept.append(candidate)
        if len(kept) >= MAX_REPEATS:
            break
    kept.sort(key=lambda r: r["start"])
    return kept


# ---------------------------------------------------------------------------
# The one call the pipeline makes
# ---------------------------------------------------------------------------
def analyze_music(pcm: np.ndarray, sample_rate: int,
                  beats: list[float], beat_s: float) -> dict:
    """Harmony, melody, phrases and repetition, from one STFT pass."""
    mags = spectra(pcm)
    if mags is None:
        return {"key": None, "chords": [], "notes": [], "phrases": [],
                "repeats": []}
    rate = frame_rate(sample_rate)
    chroma = chromagram(mags, sample_rate)
    notes = melody_notes(mags, sample_rate)
    return {
        "key": key_of(chroma),
        "chords": chords(chroma, rate, beats),
        "notes": notes,
        "phrases": phrases(notes, beat_s),
        "repeats": repeats(chroma, rate, beats),
    }
