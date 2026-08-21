#!/usr/bin/env python3
"""BRight's analyzer, measured against synthesized ground truth.

Every rhythmic test builds its own audio — a kick pattern at a KNOWN tempo,
an energy arc with KNOWN section boundaries — so the analyzer is graded
against answers it did not produce. No fixtures, no golden files, no ffmpeg
(the decode boundary is the one thing mocked).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

import numpy as np  # noqa: E402

from analyzer import beats, features, library, lyrics, sections  # noqa: E402

SR = 22050


def kick(sample_rate=SR, length_s=0.10) -> np.ndarray:
    """A synthesized kick drum: a pitch-dropping sine with a fast decay."""
    t = np.arange(int(length_s * sample_rate)) / sample_rate
    freq = 150.0 * np.exp(-t * 18.0) + 45.0
    return (np.sin(2 * np.pi * np.cumsum(freq) / sample_rate)
            * np.exp(-t * 32.0)).astype(np.float32)


def drum_track(bpm: float, seconds: float, sample_rate=SR,
               offset_s: float = 0.0, noise: float = 0.005) -> np.ndarray:
    rng = np.random.default_rng(seed=5)
    total = int(seconds * sample_rate)
    audio = rng.normal(0.0, noise, total).astype(np.float32)
    hit = kick(sample_rate)
    period = 60.0 / bpm
    t = offset_s
    while t < seconds:
        start = int(t * sample_rate)
        end = min(total, start + len(hit))
        audio[start:end] += hit[:end - start]
        t += period
    return audio


class TestBeats(unittest.TestCase):
    def test_finds_the_tempo(self):
        for bpm in (100.0, 128.0, 174.0):
            with self.subTest(bpm=bpm):
                audio = drum_track(bpm, 30.0)
                result = beats.analyze_beats(audio, SR)
                self.assertLess(abs(result["bpm"] - bpm) / bpm, 0.03,
                                f"answered {result['bpm']} for {bpm}")

    def test_the_grid_lands_on_the_hits(self):
        bpm, offset = 120.0, 0.35
        audio = drum_track(bpm, 30.0, offset_s=offset)
        result = beats.analyze_beats(audio, SR)
        period = 60.0 / bpm
        # Each detected beat should sit within 40ms of a true hit.
        errors = []
        for beat in result["beats"][2:-2]:
            nearest = round((beat - offset) / period) * period + offset
            errors.append(abs(beat - nearest))
        self.assertLess(max(errors), 0.04,
                        f"worst grid error {max(errors) * 1000:.0f}ms")

    def test_onsets_fire_on_hits_not_noise(self):
        audio = drum_track(120.0, 20.0)
        result = beats.analyze_beats(audio, SR)
        self.assertGreater(len(result["onsets"]), 20)
        period = 0.5
        strays = [o for o in result["onsets"]
                  if min(o % period, period - (o % period)) > 0.08]
        self.assertLess(len(strays), len(result["onsets"]) * 0.15)

    def test_silence_answers_empty_not_crash(self):
        result = beats.analyze_beats(np.zeros(SR * 5, dtype=np.float32), SR)
        self.assertIsInstance(result["beats"], list)


def hat(sample_rate=SR, length_s=0.03) -> np.ndarray:
    """A hi-hat tick: high-frequency, fast decay — flux, but not punch."""
    t = np.arange(int(length_s * sample_rate)) / sample_rate
    return (np.sin(2 * np.pi * 6000.0 * t)
            * np.exp(-t * 220.0) * 0.5).astype(np.float32)


def stab(sample_rate=SR, length_s=0.15) -> np.ndarray:
    """A broadband stab: kick weight plus a mid-band body, loud."""
    t = np.arange(int(length_s * sample_rate)) / sample_rate
    body = np.sin(2 * np.pi * 800.0 * t) * np.exp(-t * 22.0)
    hit = kick(sample_rate, length_s)
    hit = np.pad(hit, (0, max(0, len(body) - len(hit))))[:len(body)]
    return ((body + 2.0 * hit) * 0.9).astype(np.float32)


class TestHits(unittest.TestCase):
    """detect_hits, graded against audio with a KNOWN accent in it."""

    def _audio(self, stab_t=10.0, seconds=20.0):
        audio = drum_track(120.0, seconds)
        tick = hat()
        t = 0.125
        while t < seconds:  # constant hi-hats: texture, not events
            start = int(t * SR)
            end = min(len(audio), start + len(tick))
            audio[start:end] += tick[:end - start]
            t += 0.25
        burst = stab()
        start = int(stab_t * SR)
        audio[start:start + len(burst)] += burst[:len(audio) - start]
        return audio

    # detect_hits is graded against the TRUE grid, handed in directly —
    # the constant synthetic hi-hats that make this fixture a good ranking
    # test are exactly the pathological input that derails the tempo
    # estimator, and grading the ranker through a tempo lock it is not
    # responsible for would fail the right code for the wrong reason.
    GRID = [round(0.5 * i, 2) for i in range(1, 40)]

    def test_the_stab_outranks_the_hats_and_sits_on_the_beat(self):
        audio = self._audio(stab_t=10.0)
        hits = beats.detect_hits(audio, SR, self.GRID)
        self.assertTrue(hits, "no hits detected at all")
        top = max(hits, key=lambda h: h["strength"])
        self.assertLess(abs(top["t"] - 10.0), 0.08,
                        f"the loudest hit was at {top['t']}, not the stab")
        self.assertEqual(1.0, top["strength"])
        self.assertTrue(top["on_beat"])

    def test_an_off_beat_stab_is_marked_as_such(self):
        # 10.22s is 220ms from the nearest beat of a 120bpm grid — far
        # outside the ±70ms window that means "on the beat".
        audio = self._audio(stab_t=10.22)
        hits = beats.detect_hits(audio, SR, self.GRID)
        near = [h for h in hits if abs(h["t"] - 10.22) < 0.08]
        self.assertTrue(near, "the stab was not detected")
        self.assertFalse(near[0]["on_beat"])

    def test_analysis_carries_the_hits(self):
        result = beats.analyze_beats(drum_track(120.0, 20.0), SR)
        self.assertIn("hits", result)
        self.assertTrue(result["hits"])
        for hit in result["hits"]:
            self.assertIn("on_beat", hit)

    def test_hits_are_sorted_spaced_and_capped(self):
        hits = beats.detect_hits(self._audio(), SR, self.GRID)
        times = [h["t"] for h in hits]
        self.assertEqual(times, sorted(times))
        self.assertLessEqual(len(hits), beats.MAX_HITS)
        gaps = [b - a for a, b in zip(times, times[1:])]
        if gaps:
            self.assertGreaterEqual(min(gaps), beats.HIT_SPACING_S - 1e-6)

    def test_silence_has_no_hits(self):
        result = beats.analyze_beats(np.zeros(SR * 5, dtype=np.float32), SR)
        self.assertEqual([], result.get("hits", []))

    def test_band_flux_separates_punch_from_shimmer(self):
        t = np.arange(SR * 4) / SR
        # Pulsed tones, so there is flux to see in the band it lives in.
        gate = (np.sin(2 * np.pi * 2.0 * t) > 0).astype(np.float32)
        bass = (np.sin(2 * np.pi * 80.0 * t) * gate).astype(np.float32)
        treble = (np.sin(2 * np.pi * 6000.0 * t) * gate).astype(np.float32)
        low_b, mid_b, _ = beats.band_flux(bass, SR)
        low_t, mid_t, _ = beats.band_flux(treble, SR)
        self.assertGreater(low_b.sum(), 5 * low_t.sum())
        self.assertLess(mid_t.sum(), low_b.sum())


class TestFeatures(unittest.TestCase):
    def test_bands_separate(self):
        t = np.arange(SR * 4) / SR
        bass = np.sin(2 * np.pi * 80.0 * t).astype(np.float32)
        treble = np.sin(2 * np.pi * 5000.0 * t).astype(np.float32)
        bass_bands = features.band_energies(bass, SR)
        treble_bands = features.band_energies(treble, SR)
        self.assertGreater(np.mean(bass_bands["low"]),
                           np.mean(bass_bands["high"]) * 5)
        self.assertGreater(np.mean(treble_bands["high"]),
                           np.mean(treble_bands["low"]) * 5)

    def test_energy_is_normalized(self):
        audio = drum_track(120.0, 10.0)
        bands = features.band_energies(audio, SR)
        self.assertLessEqual(max(bands["energy"]), 1.0)

    def test_brightness_orders_dark_and_bright(self):
        t = np.arange(SR * 4) / SR
        dark = np.sin(2 * np.pi * 100.0 * t).astype(np.float32)
        bright = np.sin(2 * np.pi * 3000.0 * t).astype(np.float32)
        self.assertLess(features.brightness_hint(dark, SR),
                        features.brightness_hint(bright, SR))


def synthetic_features(levels: list[tuple[float, float]],
                       hop_s: float = 0.05) -> dict:
    """A features dict with piecewise-constant energy: [(seconds, level)]."""
    energy, low, high = [], [], []
    for seconds, level in levels:
        count = int(seconds / hop_s)
        energy += [level] * count
        low += [level * 0.8] * count
        high += [level * 0.5] * count
    return {"hop_s": hop_s, "energy": energy, "low": low, "high": high,
            "mid": energy}


class TestSections(unittest.TestCase):
    def test_boundary_lands_on_the_energy_step(self):
        levels = [(20.0, 0.2), (20.0, 0.9), (20.0, 0.3)]
        result = sections.find_sections(synthetic_features(levels), 60.0)
        self.assertGreaterEqual(len(result), 3)
        boundaries = [s["start"] for s in result[1:]]
        self.assertTrue(any(abs(b - 20.0) <= 4.0 for b in boundaries),
                        f"no boundary near 20s in {boundaries}")
        self.assertTrue(any(abs(b - 40.0) <= 4.0 for b in boundaries),
                        f"no boundary near 40s in {boundaries}")

    def test_kinds_follow_energy(self):
        levels = [(20.0, 0.15), (20.0, 0.95), (20.0, 0.15)]
        result = sections.find_sections(synthetic_features(levels), 60.0)
        kinds = [s["kind"] for s in result]
        self.assertIn("peak", kinds)
        self.assertEqual("intro", kinds[0])

    def test_a_short_track_is_one_section(self):
        result = sections.find_sections(synthetic_features([(10.0, 0.5)]), 10.0)
        self.assertEqual(1, len(result))

    def test_drop_detection(self):
        levels = [(16.0, 0.25), (16.0, 0.85)]
        drops = sections.find_drops(synthetic_features(levels))
        self.assertEqual(1, len(drops))
        self.assertLess(abs(drops[0]["t"] - 16.0), 2.5)

    def test_steady_music_has_no_drops(self):
        drops = sections.find_drops(synthetic_features([(40.0, 0.6)]))
        self.assertEqual([], drops)


class TestLyrics(unittest.TestCase):
    def test_lrc_parsing(self):
        text = ("[00:12.40]First line\n"
                "[00:15.00][01:15.00]Repeated line\n"
                "[00:20.00]\n"          # empty content — dropped
                "no stamp — dropped\n")
        lines = lyrics.parse_lrc(text)
        self.assertEqual(
            [(12.4, "First line"), (15.0, "Repeated line"),
             (75.0, "Repeated line")],
            [(line["t"], line["text"]) for line in lines])

    def test_fetch_with_fake_server(self):
        import io
        import json as _json

        def opener(request, timeout=None):
            self.assertIn("artist_name=Daft+Punk", request.full_url)
            body = _json.dumps({
                "syncedLyrics": "[00:10.00]One more time",
            }).encode()

            class _Response(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return _Response(body)

        result = lyrics.fetch("Daft Punk", "One More Time",
                              duration_s=320, opener=opener)
        self.assertTrue(result["synced"])
        self.assertEqual(10.0, result["lines"][0]["t"])

    def test_absence_is_an_answer_not_an_error(self):
        def opener(request, timeout=None):
            raise OSError("no network tonight")

        result = lyrics.fetch("Nobody", "Nothing", opener=opener)
        self.assertFalse(result["synced"])
        self.assertEqual([], result["lines"])


class TestLibrary(unittest.TestCase):
    def test_hash_survives_a_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "song.mp3"
            first.write_bytes(b"x" * 4096)
            original = library.track_hash(first)
            renamed = Path(tmp) / "renamed.mp3"
            first.rename(renamed)
            self.assertEqual(original, library.track_hash(renamed))

    def test_scan_finds_audio_and_reports_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            shows = Path(tmp) / "shows"
            self._patch_shows(shows)
            try:
                folder = Path(tmp) / "music"
                (folder / "sub").mkdir(parents=True)
                (folder / "a.mp3").write_bytes(b"a" * 100)
                (folder / "sub" / "b.flac").write_bytes(b"b" * 100)
                (folder / "cover.jpg").write_bytes(b"nope")
                tracks = library.scan(folder)
                self.assertEqual(2, len(tracks))
                self.assertFalse(tracks[0]["analyzed"])
                library.save_analysis(tracks[0]["hash"], {
                    "bpm": 120, "tags": {"duration": 60},
                    "sections": [1, 2], "drops": [],
                    "lyrics": {"synced": True},
                })
                tracks = library.scan(folder)
                analyzed = [t for t in tracks if t["analyzed"]]
                self.assertEqual(1, len(analyzed))
                self.assertEqual(120, analyzed[0]["summary"]["bpm"])
            finally:
                self._unpatch_shows()

    def test_a_bad_hash_never_names_a_path(self):
        for hostile in ("../etc", "zz", "A" * 40):
            with self.subTest(value=hostile):
                with self.assertRaises(ValueError):
                    library.analysis_path(hostile)

    def _patch_shows(self, path):
        self._shows = library.SHOWS_DIR
        library.SHOWS_DIR = path

    def _unpatch_shows(self):
        library.SHOWS_DIR = self._shows


class TestTheLibraryIsNotRereadFromTheDiskUp(unittest.TestCase):
    """A megabyte per file per scan, paid once.

    `track_hash` reads the first megabyte of every track, and the library
    is scanned far more often than the Library tab suggests: the Shows
    tab lists it, the effect builder lists it, the sync proof lists it,
    and the Library tab now lists it on open rather than on a button
    press. On a Pi reading a network share that is why the tab felt like
    it was loading the music every time — the whole file list really was
    being re-read from the disk up on each visit.

    Nothing here is about persistence of the *analysis*, which has always
    lived in /data and always survived a restart. What did not survive
    was the cheapness of finding out.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.music = root / "music"
        self.music.mkdir()
        self._shows, library.SHOWS_DIR = library.SHOWS_DIR, root / "shows"
        self._cache, library.HASH_CACHE = (library.HASH_CACHE,
                                           root / "track-hashes.json")

    def tearDown(self):
        library.SHOWS_DIR = self._shows
        library.HASH_CACHE = self._cache
        self.tmp.cleanup()

    def _track(self, name, payload=b"a"):
        path = self.music / name
        path.write_bytes(payload * 2048)
        return path

    def _reads(self, folders):
        """How many tracks got their first megabyte read this scan."""
        opened = []
        real = library.track_hash

        def counting(path):
            opened.append(str(path))
            return real(path)

        library.track_hash = counting
        try:
            library.scan_all(folders)
        finally:
            library.track_hash = real
        return opened

    def test_a_second_scan_reads_nothing(self):
        self._track("a.mp3")
        self._track("b.mp3", b"b")
        self.assertEqual(2, len(self._reads([self.music])), "cold: both read")
        self.assertEqual([], self._reads([self.music]), "warm: neither")

    def test_an_edited_track_is_read_again(self):
        path = self._track("a.mp3")
        self._reads([self.music])
        path.write_bytes(b"different content entirely" * 100)
        self.assertEqual([str(path)], self._reads([self.music]))

    def test_a_touched_track_is_reread_but_keeps_its_identity(self):
        """mtime is a hint that something changed, not proof — so the file
        is read again, and the hash it produces is the same one, because
        the hash is of the content and the content did not move."""
        path = self._track("a.mp3")
        before = library.scan_all([self.music])[0]["hash"]
        os.utime(path, (0, 0))
        self.assertEqual([str(path)], self._reads([self.music]))
        self.assertEqual(before, library.scan_all([self.music])[0]["hash"])

    def test_a_new_track_beside_known_ones_reads_only_itself(self):
        self._track("a.mp3")
        self._reads([self.music])
        fresh = self._track("b.mp3", b"b")
        self.assertEqual([str(fresh)], self._reads([self.music]))

    def test_a_removed_track_leaves_the_cache(self):
        """Otherwise the file grows to every track that has ever been in
        the library rather than the ones that are."""
        path = self._track("a.mp3")
        self._track("b.mp3", b"b")
        library.scan_all([self.music])
        path.unlink()
        library.scan_all([self.music])
        entries = json.loads(library.HASH_CACHE.read_text())["entries"]
        self.assertEqual(1, len(entries))
        self.assertNotIn(str(path), entries)

    def test_scanning_one_folder_never_prunes(self):
        """`scan` of a single folder cannot know what the others were
        going to claim, so it gets a cache it never saves. Pruning is only
        safe once every folder has been walked."""
        other = Path(self.tmp.name) / "more"
        other.mkdir()
        self._track("a.mp3")
        (other / "b.mp3").write_bytes(b"b" * 2048)
        library.scan_all([self.music, other])
        before = json.loads(library.HASH_CACHE.read_text())["entries"]
        self.assertEqual(2, len(before))
        library.scan(self.music)
        after = json.loads(library.HASH_CACHE.read_text())["entries"]
        self.assertEqual(before, after, "a partial scan must not evict")

    def test_an_unreadable_cache_costs_speed_and_nothing_else(self):
        self._track("a.mp3")
        library.HASH_CACHE.write_text("{{{ not json")
        tracks = library.scan_all([self.music])
        self.assertEqual(1, len(tracks))
        self.assertTrue(tracks[0]["hash"])


