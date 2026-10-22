"""Slice with Bambu Studio's own command line.

The same binary the sidebar shows has a CLI (`--slice`, `--export-3mf`),
so a slice from Home Assistant or brAIn is a slice by the real slicer with
the real profiles, not an approximation of one. Two ways in, and the first
is the one that is always right:

* A Bambu PROJECT (.3mf saved from Bambu Studio) carries its printer,
  process and filament settings, so it slices exactly as it would in the
  GUI with nothing else named.
* A bare model (.stl, .step, .obj, or a .3mf from somewhere else) carries
  no settings, so the CLI has to be handed them: a machine, a process and
  filament profile, by the names Bambu Studio lists, looked up in the
  install's own `resources/profiles/BBL`. That works for the common case
  and is honest about the rest — a profile name that is not there is
  refused naming the near ones, never guessed.

The CLI wants a display even when it never draws (it initialises GTK), so
it runs against the same virtual screen as the GUI. A slice is minutes of
CPU, so it is a job: started, polled, never awaited by a request.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

import installer
import library
from bambu import threemf

TIMEOUT_S = 1800
# The command line gets a profile folder of its own. Sharing the window's
# meant two Bambu Studios reading and writing one BambuStudio.conf and one
# preset folder at once.
SLICE_HOME = Path(os.environ.get("BAMBU_SLICE_HOME", "/data/slicer-home"))
# What a slice of a part needs free before it runs beside the window; less,
# and the window is closed for the slice (studio.make_room) and reopened.
SLICE_MEMORY_MB = 1500
# Set by the panel: Studio.make_room, so a slice can ask for the memory.
MAKE_ROOM = None
MAX_JOBS = 30
JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


# What the CLI's exit codes mean (src/libslic3r/Utils.hpp, the cli_errors
# table in src/BambuStudio.cpp), in words for somebody printing a part — every
# code in that table. The process exits with the negative code, which the
# shell reads as 256 + code.
EXIT_REASONS = {
    -1: "it could not set itself up to run (its folders or display)",
    -2: "it was handed settings it could not use together",
    -3: "an input file was not found",
    -4: "the files were handed over in the wrong order (a project file has to come first)",
    -5: "a printer, process or filament profile could not be read",
    -6: "the model file could not be read",
    -7: "the printer is not a filament printer it supports",
    -8: "it was asked to do something its command line cannot do",
    -9: "it could not copy the objects",
    -10: "it could not scale the part to fit the plate",
    -11: "it could not export an STL",
    -12: "it could not export an OBJ",
    -13: "it could not write the sliced file",
    -14: "it ran out of memory; a simpler model would help",
    -15: "the printer is not one it supports",
    -16: "the printer does not match the file",
    -17: "the process profile does not list this printer as compatible",
    -18: "the file carries a setting value it rejects",
    -19: "the file asks for a post-processing script, which it will not run here",
    -20: "the printer's bed is smaller than the profile's",
    -21: "it could not arrange the part on the plate",
    -22: "it could not turn the part to a good orientation",
    -23: "the printer's printable area or height was changed, which it does not allow",
    -24: "the file was made by a newer Bambu Studio than this one",
    -25: "the file uses a feature it does not support yet",
    -50: "nothing is fully on the plate",
    -51: "a slicing setting is wrong",
    -52: "part of the model is over the edge of the bed",
    -53: "it could not make a folder for its cache",
    -54: "it could not write its cache",
    -55: "its cache was not found",
    -56: "its cache could not be read",
    -57: "it could not load its cache",
    -58: "slicing took longer than it allows; a simpler model or thicker layers would help",
    -59: "the model has too many triangles; a simpler model would help",
    -60: "nothing was left to print after skipping objects",
    -61: "a filament does not suit the build plate",
    -62: "the filaments' temperatures are too far apart to print together",
    -63: "objects collide when printed one at a time",
    -64: "objects collide",
    -65: "a setting does not work with spiral vase mode",
    -66: "a filament could not be mapped to the printer",
    -67: "it will not print two TPU filaments together",
    -68: "a filament cannot be printed by the nozzle it was mapped to",
    -100: "slicing failed",
    -101: "the sliced paths collide (often the prime tower; moving it further in helps)",
    -102: "some of the print would be in an area this printer's nozzles cannot reach",
    -103: "a filament cannot print on the first layer of this plate",
    -104: "some of the print would be outside the printable area",
    -105: "some of the print would be where the printer checks for filament wrapping",
}

# What to change, for the codes whose cure is not in the words above. The
# CLI's own line (cli_error_lines) says which setting, where it names one.
EXIT_ADVICE = {
    -2: ("Nothing in the part needs changing; this is the add-on asking the slicer the "
         "wrong way. Open the part in Bambu Studio and slice it there, and report this "
         "with the slicer's words."),
    -5: "Updating Bambu Studio on the Studio tab reinstalls its profiles.",
    -24: "Update Bambu Studio on the Studio tab.",
}

# What the CLI's own message means, when it names the condition (the error
# lines in src/BambuStudio.cpp before each CLI_INVALID_PARAMS).
_INVALID_HINTS = (
    (("invalid plate", "plate id"), "it was asked for a plate the file does not have"),
    (("repetitions",), "copies were asked for in a way it does not take"),
    (("filament_id", "load_filaments", "uptodate_filaments", "filament config not loaded",
      "filament_colour"),
     "the filaments it was handed do not match the part's filaments"),
    (("nozzle manual", "filament_volume_map", "filament_nozzle_map"),
     "the filaments were not mapped to the printer's nozzles"),
    (("clone_objects", "loaded_filament_ids", "assemble"),
     "it was asked to copy or assemble objects in a way it does not take"),
    (("metadata_name",), "the file's extra metadata was handed over unpaired"),
    (("scale ratio",), "the part was scaled by a number it cannot use"),
)

# Lines the CLI writes that are not the reason: its own sign-off, and progress.
_NOT_A_REASON = ("found error, return", "found error, exit", "slicer_info_report")
_CERR_REASONS = ("no such file", "setup params error", "params in command line error",
                 "error:", "invalid printer_technology", "duplicate machine config",
                 "duplicate process config", "can not find setting file", "unsupported",
                 "unknown config type", "failed")


def cli_error_lines(lines: list[str]) -> list[str]:
    """The CLI's own words for why it stopped, in the order it said them.

    Its log lines look like "[time] [thread] [error]   message"; a few
    messages go to stderr bare ("No such file: …"). The last line it
    prints, "run found error, return -2, exit...", says only that it stopped,
    so it is never the reason.
    """
    out: list[str] = []
    for raw in lines:
        line = raw.strip()
        low = line.lower()
        if not line or any(n in low for n in _NOT_A_REASON):
            continue
        text = None
        for tag in ("[error]", "[fatal]"):
            if tag in low:
                text = line[low.index(tag) + len(tag):].strip()
                break
        if text is None and not line.startswith("[") and low.startswith(_CERR_REASONS):
            text = line
        if text is None:
            continue
        # BambuStudio logs "run: " / "operator(): " in front of some lines.
        for prefix in ("run:", "run :", "operator():", "operator() :"):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        text = text.replace("%%", "%")
        if text and text not in out:
            out.append(text)
    return out


def invalid_hint(said: list[str]) -> str:
    """For exit -2: which of its parameter checks the CLI named, in words."""
    joined = " ".join(said).lower()
    for words, sentence in _INVALID_HINTS:
        if any(w in joined for w in words):
            return sentence
    return ""


def failure_message(returncode: int, lines: list[str]) -> str:
    """Everything the owner needs from a failed slice, uncut: what the code
    means, what Bambu Studio itself said, and what to change."""
    code = returncode - 256 if returncode > 127 else returncode
    reason = exit_reason(returncode)
    said = cli_error_lines(lines)
    if code == -2:
        hint = invalid_hint(said)
        if hint:
            reason = f"{reason}: {hint}"
    if not reason and said:
        reason = said[-1]
    text = f"Bambu Studio could not slice it (exit {returncode})"
    text += f": {reason}." if reason and not reason.endswith(".") else (f": {reason}" if reason else ".")
    named = rejected(lines)
    if named:
        text += f" It named: {'; '.join(named)}."
    shown = [s for s in said if s not in named and s != reason]
    if shown:
        text += " Bambu Studio said: " + " / ".join(shown)
        text += "" if text.endswith(".") else "."
    advice = EXIT_ADVICE.get(code)
    if advice:
        text += " " + advice
    return text


SIGNAL_REASONS = {
    9: "it was killed, most likely because the machine ran out of memory",
    11: "it crashed",
    6: "it crashed",
}


def exit_reason(returncode: int) -> str:
    if returncode < 0:
        # subprocess reports a signal as a negative code; one it does not
        # name may be the CLI's own code handed in as written (-17).
        if -returncode in SIGNAL_REASONS:
            return SIGNAL_REASONS[-returncode]
        return EXIT_REASONS.get(returncode, f"it was stopped by signal {-returncode}")
    if returncode in (137, 139, 134):  # a shell's 128 + signal
        return SIGNAL_REASONS[returncode - 128]
    code = returncode - 256 if returncode > 127 else returncode
    return EXIT_REASONS.get(code, "")


def rejected(lines: list[str]) -> list[str]:
    """The settings the CLI named when it refused the config (exit -18).

    It prints "Param values in 3mf/config error:" and then one
    "key: why" line per setting, which is the only place the culprit is
    named; without it the failure is a number.
    """
    out = []
    for i, line in enumerate(lines):
        if "Param values in 3mf/config error" in line:
            for row in lines[i + 1:i + 12]:
                row = row.strip()
                if ":" in row and not row.lower().startswith(("[", "error", "warning")):
                    # The CLI prints its format string's escaped "%%" as is.
                    out.append(row.replace("%%", "%")[:200])
            break
    return out


def slice_env(base: dict | None) -> dict:
    """The window's environment with a home of the command line's own."""
    env = dict(base or os.environ)
    try:
        SLICE_HOME.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(SLICE_HOME)
    except OSError:
        pass  # the window's home still slices; it only shares the presets
    return env


def profile_names(kind: str) -> list[str]:
    root = installer.resources()
    if root is None:
        return []
    folder = root / "profiles" / "BBL" / kind
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.json"))


def profile_path(kind: str, name: str) -> Path:
    names = profile_names(kind)
    if not names:
        raise LookupError("Bambu Studio's profiles are not installed yet.")
    if name not in names:
        near = difflib.get_close_matches(name, names, n=4, cutoff=0.4)
        raise LookupError(f"No {kind} profile called {name!r}."
                          + (f" Did you mean: {'; '.join(near)}?" if near else ""))
    return installer.resources() / "profiles" / "BBL" / kind / f"{name}.json"


# How copies reach the CLI. `--repetitions N` repeats one plate's model, and
# src/BambuStudio.cpp keeps the plate asked for only for a 3MF Bambu Studio
# wrote itself — any other input is reset to plate 0 ("not support to slice
# plate"), and then `--repetitions` is refused ("can not set repetitions when
# slice all", exit 254). Its importer (bbs_3mf.cpp) knows its own 3MF by the
# model's Application metadata starting "BambuStudio-". So:
#   repetitions - Bambu Studio's own project: --slice <plate> --repetitions N
#   instances   - any other 3MF (a designed part is one): a copy whose build
#                 lists each item N times, which the importer reads as N
#                 instances of the object (_handle_start_item)
#   files       - a bare model: the file handed over N times
# and the last two are laid out with --arrange 1.
COPIES_WAYS = ("repetitions", "instances", "files")
_APPLICATION = re.compile(
    rb'<metadata\s[^>]*name\s*=\s*"Application"[^>]*>\s*BambuStudio-', re.I)


def _root_model(archive: zipfile.ZipFile) -> str:
    """The 3MF's root model part, as its relationships name it."""
    try:
        rels = archive.read("_rels/.rels").decode(errors="replace")
        found = re.search(r'Target="/?([^"]+\.model)"', rels)
        if found and found.group(1) in archive.namelist():
            return found.group(1)
    except KeyError:
        pass  # no relationships part: the 3MF default name below is the answer
    return "3D/3dmodel.model"


