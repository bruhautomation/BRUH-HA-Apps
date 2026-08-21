#!/usr/bin/env python3
"""The musical analysis — harmony, melody, phrases, repetition — graded
against audio synthesized here, so every answer is checked against notes
this file chose rather than against the analyzer's own opinion.

And the version check that decides whether any of it ever runs on a
library somebody already scanned. That one is not a nicety: the accent
detection shipped in 0.15.0 and could not reach one existing install,
because `scan` called a track analysed if an analysis file existed at
all. The tests here reproduce that before asserting the fix.
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

from analyzer import library, music  # noqa: E402

SR = 22050


def tone(midi: float, seconds: float, amp: float = 0.3) -> np.ndarray:
    """A note with a real timbre: four harmonics and an envelope. A pure
    sine would let the pitch tracker pass a test no instrument would."""
    freq = 440.0 * 2 ** ((midi - 69) / 12.0)
    t = np.arange(int(seconds * SR)) / SR
    wave = sum(level * np.sin(2 * np.pi * freq * harmonic * t)
               for harmonic, level in zip(range(1, 5), (1, 0.5, 0.3, 0.15)))
    envelope = np.minimum(1.0, np.minimum(t * 60, (seconds - t) * 30))
    return (wave * envelope * amp).astype(np.float32)


def chord(midis, seconds: float, amp: float = 0.25) -> np.ndarray:
    return sum(tone(m, seconds, amp) for m in midis).astype(np.float32)


def progression(chords, seconds: float = 2.0, repeats: int = 2):
    blocks = [chord(notes, seconds) for _ in range(repeats)
              for _, notes in chords]
    return np.concatenate(blocks)


def beat_grid(audio: np.ndarray, beat_s: float = 0.5) -> list[float]:
    return [round(beat_s * i, 3)
            for i in range(1, int(len(audio) / SR / beat_s))]


C_MAJ, A_MIN, F_MAJ, G_MAJ = ([60, 64, 67], [57, 60, 64],
                              [53, 57, 60], [55, 59, 62])
PROGRESSION = [("C", C_MAJ), ("Am", A_MIN), ("F", F_MAJ), ("G", G_MAJ)]


class TestHarmony(unittest.TestCase):
    def setUp(self):
        self.audio = progression(PROGRESSION)
        self.beats = beat_grid(self.audio)
        self.chroma = music.chromagram(music.spectra(self.audio), SR)

    def test_the_chords_come_back_in_order(self):
        heard = [c["name"] for c in
                 music.chords(self.chroma, music.frame_rate(SR), self.beats)]
        self.assertEqual(["C", "Am", "F", "G", "C", "Am", "F", "G"], heard)

    def test_minor_is_told_from_major(self):
        heard = {c["name"]: c["quality"] for c in
                 music.chords(self.chroma, music.frame_rate(SR), self.beats)}
        self.assertEqual("min", heard["Am"])
        self.assertEqual("maj", heard["C"])

    def test_only_changes_are_reported(self):
        """A chord per beat would be forty rows of the same answer — the
        list is what a show acts on, and a show acts on the change."""
        changes = music.chords(self.chroma, music.frame_rate(SR), self.beats)
        self.assertEqual(8, len(changes),
                         "one row per chord, not one per beat")

    def test_the_key_is_the_key(self):
        self.assertEqual("C", music.key_of(self.chroma))

    def test_silence_answers_nothing_rather_than_a_chord(self):
        quiet = np.zeros(SR * 8, dtype=np.float32)
        chroma = music.chromagram(music.spectra(quiet), SR)
        self.assertEqual([], music.chords(chroma, music.frame_rate(SR),
                                          beat_grid(quiet)))
        self.assertIsNone(music.key_of(chroma))


class TestMelody(unittest.TestCase):
    TUNE = [(60, 0.4), (62, 0.4), (64, 0.4), (67, 0.6), (None, 0.8),
            (64, 0.4), (62, 0.4), (60, 0.6)]

    def _audio(self, bass_amp: float = 0.0) -> np.ndarray:
        parts = [tone(m, d) if m else np.zeros(int(d * SR), dtype=np.float32)
                 for m, d in self.TUNE]
        audio = np.concatenate(parts)
        if bass_amp:
            bass = tone(36, len(audio) / SR, amp=bass_amp)[:len(audio)]
            audio = (audio + bass).astype(np.float32)
        return audio

    def test_the_tune_comes_back_as_the_tune(self):
        notes = music.melody_notes(music.spectra(self._audio()), SR)
        self.assertEqual([m for m, _ in self.TUNE if m],
                         [n["m"] for n in notes])

    def test_a_bass_line_is_not_the_melody(self):
        """The tracker follows the loudest MELODIC voice, and a bass an
        octave and a half below it is not that voice however loud it is.
        Without the sub-octave penalty this reported a phantom note for
        the whole of the rest — the bass's second harmonic, sitting in
        the melodic range with nothing to compete with."""
        notes = music.melody_notes(music.spectra(self._audio(0.35)), SR)
        self.assertEqual([m for m, _ in self.TUNE if m],
                         [n["m"] for n in notes])

    def test_a_rest_is_a_rest(self):
        notes = music.melody_notes(music.spectra(self._audio(0.35)), SR)
        during_rest = [n for n in notes if 1.85 <= n["t"] <= 2.4]
        self.assertEqual([], during_rest,
                         f"invented a note in the silence: {during_rest}")

    def test_notes_carry_their_pitch_class_and_strength(self):
        notes = music.melody_notes(music.spectra(self._audio()), SR)
        for note in notes:
            self.assertEqual(note["m"] % 12, note["pc"])
            self.assertGreaterEqual(note["s"], 0.0)
            self.assertLessEqual(note["s"], 1.0)
            self.assertGreaterEqual(note["d"], music.MIN_NOTE_S)

    def test_silence_has_no_melody(self):
        quiet = np.zeros(SR * 4, dtype=np.float32)
        self.assertEqual([], music.melody_notes(music.spectra(quiet), SR))

    def test_phrases_split_on_the_rest_and_read_their_direction(self):
        notes = music.melody_notes(music.spectra(self._audio()), SR)
        # A gap of 0.8s at 150bpm (beat 0.4s) is two beats of silence.
        found = music.phrases(notes, 0.4)
        self.assertEqual(2, len(found), f"expected two phrases, got {found}")
        self.assertEqual("rise", found[0]["dir"])
        self.assertEqual("fall", found[1]["dir"])


class TestRepetition(unittest.TestCase):
    def test_a_repeated_passage_is_found_and_pointed_at_its_original(self):
        audio = progression(PROGRESSION, repeats=2)
        chroma = music.chromagram(music.spectra(audio), SR)
        found = music.repeats(chroma, music.frame_rate(SR), beat_grid(audio))
        self.assertTrue(found, "the second time through was not recognised")
        first = found[0]
        # The second pass through the progression starts at 8s and
        # repeats the one that started at 0.
        self.assertGreater(first["start"], 7.0)
        self.assertLess(first["same_as"], 2.0)

    def test_a_song_that_never_repeats_reports_nothing(self):
        walking = [(f"n{i}", [40 + i, 44 + i, 47 + i]) for i in range(8)]
        audio = progression(walking, seconds=1.0, repeats=1)
        chroma = music.chromagram(music.spectra(audio), SR)
        self.assertEqual([], music.repeats(chroma, music.frame_rate(SR),
                                           beat_grid(audio)))


class TestTheWholeMap(unittest.TestCase):
    def test_analyze_music_answers_every_question_at_once(self):
        audio = progression(PROGRESSION)
        result = music.analyze_music(audio, SR, beat_grid(audio), 0.5)
        for field in ("key", "chords", "notes", "phrases", "repeats"):
            self.assertIn(field, result)
        self.assertTrue(result["chords"])

    def test_audio_too_short_to_analyse_is_empty_not_a_crash(self):
        result = music.analyze_music(np.zeros(1000, dtype=np.float32), SR,
                                     [], 0.5)
        self.assertEqual([], result["chords"])
        self.assertEqual([], result["notes"])


class TestAnAnalysisKnowsHowOldItIs(unittest.TestCase):
    """The version check, reproduced against the failure it exists for.

    0.15.0 added ranked accents and shipped a scan that marked any track
    with an analysis file as analysed. Every library that had been
    scanned once went on serving the old analyzer's output forever, so
    the feature reached nobody who already used the add-on — and from
    the outside that is identical to a feature that does nothing.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._shows = library.SHOWS_DIR
        library.SHOWS_DIR = Path(self.tmp.name) / "shows"
        library.SHOWS_DIR.mkdir(parents=True)

    def tearDown(self):
        library.SHOWS_DIR = self._shows
        self.tmp.cleanup()

    def _write(self, hash_hex: str, version) -> None:
        folder = library.SHOWS_DIR / hash_hex
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "analysis.json").write_text(json.dumps(
            {"version": version, "hash": hash_hex, "bpm": 120,
             "beats": [0.5, 1.0], "tags": {"title": "t", "duration": 10},
             "duration_s": 10}))

    def test_an_analysis_from_an_older_analyzer_is_stale(self):
        self.assertTrue(library.is_stale({"version": 1}))
        self.assertTrue(library.is_stale({"version":
                                          library.ANALYSIS_VERSION - 1}))

    def test_the_current_version_is_not_stale(self):
        self.assertFalse(library.is_stale(
            {"version": library.ANALYSIS_VERSION}))

    def test_an_analysis_with_no_version_at_all_is_stale(self):
        """The oldest files predate the field. Absent is older, never
        newer — the opposite reading leaves the very first analyses as
        the one set that can never be refreshed."""
        self.assertTrue(library.is_stale({"bpm": 120}))

    def test_nothing_analysed_is_not_stale(self):
        """Stale is a claim about an analysis. A track with none is
        `analyzed: false`, which is already the thing that gets it
        analysed — calling it stale as well would double-count it."""
        self.assertFalse(library.is_stale(None))

    def test_a_junk_version_is_stale_rather_than_a_crash(self):
        self.assertTrue(library.is_stale({"version": "two"}))

    def test_scan_reports_stale_without_calling_the_track_unplayable(self):
        """`analyzed` has to stay true for an out-of-date analysis: it
        still has beats and a duration, so the track still plays and the
        party queue is built from exactly this flag. Downgrading it would
        silently drop every already-scanned track out of every party."""
        folder = Path(self.tmp.name) / "music"
        folder.mkdir()
        old = folder / "old.mp3"
        old.write_bytes(b"not really audio, but it hashes")
        self._write(library.track_hash(old), 1)

        rows = library.scan(folder)
        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0]["analyzed"], "a stale track still plays")
        self.assertTrue(rows[0]["stale"])

    def test_a_current_analysis_scans_as_neither(self):
        folder = Path(self.tmp.name) / "music2"
        folder.mkdir()
        fresh = folder / "fresh.mp3"
        fresh.write_bytes(b"also not audio")
        self._write(library.track_hash(fresh), library.ANALYSIS_VERSION)

        rows = library.scan(folder)
        self.assertTrue(rows[0]["analyzed"])
        self.assertFalse(rows[0]["stale"])


