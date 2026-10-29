"""Print failure detection, one printer at a time.

Every printer with detection on gets a thread of its own that takes a frame
every few seconds while it prints (and every minute or so after it
finishes, until the plate is cleared) and does the free things with it:
is the lens covered or the chamber dark, did the plate change suddenly, is
the feed frozen, does the finished plate look empty again. Those decide
nothing about a failure. What decides is a LOOK — one brAIn run with the
pictures — and looks are spent where prints fail:

* the checkpoints `plan` read out of this print's own G-code (the first
  layer, a few millimetres up, a sharp narrowing, bridges and overhangs, a
  colour change, a part getting tall and thin, the last layers, and one
  look in any long stretch with nothing else);
* a sudden change to the plate the free looks noticed;
* the printer's own camera raising an HMS message (module 0C00);
* a look again soon after anything doubtful (`watch` or `warning`), which
  is how a lifting corner becomes either nothing or a pause;
* a press of Check now.

A per-print budget and a minimum gap keep it from asking brAIn about every
frame, and brAIn's own pause and usage budget apply to every look nobody
pressed for.

What a look finds is `judge.decide`'s: `failure` pauses the printer and
says so, `warning` tells somebody and offers Ignore and Pause, `watch` looks
again soon and tells nobody. A lens that is covered or a chamber that is
dark stands every look down — there is nothing to judge — and says which.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.parse
from pathlib import Path

import bambu_atomic
import library
import prefs
import store
import thumbs
from bambu import ftps, protocol
from design import brain_link

from . import judge, plan, vision

log = logging.getLogger("bruh_bambu.watch")

DATA = Path(os.environ.get("BAMBU_DATA", "/data")) / "watch"
SETTINGS_FILE = Path(os.environ.get("BAMBU_DATA", "/data")) / "watch_settings.json"
SHARED = Path(os.environ.get("BAMBU_SHARED", "/config/.bruh_bambu"))

STEP_S = 2
SAMPLE_PRINTING_S = 10
SAMPLE_PLATE_S = 45
PLATE_WATCH_S = 12 * 3600
FRAME_WAIT_S = 8
# Consecutive frames before the view is called covered or dark, so one bad
# frame (a JPEG the camera garbled) never stands detection down.
BLIND_AFTER = 2
FROZEN_AFTER = 6
# Between two looks nobody pressed for; a trigger may cut it to the short one.
MIN_LOOK_GAP_S = 240
URGENT_LOOK_GAP_S = 75
FOLLOW_UP_S = 180
MAX_FOLLOW_UPS = 3
PLATE_LOOK_GAP_S = 20 * 60
# A look is taken from a burst, not the one frame that happened to be newest:
# the bed of an A1 slides front to back and every bed drops at each layer, so
# a single frame is often a smear. The steadiest of the burst (the most edge,
# vision.sharpest) is the one brAIn is shown.
BURST_FRAMES = 4
BURST_GAP_S = 1.2
# Lifted no faster than this after a pause, or an AI look already in flight
# about the moment before the pause would raise the same alert again.
KEEP_CHECKS = 60
ACTIVE = {"prepare", "running", "pause", "slicing"}
# The printer's own camera (xcam) reports under HMS module 0C00.
XCAM_HMS = "0C00"
# The printer paused itself over these (protocol.STAGES): a failure it found.
PRINTER_FAILURE_STAGES = ("first layer fault", "nozzle clog", "filament over the nozzle",
                          "skipped step")
SENSITIVITIES = ("low", "medium", "high")
MODES = ("pause", "warn")
DEFAULTS = {"enabled": False, "mode": "pause", "sensitivity": "medium", "light": True,
            "plate": True}
NAME = re.compile(r"^(?P<print>[0-9a-f]{4,16})/(?P<file>\d{1,4}\.jpg|expected\.png)$")

STATUS_WORDS = {
    "off": "Print failure detection is off.",
    "idle": "Watching for the next print.",
    "watching": "Watching the print.",
    "basic": "Watching without brAIn: covered lens, sudden changes and the printer's own alerts only.",
    "looking": "brAIn is looking at the print.",
    "warning": "Something may be wrong with the print.",
    "failure": "The print failed and was paused.",
    "covered": "The camera lens is covered, so nothing is being checked.",
    "dark": "The chamber is too dark to see the print, so nothing is being checked.",
    "frozen": "The camera picture has stopped changing, so nothing is being checked.",
    "no_camera": "The camera is not sending pictures, so nothing is being checked.",
}


def load_settings() -> dict:
    data = bambu_atomic.read_json(SETTINGS_FILE, {})
    return data if isinstance(data, dict) else {}


def clean_settings(current: dict, changes: dict) -> dict:
    out = {**DEFAULTS, **(current or {})}
    for key in ("enabled", "light", "plate"):
        if key in changes:
            out[key] = bool(changes[key])
    if "mode" in changes:
        if changes["mode"] not in MODES:
            raise ValueError("Mode is pause (warn, and pause a failed print) or warn (only warn).")
        out["mode"] = changes["mode"]
    if "sensitivity" in changes:
        if changes["sensitivity"] not in SENSITIVITIES:
            raise ValueError("Sensitivity is low, medium or high.")
        out["sensitivity"] = changes["sensitivity"]
    return out


def clean_notify(target) -> str:
    text = str(target or "").strip()
    if text and not re.fullmatch(r"notify\.[a-z0-9_]{1,80}", text):
        raise ValueError("A notification target is a notify service, such as notify.mobile_app_pixel.")
    return text


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


class PrinterWatch:
    """The state of one printer's detection: the print, its plan, its looks."""

    def __init__(self, owner: "Watcher", pid: str):
        self.owner, self.pid = owner, pid
        self.dir = owner.data / pid
        self.lock = threading.RLock()
        self.record: dict | None = bambu_atomic.read_json(self.dir / "print.json", None)
        self.previous: dict | None = bambu_atomic.read_json(self.dir / "last.json", None)
        self.tracker = vision.ChangeTracker()
        self.facts: dict | None = None
        self.view = "unknown"
        self.view_since = 0.0
        self._blind_run = 0
        self.frozen = False
        self.camera_error = ""
        self.last_state: str | None = None
        self.last_sample = 0.0
        self.last_grid: vision.Grid | None = None
        self.last_frame: bytes | None = None
        self.empty_candidate: tuple[vision.Grid, bytes] | None = None
        self.empty_ref = self._load_empty()
        self.finished_grid: vision.Grid | None = None
        self.plate = bambu_atomic.read_json(self.dir / "plate.json", None) or {
            "state": "unknown", "since": None, "why": ""}
        self._clear_votes = 0
        self.last_plate_look = 0.0
        self.looking = False
        self.triggers: list[dict] = []
        self.hms_seen: set[str] = set()
        self.brain = {"state": "unknown", "sentence": ""}
        self.reading_plan = False

    # -- persistence -------------------------------------------------------
    def _save(self) -> None:
        if self.record is None:
            return
        try:
            bambu_atomic.write_json(self.dir / "print.json", self.record)
        except OSError as exc:
            log.warning("Could not save the print record for %s: %s", self.pid, exc)

    def _save_plate(self) -> None:
        try:
            bambu_atomic.write_json(self.dir / "plate.json", self.plate)
        except OSError:
            pass  # the plate's state is kept in memory; the file only survives a restart

    def _load_empty(self) -> vision.Grid | None:
        try:
            raw = (self.dir / "empty.gray").read_bytes()
            return vision.Grid(raw)
        except (OSError, ValueError):
            return None

    def _store_empty(self, grid: vision.Grid, jpeg: bytes) -> None:
        self.empty_ref = grid
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            bambu_atomic.write_bytes(self.dir / "empty.gray", grid.px)
            bambu_atomic.write_bytes(self.dir / "empty.jpg", jpeg)
        except OSError:
            pass  # the reference is kept in memory for this run; the file is for the next

    # -- the print ---------------------------------------------------------
    def _new_print(self, summary: dict, now: float) -> None:
        if self.record:
            try:
                bambu_atomic.write_json(self.dir / "last.json", self.record)
            except OSError:
                pass  # the previous print's record is history, not needed to watch this one
            self.previous = self.record
            self._prune(keep={self.record.get("id")})
        settings = self.owner.settings_for(self.pid)
        self.record = {
            "id": f"{int(now):x}", "file": summary.get("file") or "",
            "gcode_file": summary.get("gcode_file") or "", "started_at": now,
            "plan": None, "plan_note": "Reading the print's file…", "checks": [],
            "alert": None, "alerts": [], "ignored": [], "no_pause": [],
            "looks": 0, "follow_ups": 0, "light_on": False, "finished_at": None,
            "sensitivity": settings["sensitivity"], "result": None,
        }
        self.facts = None
        self.tracker.reset()
        self.hms_seen = set(summary.get("hms") or [])
        self.triggers = []
        self.finished_grid = None
        self.plate = {"state": "printing", "since": now, "why": "A print is on the plate."}
        self._save_plate()
        self._save()
        self._start_plan_reading(summary)

    def _prune(self, keep: set) -> None:
        try:
            for child in self.dir.iterdir():
                if child.is_dir() and child.name not in keep:
                    for f in child.iterdir():
                        f.unlink(missing_ok=True)
                    child.rmdir()
        except OSError:
            pass  # old pictures left behind cost disk, never a wrong verdict

    def _print_dir(self) -> Path:
        return self.dir / self.record["id"]

    def _start_plan_reading(self, summary: dict) -> None:
        if self.reading_plan:
            return
        self.reading_plan = True
        record_id = self.record["id"]
        threading.Thread(target=self._read_plan, args=(summary, record_id), daemon=True,
                         name=f"watch-plan-{self.pid}").start()

    def _read_plan(self, summary: dict, record_id: str) -> None:
        facts, note, expected = None, "", None
        try:
            facts, expected, note = self.owner.read_print(self.pid, summary)
        except Exception as exc:  # noqa: BLE001 - a plan that cannot be read falls back, never stops
            note = f"Could not read the print's file ({exc}); looks are spread by layer instead."
            log.info("%s: %s", self.pid, note)
        finally:
            self.reading_plan = False
        with self.lock:
            if not self.record or self.record["id"] != record_id:
                return
            self.facts = facts
            if expected:
                try:
                    self._print_dir().mkdir(parents=True, exist_ok=True)
                    bambu_atomic.write_bytes(self._print_dir() / "expected.png", expected)
                    self.record["expected"] = True
                except OSError:
                    pass  # without the picture the look goes on with the camera alone
            self._plan(summary.get("total_layers"), note)
            self._save()

    def _plan(self, total_layers, note: str = "") -> None:
        sensitivity = self.owner.settings_for(self.pid)["sensitivity"]
        old = {c["layer"]: c for c in ((self.record.get("plan") or {}).get("checkpoints") or [])}
        if self.facts and self.facts.get("layers"):
            built = plan.from_gcode(self.facts, sensitivity)
            note = note or (f"Planned from the print's G-code: {len(built['checkpoints'])} looks " +
                            "at the moments most likely to fail.")
        else:
            built = plan.estimated(total_layers, sensitivity)
            note = note or ("The print's file could not be read, so looks are spread by layer.")
        for point in built["checkpoints"]:
            was = old.get(point["layer"])
            if was and was.get("state"):
                point["state"], point["decision"] = was["state"], was.get("decision")
            else:
                point["state"] = "planned"
        self.record["plan"] = built
        self.record["plan_note"] = note
        self.record["sensitivity"] = sensitivity

    def replan(self) -> None:
        with self.lock:
            if self.record and self.record.get("plan") and not self.record.get("finished_at"):
                self._plan(self.record["plan"].get("total_layers"), "")
                self._save()

    # -- one step ----------------------------------------------------------
    def step(self, now: float | None = None) -> None:
        now = self.owner.clock() if now is None else now
        settings = self.owner.settings_for(self.pid)
        if not settings["enabled"]:
            self.last_state = None
            if settings["plate"]:
                self._plate_only_step(settings, now)
            return
        summary = self.owner.summary_of(self.pid)
        if summary is None or not summary.get("online"):
            return
        state = summary.get("state")
        with self.lock:
            self._transitions(summary, state, now)
            self._printer_signals(summary, now)
            self.last_state = state
        active = state in ACTIVE
        watching_plate = (settings["plate"] and state in ("finish", "failed")
                          and self.plate["state"] not in ("clear",)
                          and self.record and self.record.get("finished_at")
                          and now - self.record["finished_at"] < PLATE_WATCH_S)
        if not active and not watching_plate:
            return
        every = SAMPLE_PRINTING_S if active else SAMPLE_PLATE_S
        if now - self.last_sample >= every:
            self.last_sample = now
            self._sample(summary, settings, now)
        if state == "running":
            self._maybe_look(summary, settings, now)

    def _plate_only_step(self, settings: dict, now: float) -> None:
        """Detection off, the plate watch on: nothing is looked at while a
        print runs. Once one finishes, a frame a minute or so says when the
        plate has been cleared, so the panel stops showing a finished print
        nobody is printing any more."""
        summary = self.owner.summary_of(self.pid)
        if summary is None or not summary.get("online"):
            return
        state = summary.get("state")
        with self.lock:
            if state in ACTIVE and self.plate["state"] != "printing":
                self.plate = {"state": "printing", "since": now, "why": "A print is on the plate."}
                self.finished_grid = None
                self._clear_votes = 0
                self._save_plate()
            elif state in ("finish", "failed") and self.plate["state"] in ("printing", "unknown"):
                self.plate = {"state": "occupied", "since": now, "why": (
                    "The finished print is on the plate." if state == "finish"
                    else "A failed print is on the plate.")}
                self._clear_votes = 0
                self._save_plate()
                self.owner.changed()
        if state not in ("finish", "failed") or self.plate["state"] != "occupied":
            return
        if now - (self.plate.get("since") or now) > PLATE_WATCH_S:
            return
        if now - self.last_sample < SAMPLE_PLATE_S:
            return
        self.last_sample = now
        jpeg, _error = self.owner.frame(self.pid)
        grid = self.owner.decode(jpeg) if jpeg else None
        if grid is None or vision.view(grid, summary.get("chamber_light")) != "ok":
            return
        with self.lock:
            self.last_grid, self.last_frame = grid, jpeg
            self.brain = self.owner.brain_status()
            self._plate_step(grid, jpeg, now)

    def _transitions(self, summary: dict, state, now: float) -> None:
        was = self.last_state
        rec = self.record
        file_changed = rec and summary.get("file") and summary.get("file") != rec.get("file") \
            and state in ACTIVE
        if state in ACTIVE and (rec is None or rec.get("finished_at") is not None
                                or was in ("idle", "finish", "failed") or file_changed):
            if rec is None or rec.get("finished_at") is not None or file_changed or was is not None:
                self._new_print(summary, now)
        rec = self.record
        if rec is None:
            return
        if rec.get("plan") is None and not self.reading_plan and state in ACTIVE:
            self._start_plan_reading(summary)
        plan_ = rec.get("plan") or {}
        if plan_.get("source") == "estimate" and not plan_.get("total_layers") \
                and summary.get("total_layers"):
            self._plan(summary["total_layers"], rec.get("plan_note") or "")
            self._save()
        if state in ("finish", "failed") and rec.get("finished_at") is None:
            rec["finished_at"] = now
            rec["result"] = state
            alert = rec.get("alert")
            if alert and alert.get("open") and state == "finish" and alert["level"] == "warning":
                self._close_alert("The print finished.", answer="finished")
            if state == "finish":
                self.plate = {"state": "occupied", "since": now,
                              "why": "The finished print is on the plate."}
                self._clear_votes = 0
                self.triggers.append({"kind": "finish", "why": "The print finished: one last look " +
                                      "to see that it looks like the picture.", "at": now})
            else:
                self.plate = {"state": "occupied", "since": now, "why": "A failed print is on the plate."}
            self._save_plate()
            self._save()
        if state == "running" and self.empty_candidate and summary.get("layer"):
            grid, jpeg = self.empty_candidate
            self.empty_candidate = None
            self._store_empty(grid, jpeg)

    def _printer_signals(self, summary: dict, now: float) -> None:
        rec = self.record
        if rec is None or summary.get("state") not in ACTIVE:
            return
        codes = set(summary.get("hms") or [])
        for code in sorted(codes - self.hms_seen):
            if code.startswith(XCAM_HMS):
                why = (f"The printer's own camera raised a message ({code}).")
                self.triggers.append({"kind": "printer_camera", "why": why, "at": now,
                                      "urgent": True, "code": code})
                if self.brain["state"] != "ok":
                    self._open_alert("warning", "other",
                                     "The printer's own camera reported a possible problem " +
                                     f"({code}).", now, image=None, source="printer")
        self.hms_seen = codes
        stage = (summary.get("stage") or "").lower()
        if summary.get("state") == "pause" and any(word in stage for word in PRINTER_FAILURE_STAGES):
            alert = rec.get("alert")
            if not (alert and alert.get("open") and alert.get("source") == "printer_pause"):
                self._open_alert("failure", "other", "The printer paused the print itself: " +
                                 f"{summary.get('stage')}.", now, image=None,
                                 source="printer_pause", paused=True)

    # -- frames ------------------------------------------------------------
    def _sample(self, summary: dict, settings: dict, now: float) -> None:
        jpeg, error = self.owner.frame(self.pid)
        if jpeg is None:
            self.camera_error = error or "The camera is not sending pictures."
            self.view = "no_camera"
            return
        self.camera_error = ""
        grid = self.owner.decode(jpeg)
        if grid is None:
            return
        seen = vision.view(grid, summary.get("chamber_light"))
        with self.lock:
            if seen == "ok":
                self._blind_run = 0
                if self.view != "ok":
                    self.view, self.view_since = "ok", now
            else:
                self._blind_run += 1
                if self._blind_run >= BLIND_AFTER and self.view != seen:
                    self.view, self.view_since = seen, now
            self.last_grid, self.last_frame = grid, jpeg
            state = summary.get("state")
            rec = self.record
            if (seen == "dark" and settings["light"] and rec and not rec.get("light_on")
                    and state in ACTIVE and summary.get("chamber_light") is False):
                rec["light_on"] = True
                self._save()
                self.owner.command(self.pid, protocol.light(True))
            if seen != "ok":
                return
            if state == "prepare" and not summary.get("layer"):
                self.empty_candidate = (grid, jpeg)
            if state == "running":
                change = self.tracker.add(grid)
                self.frozen = change["frozen"] >= FROZEN_AFTER
                if change["spike"]:
                    self.triggers.append({"kind": "change", "why": "The plate changed suddenly " +
                                          "between two frames.", "at": now, "urgent": True})
            if state in ("finish", "failed"):
                self._plate_step(grid, jpeg, now)

    def _plate_step(self, grid: vision.Grid, jpeg: bytes, now: float) -> None:
        if self.plate["state"] == "clear":
            return
        if self.finished_grid is None:
            self.finished_grid = grid
            return
        if self.empty_ref is not None:
            if vision.looks_like(grid, self.empty_ref):
                self._clear_votes += 1
                if self._clear_votes >= 2:
                    self._plate_clear(now, "The plate looks the way it did before the print.",
                                      learn=False)
            else:
                self._clear_votes = 0
            return
        moved = vision.difference(grid, self.finished_grid)
        if moved["changed"] > 0.12 and now - self.last_plate_look > PLATE_LOOK_GAP_S \
                and self.brain["state"] == "ok" and not self.looking:
            self.last_plate_look = now
            self.finished_grid = grid
            self._launch({"kind": "plate", "why": "The plate changed after the print finished.",
                          "at": now}, None, plate_only=True)

    def _plate_clear(self, now: float, why: str, *, learn: bool = True) -> None:
        self.plate = {"state": "clear", "since": now, "why": why}
        self._save_plate()
        # The plate as it is now is what an empty plate looks like: the next
        # finished print is compared with it for free, without brAIn.
        if learn and self.last_grid is not None and self.last_frame is not None \
                and vision.view(self.last_grid, None) == "ok":
            self._store_empty(self.last_grid, self.last_frame)
        self.owner.changed()

    def _learn_empty(self) -> None:
        """A fresh frame of the plate somebody just said is clear, kept as the
        empty plate (the frame before they said it may still show the print)."""
        try:
            jpeg, _error = self.owner.frame(self.pid)
            grid = self.owner.decode(jpeg) if jpeg else None
            if grid is None or vision.view(grid, None) != "ok":
                return
            with self.lock:
                if self.plate["state"] == "clear":
                    self._store_empty(grid, jpeg)
        except Exception:  # noqa: BLE001 - a reference not learnt is asked for again next time
            log.info("Could not keep the empty plate for %s", self.pid, exc_info=True)

    # -- looks -------------------------------------------------------------
    def _budget(self) -> int:
        return plan.BUDGETS.get(self.owner.settings_for(self.pid)["sensitivity"], 8)

    def _maybe_look(self, summary: dict, settings: dict, now: float) -> None:
        rec = self.record
        # The newest frame has to be a picture too: the view waits for two
        # bad frames before it says covered, and a look must not spend
        # itself on the first.
        if rec is None or self.looking or self.view != "ok" or self.frozen or self._blind_run:
            return
        self.brain = self.owner.brain_status()
        if self.brain["state"] != "ok":
            return
        last = max([c["at"] for c in rec["checks"]] or [0])
        layer = summary.get("layer") or 0
        trigger = None
        manual = [t for t in self.triggers if t["kind"] == "manual"]
        if manual:
            trigger = manual[0]
        else:
            urgent = [t for t in self.triggers if t.get("urgent")]
            due_follow = [t for t in self.triggers if t["kind"] == "follow_up" and t["at"] <= now]
            point = self._due_checkpoint(layer)
            used = rec["looks"]
            budget = self._budget()
            if urgent and now - last >= URGENT_LOOK_GAP_S and used < budget + plan.TRIGGER_EXTRA:
                trigger = urgent[0]
            elif due_follow and now - last >= URGENT_LOOK_GAP_S and used < budget + plan.TRIGGER_EXTRA:
                trigger = due_follow[0]
            elif point and now - last >= MIN_LOOK_GAP_S and used < budget + 1:
                why = point["reason"] + "".join(f" Also: {a}" for a in point.get("also") or [])
                trigger = {"kind": "checkpoint", "why": why, "at": now,
                           "layer": point["layer"], "checkpoint": point["kind"]}
        if trigger is None:
            return
        if trigger in self.triggers:
            self.triggers.remove(trigger)
        if trigger["kind"] in ("change", "printer_camera"):
            self.triggers = [t for t in self.triggers if t["kind"] not in ("change", "printer_camera")]
        self._launch(trigger, summary)

    def _due_checkpoint(self, layer: int) -> dict | None:
        points = ((self.record.get("plan") or {}).get("checkpoints")) or []
        due = [p for p in points if p.get("state") == "planned" and p["layer"] <= layer]
        if not due:
            return None
        for p in due[:-1]:
            p["state"] = "missed"
        return due[-1]

    def finish_look_due(self, now: float) -> None:
        """The look at a finished print, which happens off the running state."""
        with self.lock:
            rec = self.record
            pending = [t for t in self.triggers if t["kind"] == "finish"]
            if not pending or self.looking or self.view != "ok" or rec is None:
                return
            self.brain = self.owner.brain_status()
            if self.brain["state"] != "ok":
                self.triggers.remove(pending[0])
                return
            self.triggers.remove(pending[0])
            summary = self.owner.summary_of(self.pid) or {}
            self._launch(pending[0], summary)

    def _launch(self, trigger: dict, summary: dict | None, plate_only: bool = False) -> None:
        frame = self.last_frame
        if frame is None:
            return
        self.looking = True
        if trigger["kind"] not in ("manual", "plate"):
            self.record["looks"] += 1
        if trigger["kind"] == "checkpoint":
            for p in (self.record.get("plan") or {}).get("checkpoints") or []:
                if p["layer"] == trigger.get("layer") and p.get("state") == "planned":
                    p["state"] = "looking"
        self._save()
        threading.Thread(target=self._look, args=(trigger, dict(summary or {}), frame, plate_only),
                         daemon=True, name=f"watch-look-{self.pid}").start()

    def _steadiest(self, first: bytes) -> bytes:
        """The steadiest frame of a short burst, the one the look started with included."""
        frames = [first]
        for _ in range(BURST_FRAMES - 1):
            self.owner.sleep(BURST_GAP_S)
            jpeg, _error = self.owner.frame(self.pid)
            if jpeg and jpeg not in frames:
                frames.append(jpeg)
        if len(frames) == 1:
            return first
        grids, kept = [], []
        for jpeg in frames:
            grid = self.owner.decode(jpeg)
            if grid is not None and vision.view(grid, None) == "ok":
                grids.append(grid)
                kept.append(jpeg)
        if not grids:
            return first
        return kept[vision.sharpest(grids)]

    def _context(self, trigger: dict, summary: dict, row: dict) -> tuple[dict, list[bytes], dict]:
        rec = self.record
        ctx = {"printer": row.get("name"), "model": row.get("model"), "file": rec.get("file"),
               "layer": summary.get("layer"), "total_layers": summary.get("total_layers"),
               "progress": summary.get("progress"), "stage": summary.get("stage"),
               "why": trigger.get("why")}
        facts = self.facts or {}
        layers = facts.get("layers") or []
        layer = summary.get("layer") or 0
        if layers and 0 < layer <= len(layers):
            ctx["z_mm"] = layers[layer - 1].get("z")
            ctx["height_mm"] = facts.get("height")
        trays = [t for t in (summary.get("ams") or []) if isinstance(t, dict)]
        active = summary.get("active_tray")
        tray = next((t for t in trays if t.get("slot") == active), None) or (
            summary.get("external_spool") if active == "external" else None)
        if tray:
            ctx["filaments"] = " ".join(x for x in (tray.get("colour"), tray.get("type"),
                                                     tray.get("name")) if x) + " (feeding now)"
        images = []
        expected_path = self._print_dir() / "expected.png"
        earlier = next((c for c in reversed(rec["checks"]) if c.get("image")
                        and c.get("decision") in ("ok", "watch", "ignored")), None)
        extra = {"expected": False, "earlier": None}
        if expected_path.is_file():
            try:
                images.append(expected_path.read_bytes())
                ctx["expected"] = True
                extra["expected"] = True
            except OSError:
                pass  # the look goes on without the picture of the plate
        if earlier:
            try:
                images.append((self._print_dir() / earlier["image"]).read_bytes())
                ctx["earlier"] = True
                ctx["earlier_layer"] = earlier.get("layer")
                ctx["earlier_ago"] = _ago(self.owner.clock() - earlier["at"])
                extra["earlier"] = earlier["n"]
            except OSError:
                pass  # the look goes on without the earlier frame
        past = [f"layer {c.get('layer')}: {c['decision']} ({c['summary']})"
                for c in rec["checks"][-3:] if c.get("summary")]
        if past:
            ctx["history"] = "; ".join(past)
        if rec.get("ignored"):
            ctx["ignored"] = ", ".join(judge.PROBLEM_WORDS.get(p, p) for p in rec["ignored"])
        return ctx, images, extra

    def _look(self, trigger: dict, summary: dict, frame: bytes, plate_only: bool) -> None:
        try:
            row = self.owner.row(self.pid) or {}
            if not plate_only:
                frame = self._steadiest(frame)
            with self.lock:
                if self.record is None and not plate_only:
                    return
                if plate_only:
                    ctx, extra_images, extra = {"file": (self.record or {}).get("file")}, [], {}
                    question = judge.plate_prompt(ctx)
                else:
                    ctx, extra_images, extra = self._context(trigger, summary, row)
                    question = judge.prompt(ctx)
            answer, error = self.owner.ask(question, [frame, *extra_images],
                                           scheduled=trigger["kind"] != "manual")
            with self.lock:
                pause_alert = self._record_look(trigger, summary, frame, answer, error,
                                                plate_only, extra)
            if pause_alert:
                # Outside the lock, for act()'s reason.
                paused, why = self.owner.pause(self.pid)
                with self.lock:
                    alert = (self.record or {}).get("alert")
                    if alert and alert.get("id") == pause_alert:
                        alert.update(paused=paused, pause_error=why, pausing=False)
                        self._save()
        except Exception:  # noqa: BLE001 - a look that broke must not end detection
            log.exception("A print look for %s failed", self.pid)
        finally:
            self.looking = False
            self.owner.changed()

    def _record_look(self, trigger: dict, summary: dict, frame: bytes, answer: dict | None,
                     error: str, plate_only: bool, extra: dict) -> str | None:
        """Write one look down; the alert's id when the printer is to be paused."""
        rec = self.record
        now = self.owner.clock()
        if plate_only:
            if answer is None:
                self.brain = {"state": "error", "sentence": error or "brAIn did not answer."}
                return None
            if answer["plate"] == "empty" and answer["confidence"] >= 0.7:
                self._plate_clear(now, f"brAIn looked: {answer['summary']}")
            elif answer["plate"] == "has_print":
                self.plate = {"state": "occupied", "since": self.plate.get("since") or now,
                              "why": answer["summary"]}
                self._save_plate()
            return None
        if rec is None:
            return None
        if answer is None:
            self.brain = {"state": "error", "sentence": error or "brAIn did not answer."}
            if trigger["kind"] == "checkpoint":
                for p in (rec.get("plan") or {}).get("checkpoints") or []:
                    if p["layer"] == trigger.get("layer") and p.get("state") == "looking":
                        p["state"] = "skipped"
                        p["decision"] = "no answer"
            if trigger["kind"] not in ("manual", "plate"):
                rec["looks"] = max(0, rec["looks"] - 1)
            rec.setdefault("errors", []).append({"at": now, "error": error[:300]})
            rec["errors"] = rec["errors"][-10:]
            self._save()
            return None
        self.brain = {"state": "ok", "sentence": "brAIn is looking at the print."}
        settings = self.owner.settings_for(self.pid)
        decision = judge.decide(answer, sensitivity=settings["sensitivity"], mode=settings["mode"],
                                ignored=rec["ignored"], no_pause=rec["no_pause"])
        if trigger["kind"] == "finish" and decision == "failure":
            decision = "warning"  # nothing left to pause
        n = (rec["checks"][-1]["n"] + 1) if rec["checks"] else 1
        name = f"{n}.jpg"
        try:
            self._print_dir().mkdir(parents=True, exist_ok=True)
            bambu_atomic.write_bytes(self._print_dir() / name, frame)
            self.owner.mirror_check(self.pid, frame)
        except OSError:
            name = None
        check = {"n": n, "at": now, "layer": summary.get("layer"),
                 "progress": summary.get("progress"), "trigger": trigger["kind"],
                 "why": trigger.get("why"), "image": name, "decision": decision,
                 "compared_with": extra.get("earlier"), "expected": bool(extra.get("expected")),
                 **{k: answer.get(k) for k in ("verdict", "confidence", "problem", "summary", "where")}}
        rec["checks"].append(check)
        rec["checks"] = rec["checks"][-KEEP_CHECKS:]
        if trigger["kind"] == "checkpoint":
            for p in (rec.get("plan") or {}).get("checkpoints") or []:
                if p["layer"] == trigger.get("layer"):
                    p["state"], p["decision"] = "done", decision
        if answer.get("plate") == "empty" and summary.get("state") == "running" \
                and (summary.get("layer") or 0) > 3 and decision in ("warning", "failure"):
            check["note"] = "brAIn saw an empty plate mid-print."
        alert = rec.get("alert")
        if decision == "ok":
            if alert and alert.get("open") and alert["level"] == "warning" \
                    and answer["confidence"] >= 0.6:
                self._close_alert("brAIn looked again and the print looks fine.", answer="cleared")
        elif decision in ("watch", "warning"):
            if rec["follow_ups"] < MAX_FOLLOW_UPS:
                rec["follow_ups"] += 1
                self.triggers.append({"kind": "follow_up", "at": now + FOLLOW_UP_S,
                                      "why": f"A second look after: {answer['summary']}"})
            if decision == "warning":
                self._open_alert("warning", answer["problem"], answer["summary"], now,
                                 image=name, check=n, confidence=answer["confidence"])
        elif decision == "failure":
            self._open_alert("failure", answer["problem"], answer["summary"], now, image=name,
                             check=n, confidence=answer["confidence"])
            rec["alert"]["pausing"] = True
            self._save()
            return rec["alert"]["id"]
        self._save()
        return None

    # -- alerts ------------------------------------------------------------
    def _open_alert(self, level: str, problem: str, summary: str, now: float, *, image=None,
                    check=None, confidence=None, paused=False, pause_error="", source="brain") -> None:
        rec = self.record
        current = rec.get("alert")
        if current and current.get("open") and current["level"] == level \
                and current["problem"] == problem and level == "warning":
            current.update(summary=summary, image=image or current.get("image"), updated=now,
                           check=check or current.get("check"))
            return
        if current and current.get("open"):
            if current["level"] == "failure" and level == "warning":
                return  # a paused failure outranks a later doubt
            self._close_alert("Replaced by a newer alert.", answer="replaced")
        alert = {"id": f"{rec['id']}-{len(rec['alerts']) + 1}", "level": level, "problem": problem,
                 "summary": summary, "at": now, "image": image, "check": check,
                 "confidence": confidence, "paused": bool(paused), "pause_error": pause_error,
                 "source": source, "open": True, "answer": None}
        rec["alert"] = alert
        rec["alerts"].append(alert)
        rec["alerts"] = rec["alerts"][-20:]
        log.warning("%s: %s — %s", self.pid, level, summary)

    def _close_alert(self, why: str, *, answer: str) -> None:
        alert = (self.record or {}).get("alert")
        if alert and alert.get("open"):
            alert.update(open=False, answer=answer, closed_at=self.owner.clock(), closed_why=why)

    def act(self, action: str, alert_id: str = "") -> str:
        with self.lock:
            rec = self.record
            alert = (rec or {}).get("alert")
            if action == "check":
                if rec is None or self.last_state not in ACTIVE | {"finish", "failed"}:
                    raise ValueError("There is no print to look at.")
                if self.view != "ok":
                    raise ValueError(STATUS_WORDS.get(self.view, "The camera cannot see the print."))
                if self.owner.brain_status()["state"] != "ok":
                    raise ValueError(self.owner.brain_status()["sentence"])
                if self.looking:
                    return "brAIn is already looking."
                if self.last_frame is None:
                    raise ValueError("No picture from the camera yet.")
                self._launch({"kind": "manual", "why": "The owner asked for a look.",
                              "at": self.owner.clock()}, self.owner.summary_of(self.pid))
                return "brAIn is looking at the print."
            if action == "plate_clear":
                self._plate_clear(self.owner.clock(), "You said the plate is clear.", learn=False)
                threading.Thread(target=self._learn_empty, daemon=True,
                                 name=f"watch-empty-{self.pid}").start()
                return "Marked the plate clear."
            if action == "plate_occupied":
                self.plate = {"state": "occupied", "since": self.owner.clock(),
                              "why": "You said something is on the plate."}
                self._save_plate()
                return "Marked the plate as having a print on it."
            if not alert or not alert.get("open"):
                raise ValueError("There is no open alert to answer.")
            if alert_id and alert_id != alert["id"]:
                raise ValueError("That alert has already been answered.")
            problem, answered = alert["problem"], alert["id"]
            if action == "ignore":
                if problem not in rec["ignored"]:
                    rec["ignored"].append(problem)
                self._close_alert("You said to ignore it.", answer="ignored")
                self._save()
                return (f"Ignoring {judge.PROBLEM_WORDS.get(problem, problem)} for the rest of " +
                        "this print.")
            if action not in ("resume", "pause", "stop"):
                raise ValueError(f"Unknown action {action!r}.")
        # The printer is told outside the lock: a command waits seconds for
        # its echo, and the panel's state is read under the same lock.
        self.owner.command(self.pid, protocol.simple(action), raise_errors=True)
        with self.lock:
            alert = (self.record or {}).get("alert")
            if alert and alert.get("id") == answered:
                if action == "resume" and problem not in self.record["no_pause"]:
                    self.record["no_pause"].append(problem)
                if action == "pause":
                    alert["paused"] = True
                self._close_alert({"resume": "You said it was a false alarm and resumed.",
                                   "pause": "You paused the print.",
                                   "stop": "You stopped the print."}[action],
                                  answer={"resume": "resumed", "pause": "paused",
                                          "stop": "stopped"}[action])
                self._save()
        return {"resume": "Resumed. The same problem will only be warned about, not paused for, " +
                          "on this print.",
                "pause": "Paused.", "stop": "Stopped."}[action]

    # -- what the panel and Home Assistant read ----------------------------
    def status(self, settings: dict, printer_state) -> str:
        if not settings["enabled"]:
            return "off"
        rec = self.record
        alert = (rec or {}).get("alert")
        active = printer_state in ACTIVE
        if alert and alert.get("open"):
            return alert["level"]
        if not active:
            return "idle"
        if self.view == "no_camera":
            return "no_camera"
        if self.view in ("covered", "dark"):
            return self.view
        if self.frozen:
            return "frozen"
        if self.looking:
            return "looking"
        if self.owner.brain_status()["state"] != "ok":
            return "basic"
        return "watching"

    def summary(self, printer_state=None) -> dict:
        settings = self.owner.settings_for(self.pid)
        with self.lock:
            rec = self.record or {}
            status = self.status(settings, printer_state)
            brain = self.owner.brain_status() if settings["enabled"] else self.brain
            sentence = STATUS_WORDS[status]
            if status == "basic":
                sentence = f"{STATUS_WORDS['basic']} {brain.get('sentence') or ''}".strip()
            if status == "no_camera" and self.camera_error:
                sentence = f"{STATUS_WORDS['no_camera']} {self.camera_error}"
            plan_ = rec.get("plan") or {}
            points = plan_.get("checkpoints") or []
            nxt = next((p for p in points if p.get("state") == "planned"), None)
            if status in ("watching", "looking") and nxt:
                sentence = f"Watching. Next look at layer {nxt['layer']}: {nxt['reason']}"
            last = rec.get("checks", [])[-1] if rec.get("checks") else None
            alert = rec.get("alert")
            base = f"api/watch/image?printer={urllib.parse.quote(self.pid)}&name="
            return {
                "enabled": settings["enabled"], "mode": settings["mode"],
                "sensitivity": settings["sensitivity"], "light": settings["light"],
                "plate_watch": settings["plate"],
                "status": status, "sentence": sentence, "view": self.view,
                "brain": brain,
                "plate": dict(self.plate),
                "print_id": rec.get("id"), "file": rec.get("file"),
                "alert": ({**alert, "image_url": (base + urllib.parse.quote(f"{rec['id']}/{alert['image']}")
                                                  if alert.get("image") else None)}
                          if alert else None),
                "last": ({**last, "image_url": (base + urllib.parse.quote(f"{rec['id']}/{last['image']}")
                                                if last.get("image") else None)} if last else None),
                "next": nxt,
                "expected_url": (base + urllib.parse.quote(f"{rec['id']}/expected.png")
                                 if rec.get("expected") else None),
                "plan": {"source": plan_.get("source"), "total_layers": plan_.get("total_layers"),
                         "note": rec.get("plan_note"),
                         "checkpoints": [{k: p.get(k) for k in ("layer", "kind", "reason", "also",
                                                                 "state", "decision")}
                                         for p in points]},
                "looks": {"used": rec.get("looks", 0), "budget": self._budget(),
                          "checks": len(rec.get("checks") or [])},
                "ignored": rec.get("ignored") or [],
            }

    def history(self) -> dict:
        with self.lock:
            rec = self.record or {}
            base = f"api/watch/image?printer={urllib.parse.quote(self.pid)}&name="
            checks = [{**c, "image_url": (base + urllib.parse.quote(f"{rec['id']}/{c['image']}")
                                          if c.get("image") else None)}
                      for c in rec.get("checks") or []]
            return {"print": {k: rec.get(k) for k in ("id", "file", "started_at", "finished_at",
                                                      "result", "plan_note", "looks", "ignored",
                                                      "no_pause")},
                    "checks": list(reversed(checks)), "alerts": list(reversed(rec.get("alerts") or [])),
                    "errors": rec.get("errors") or [],
                    "previous": ({k: (self.previous or {}).get(k) for k in ("file", "started_at",
                                                                            "result", "looks")}
                                 if self.previous else None)}

    def image(self, name: str) -> Path | None:
        m = NAME.match(str(name or ""))
        if not m:
            return None
        path = self.dir / m.group("print") / m.group("file")
        return path if path.is_file() else None