def copies_way(source: Path) -> str:
    """Which of COPIES_WAYS `source` takes its copies by."""
    if not source.name.lower().endswith(".3mf"):
        return "files"
    try:
        with zipfile.ZipFile(source) as archive:
            model = archive.read(_root_model(archive))
    except (OSError, KeyError, zipfile.BadZipFile):
        # Unreadable: the CLI will say so itself; ask it Bambu's own way.
        return "repetitions"
    return "repetitions" if _APPLICATION.search(model) else "instances"


_BUILD = re.compile(rb"(<build\b[^>]*>)(.*?)(</build>)", re.S)
_ITEM = re.compile(rb"<item\b[^>]*?(?:/>|>.*?</item>)", re.S)


def with_copies(source: Path, target: Path, copies: int) -> None:
    """Copy the 3MF `source` to `target` with every build item listed
    `copies` times. Everything else in the file is copied byte for byte."""
    with zipfile.ZipFile(source) as archive:
        name = _root_model(archive)
        model = archive.read(name)
        build = _BUILD.search(model)
        items = _ITEM.findall(build.group(2)) if build else []
        if not items:
            raise ValueError(f"{source.name} has nothing in its build to make copies of.")
        repeated = b"".join(items) * int(copies)
        model = model[:build.start(2)] + repeated + model[build.end(2):]
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
            for item in archive.infolist():
                if item.filename == name:
                    out.writestr(name, model)
                else:
                    with archive.open(item) as src, out.open(item.filename, "w") as dst:
                        shutil.copyfileobj(src, dst)