if __name__ == "__main__":
    unittest.main()


class TestTheDurationIsMeasuredNotBelieved(unittest.TestCase):
    """The twenty-six-minute four-minute song.

    mutagen's `info.length` is read from the file header, and a VBR file
    without a proper Xing header reports an estimate from the first
    frame's bitrate — wrong by whole multiples. The old pipeline let that
    estimate win over the length of the PCM it had JUST DECODED
    (`tags.setdefault`), and everything downstream schedules against the
    number: the waveform drew 26 minutes, the compiler laid the show out
    over 26 minutes, and the conductor slept out the phantom tail after
    the last cue — parking the party queue for the difference.
    """

    def test_a_new_analysis_carries_the_measured_length(self):
        measured = {"duration_s": 214.3,
                    "tags": {"duration": 1562.0},  # the header's lie
                    "beats": [float(b) for b in range(1, 210)]}
        self.assertEqual(214.3, library.duration_of(measured))

    def test_an_old_analysis_with_a_lying_header_is_healed_by_its_beats(self):
        """Analyses from before `duration_s` cannot be re-measured without
        a decode, but the beat tracker walked the whole file — the last
        beat is near the real end, and a claimed duration far past it is
        the header lying, not a quiet outro."""
        old = {"tags": {"duration": 1562.0},
               "beats": [float(b) for b in range(1, 236)]}  # ends ~235s
        self.assertEqual(240.0, library.duration_of(old))

    def test_a_long_quiet_outro_is_not_mistaken_for_a_lie(self):
        """Sixty seconds of tolerance: a real outro can run well past the
        last beat, and a header error is measured in multiples."""
        old = {"tags": {"duration": 270.0},
               "beats": [float(b) for b in range(1, 236)]}
        self.assertEqual(270.0, library.duration_of(old))

    def test_no_beats_means_the_tag_is_the_only_witness(self):
        self.assertEqual(180.0, library.duration_of(
            {"tags": {"duration": 180.0}, "beats": []}))

    def test_nothing_at_all_is_zero_not_a_crash(self):
        self.assertEqual(0.0, library.duration_of({"tags": {}}))