class Watcher:
    """Every printer's detection, and the doors to the rest of the panel.

    The panel hands in what it owns (the printer rows, the MQTT summaries,
    the cameras, the commands); everything that talks to a printer or to
    brAIn goes through one of these methods, so a test drives the whole
    state machine with fakes and no network.
    """

    def __init__(self, panel, *, data: Path | None = None, start_threads: bool = True):
        self.panel = panel
        self.data = data or DATA
        self.watches: dict[str, PrinterWatch] = {}
        self.settings = load_settings()
        self.start_threads = start_threads
        self._threads: dict[str, threading.Thread] = {}
        self._brain_cache = (0.0, {"state": "unknown", "sentence": ""})
        self.lock = threading.Lock()
        self.decode = vision.decode
        self.clock = time.time
        self.sleep = time.sleep

    # -- settings ----------------------------------------------------------
    def settings_for(self, pid: str) -> dict:
        return {**DEFAULTS, **((self.settings.get("printers") or {}).get(pid) or {})}

    def wanted(self, pid: str) -> bool:
        """A printer's thread runs for detection, or for the plate watch alone."""
        settings = self.settings_for(pid)
        return bool(settings["enabled"] or settings["plate"])

    def notify_target(self) -> str:
        return str(self.settings.get("notify") or "")

    def update_settings(self, pid: str | None, changes: dict) -> dict:
        with self.lock:
            data = json.loads(json.dumps(self.settings))
            if "notify" in changes:
                data["notify"] = clean_notify(changes["notify"])
            if pid:
                printers = data.setdefault("printers", {})
                printers[pid] = clean_settings(printers.get(pid) or {}, changes)
            bambu_atomic.write_json(SETTINGS_FILE, data)
            self.settings = data
        if pid and "sensitivity" in changes:
            self.watch(pid).replan()
        return self.settings_for(pid) if pid else {"notify": self.notify_target()}

    # -- the panel's half --------------------------------------------------
    def watch(self, pid: str) -> PrinterWatch:
        with self.lock:
            if pid not in self.watches:
                self.watches[pid] = PrinterWatch(self, pid)
            return self.watches[pid]

    def tick(self) -> None:
        """Called on the panel's timer: start a printer's thread once it is on."""
        for row in store.load():
            pid = row["id"]
            watch = self.watch(pid)
            if not self.start_threads:
                continue
            thread = self._threads.get(pid)
            if self.wanted(pid) and (thread is None or not thread.is_alive()):
                thread = threading.Thread(target=self._loop, args=(watch,), daemon=True,
                                          name=f"watch-{pid}")
                self._threads[pid] = thread
                thread.start()

    def _loop(self, watch: PrinterWatch) -> None:
        while self.wanted(watch.pid) and watch.pid in self.panel.clients:
            try:
                watch.step()
                watch.finish_look_due(time.time())
            except Exception:  # noqa: BLE001 - one bad step must not end the watch
                log.exception("Print failure detection for %s failed a step", watch.pid)
            time.sleep(STEP_S)

    def summary(self, pid: str, printer_state=None) -> dict:
        return self.watch(pid).summary(printer_state)

    def changed(self) -> None:
        mark = getattr(self.panel, "watch_changed", None)
        if callable(mark):
            mark()

    # -- doors to the rest of the panel (replaced by fakes in the tests) ---
    def row(self, pid: str) -> dict | None:
        return next((r for r in store.load() if r["id"] == pid), None)

    def summary_of(self, pid: str) -> dict | None:
        client = self.panel.clients.get(pid)
        return client.summary() if client else None

    def frame(self, pid: str) -> tuple[bytes | None, str]:
        try:
            camera = self.panel.camera(pid)
        except LookupError as exc:
            return None, str(exc)
        asked = time.time()
        camera.want()
        deadline = asked + FRAME_WAIT_S
        while time.time() < deadline:
            if camera.frame is not None and camera.frame_at >= asked - 3:
                return camera.frame, ""
            if camera.error and time.time() - asked > 2:
                break
            time.sleep(0.2)
        return None, camera.error or "The camera did not send a picture in time."

    def command(self, pid: str, payload: dict, raise_errors: bool = False) -> bool:
        client = self.panel.clients.get(pid)
        try:
            if client is None:
                raise ConnectionError("The printer is not connected.")
            client.send(payload)
            return True
        except (ConnectionError, RuntimeError, ValueError) as exc:
            if raise_errors:
                raise ValueError(str(exc)) from exc
            log.info("%s: a command from failure detection did not go through: %s", pid, exc)
            return False

    def pause(self, pid: str) -> tuple[bool, str]:
        summary = self.summary_of(pid) or {}
        if summary.get("state") != "running":
            return False, "The printer was no longer printing."
        client = self.panel.clients.get(pid)
        try:
            client.send(protocol.simple("pause"))
            return True, ""
        except (ConnectionError, RuntimeError, ValueError, AttributeError) as exc:
            return False, f"The printer did not pause: {exc}"

    def brain_status(self) -> dict:
        at, cached = self._brain_cache
        if time.time() - at < 30:
            return cached
        state = brain_link.status()
        self._brain_cache = (time.time(), state)
        return state

    def ask(self, question: str, images: list[bytes], scheduled: bool = True) -> tuple[dict | None, str]:
        """One look by brAIn; (answer, "") or (None, why not)."""
        try:
            task = brain_link.submit(question, schema=judge.SCHEMA, kind="look", images=images,
                                     scheduled=scheduled, timeout=judge.TIMEOUT_S,
                                     model=prefs.load()["look_model"])
            result = brain_link.wait(task, judge.TIMEOUT_S)
        except (brain_link.NotListening, TimeoutError, OSError) as exc:
            return None, str(exc)
        if result.get("status") == "failed" or result.get("error"):
            return None, str(result.get("result") or result.get("error") or "brAIn could not look.")
        answer = judge.parse(result.get("data"))
        if answer is None:
            return None, "brAIn's answer could not be read."
        return answer, ""

    def mirror_check(self, pid: str, frame: bytes) -> None:
        """The frame brAIn last judged, for Home Assistant's Last check camera."""
        if not SHARED.parent.is_dir():
            return
        try:
            (SHARED / "camera").mkdir(parents=True, exist_ok=True)
            bambu_atomic.write_bytes(SHARED / "camera" / f"{pid}.check.jpg", frame)
        except OSError:
            pass  # Home Assistant's copy is a convenience; the panel keeps the frame

    def read_print(self, pid: str, summary: dict) -> tuple[dict | None, bytes | None, str]:
        """The print's G-code facts and its picture, from the library or the printer."""
        plate_n = 1
        m = re.search(r"plate_(\d+)", str(summary.get("gcode_file") or ""))
        if m:
            plate_n = int(m.group(1))
        name = summary.get("file") or ""
        known = getattr(self.panel, "uploaded", {}).get(pid) or {}
        source = known.get(name) or known.get(os.path.basename(str(summary.get("gcode_file") or "")))
        if source:
            path = library.path_of(source)
            facts = plan.read_plate(str(path), plate_n)
            picture = thumbs.library(path, plate_n)
            return facts, picture, ""
        row = self.row(pid)
        client = self.panel.clients.get(pid)
        if not row or not client or not name:
            return None, None, "The print's file is not known, so looks are spread by layer."
        with ftps.Storage(row["host"], client.code) as storage:
            files = [f for f in storage.listing("/") if not f["dir"]
                     and f["name"].lower().endswith(".3mf")]
            stem = re.sub(r"(\.gcode)?\.3mf$", "", name, flags=re.I)
            match = next((f for f in files if re.sub(r"(\.gcode)?\.3mf$", "", f["name"],
                                                     flags=re.I) == stem), None)
            if match is None:
                return None, None, ("The print's file is not on the printer's storage, so looks " +
                                    "are spread by layer.")
            remote = ftps.RemoteFile(storage, match["name"], match.get("size") or 0)
            facts = plan.read_plate(remote, plate_n)
            remote.pos = 0
            try:
                picture = thumbs.from_zip(remote, plate_n)
            except OSError:
                picture = None
        return facts, picture, ""