def command(apprun: str, source: Path, out: Path, *, plate: int = 0,
            machine: Path | None = None, process: Path | None = None,
            filaments: list[Path] | None = None, arrange: bool = False,
            orient: bool = False, copies: int = 1, copies_as: str | None = None) -> list[str]:
    """The CLI's argv. With copies, `source` is already the file for the way
    they are taken (with_copies for "instances")."""
    plate = max(0, int(plate))
    copies = max(1, int(copies))
    way = (copies_as or copies_way(source)) if copies > 1 else None
    if way == "repetitions" and plate == 0:
        # The CLI repeats one plate's model, never "every plate".
        plate = 1
    elif way in ("instances", "files"):
        # The CLI would reset any other plate to 0 for these anyway.
        plate = 0
    argv = [apprun, "--slice", str(plate),
            "--export-3mf", out.name, "--outputdir", str(out.parent)]
    settings = [str(p) for p in (machine, process) if p]
    if settings:
        argv += ["--load-settings", ";".join(settings)]
    if filaments:
        argv += ["--load-filaments", ";".join(str(p) for p in filaments)]
    if arrange or way:
        argv += ["--arrange", "1"]
    if orient:
        argv += ["--orient", "1"]
    if way == "repetitions":
        argv += ["--repetitions", str(copies)]
    argv += [str(source)] * (copies if way == "files" else 1)
    return argv


