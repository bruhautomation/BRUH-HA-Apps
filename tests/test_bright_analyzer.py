#!/usr/bin/env python3
"""BRight's analyzer, measured against synthesized ground truth.

Every rhythmic test builds its own audio — a kick pattern at a KNOWN tempo,
an energy arc with KNOWN section boundaries — so the analyzer is graded
against answers it did not produce. No fixtures, no golden files, no ffmpeg
(the decode boundary is the one thing mocked).
"""

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


if __name__ == "__main__":
    unittest.main()