if __name__ == "__main__":
    unittest.main()


class TestTheAnalysisCarriesTheMusic(unittest.TestCase):
    """The wiring: an analysis run today has the musical map in it and is
    stamped with the version that says so."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._shows = library.SHOWS_DIR
        library.SHOWS_DIR = Path(self.tmp.name) / "shows"
        library.SHOWS_DIR.mkdir(parents=True)

    def tearDown(self):
        library.SHOWS_DIR = self._shows
        self.tmp.cleanup()

    def test_analyze_track_records_harmony_and_melody(self):
        from unittest import mock

        from analyzer import pipeline

        audio = progression(PROGRESSION)
        track = Path(self.tmp.name) / "song.mp3"
        track.write_bytes(b"stand-in for audio; the decode is mocked")
        with mock.patch.object(pipeline.decode, "pcm", return_value=audio), \
                mock.patch.object(pipeline.decode, "tags",
                                  return_value={"title": "Song",
                                                "artist": "", "album": "",
                                                "duration": None}), \
                mock.patch.object(pipeline.lyrics, "fetch",
                                  return_value={}):
            analysis = pipeline.analyze_track(track)

        self.assertEqual(library.ANALYSIS_VERSION, analysis["version"])
        self.assertIn("music", analysis)
        self.assertTrue(analysis["music"]["chords"],
                        "a chord progression analysed to no chords")
        self.assertIn("key", analysis["music"])
        # And it is what `is_stale` will read back off the disk.
        self.assertFalse(library.is_stale(
            library.load_analysis(analysis["hash"])))


class TestSilenceFromAMusicEffectSaysWhy(unittest.TestCase):
    """A `melody` on a track with no melody renders nothing, which is
    correct and looks exactly like a broken effect. The compiler puts the
    reason on that effect's own row."""

    def _breakdown(self, analysis: dict) -> list[dict]:
        from director import compiler

        from test_bright_director import FIXTURES

        script = {
            "version": 2,
            "scenes": [{"start": 0.0, "end": 30.0, "mood": "warm",
                        "palette": [[30.0, 0.6]], "brightness": 0.5,
                        "effects": [{"type": "melody", "name": "tune"}]}],
            "moments": [],
        }
        rows = compiler.script_actions(script, FIXTURES, analysis)["effects"]
        # By type, never by index: a scene compiles its own base wash
        # first, so row zero is the scene's ground and not the effect
        # this test is about.
        return [r for r in rows if r["type"] == "melody"]

    def test_a_stale_track_gets_a_reason_next_to_the_empty_effect(self):
        from test_bright_director import analysis_fixture

        rows = self._breakdown(analysis_fixture())          # no "music" key
        self.assertEqual(0, rows[0]["actions"])
        self.assertIn("re-run Analyze", rows[0]["note"])

    def test_a_track_with_music_needs_no_excuse(self):
        from test_bright_director import analysis_fixture

        analysis = analysis_fixture()
        analysis["music"] = {
            "notes": [{"t": 1.0 + i, "d": 0.4, "m": 60 + i, "pc": (60 + i) % 12,
                       "s": 0.9} for i in range(8)],
            "chords": [], "phrases": [], "repeats": [], "key": "C",
        }
        rows = self._breakdown(analysis)
        self.assertGreater(rows[0]["actions"], 0)
        self.assertNotIn("note", rows[0])