def _output_for(source: Path) -> Path:
    stem = source.name
    for ext in (".gcode.3mf",) + library.SUFFIXES:
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    return library.unique(library.ROOT / library.SLICED / f"{stem}.gcode.3mf")


def start(source_rel: str, *, plate: int = 0, machine: str = "", process: str = "",
          filaments: list[str] | None = None, arrange: bool = False,
          orient: bool = False, env: dict | None = None, copies: int = 1) -> dict:
    """Check the request, then slice on a thread. Returns the job."""
    source = library.path_of(source_rel)
    if not source.is_file():
        raise FileNotFoundError(f"No file {source_rel!r} in the library.")
    is_project = source.name.lower().endswith(".3mf")
    if not is_project and not (machine and process):
        raise ValueError(
            "A bare model has no printer or process settings in it. Name a machine "
            "and a process profile (bambu status lists them), or save it as a "
            "project from Bambu Studio first.")
    m = profile_path("machine", machine) if machine else None
    p = profile_path("process", process) if process else None
    f = [profile_path("filament", name) for name in (filaments or [])]
    return start_paths(source, plate=plate, machine=m, process=p, filaments=f,
                       arrange=arrange, orient=orient, env=env, copies=copies)


def start_paths(source: Path, *, plate: int = 0, machine: Path | None = None,
                process: Path | None = None, filaments: list[Path] | None = None,
                arrange: bool = False, orient: bool = False, env: dict | None = None,
                out: Path | None = None, copies: int = 1) -> dict:
    """Slice with settings files already chosen (a designed part's own)."""
    run = installer.apprun()
    if run is None:
        raise RuntimeError("Bambu Studio is not installed yet — it downloads on first start.")
    out = out or _output_for(source)
    job = {"id": uuid.uuid4().hex[:12], "kind": "slice", "state": "running",
           "source": library.relative(source), "output": None, "error": "",
           "started": time.time(), "finished": None, "info": None, "log": []}
    work = Path(tempfile.mkdtemp(prefix="slice-"))
    handed, way = source, None
    if int(copies) > 1:
        way = copies_way(source)
        if way == "instances":
            # Same name, so Bambu Studio names the object as before.
            handed = work / "copies" / source.name
            try:
                with_copies(source, handed, copies)
            except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
                shutil.rmtree(work, ignore_errors=True)
                raise ValueError(f"Could not lay out {copies} copies of {source.name}: "
                                 f"{exc}") from None
    argv = command(str(run), handed, out, plate=plate, machine=machine, process=process,
                   filaments=filaments, arrange=arrange, orient=orient, copies=copies,
                   copies_as=way)
    with _LOCK:
        JOBS[job["id"]] = job
        for old in sorted(JOBS.values(), key=lambda j: j["started"])[:-MAX_JOBS]:
            JOBS.pop(old["id"], None)
    threading.Thread(target=_run, args=(job, argv, out, env, work), daemon=True).start()
    return job


def _run(job: dict, argv: list[str], out: Path, env: dict | None,
         work: Path | None = None) -> None:
    # The CLI writes beside itself in places; a scratch working directory
    # keeps that out of the library (and holds a copies file, removed after).
    work = work or Path(tempfile.mkdtemp(prefix="slice-"))
    resume = None
    try:
        if MAKE_ROOM is not None:
            try:
                resume = MAKE_ROOM(SLICE_MEMORY_MB)
            except Exception:  # noqa: BLE001 - asking for room must not stop a slice
                resume = None
            if resume is not None:
                job["log"].append("Bambu Studio's window was closed while this sliced, "
                                  "to free memory; it reopens afterwards.")
        result = subprocess.run(argv, cwd=work, env=slice_env(env),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=TIMEOUT_S, check=False)
        lines = result.stdout.decode(errors="replace").strip().splitlines()
        # The reason is said before the CLI's long sign-off, so the error
        # lines are kept whole wherever in the log they were.
        said = cli_error_lines(lines)
        job["log"] = job["log"] + [line for line in lines[-40:]]
        if result.returncode != 0 or not out.exists():
            job["rejected"] = rejected(lines)
            job["said"] = said
            if result.returncode == 0:
                job.update(state="failed", error=(
                    "Bambu Studio finished without writing the sliced file"
                    + (". Bambu Studio said: " + " / ".join(said) if said else "") + "."))
            else:
                job.update(state="failed", error=failure_message(result.returncode, lines))
            return
        info = threemf.inspect(str(out))
        if not info["sliced"]:
            job.update(state="failed", error="Bambu Studio wrote a file with no G-code in it.")
            return
        job.update(state="done", output=library.relative(out), info=info)
    except subprocess.TimeoutExpired:
        job.update(state="failed", error=f"Slicing took longer than {TIMEOUT_S // 60} minutes.")
    except OSError as exc:
        job.update(state="failed", error=f"Could not run Bambu Studio: {exc}")
    finally:
        job["finished"] = time.time()
        shutil.rmtree(work, ignore_errors=True)
        if resume is not None:
            try:
                resume()
            except Exception:  # noqa: BLE001 - the panel's timer starts it again anyway
                pass


def get(job_id: str) -> dict | None:
    return JOBS.get(job_id)


def wait(job_id: str, timeout: float) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = JOBS.get(job_id)
        if job is None or job["state"] != "running":
            return job
        time.sleep(1)
    return JOBS.get(job_id)
