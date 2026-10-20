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
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
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
# table in src/BambuStudio.cpp), in words for somebody printing a part. The
# process exits with the negative code, which the shell reads as 256 + code.
EXIT_REASONS = {
    -3: "an input file was not found",
    -5: "a printer, process or filament profile could not be read",
    -6: "the model file could not be read",
    -14: "it ran out of memory; a simpler model would help",
    -15: "the printer is not one it supports",
    -16: "the printer does not match the file",
    -17: "the process profile does not list this printer as compatible",
    -18: "the file carries a setting value it rejects",
    -20: "the printer's bed is smaller than the profile's",
    -21: "it could not arrange the part on the plate",
    -50: "nothing is fully on the plate",
    -51: "a slicing setting is wrong",
    -52: "part of the model is over the edge of the bed",
    -61: "a filament does not suit the build plate",
    -62: "the filaments' temperatures are too far apart to print together",
    -64: "objects collide",
    -66: "a filament could not be mapped to the printer",
    -67: "it will not print two TPU filaments together",
    -100: "slicing failed",
    -104: "some of the print would be outside the printable area",
}


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


def command(apprun: str, source: Path, out: Path, *, plate: int = 0,
            machine: Path | None = None, process: Path | None = None,
            filaments: list[Path] | None = None, arrange: bool = False,
            orient: bool = False, copies: int = 1) -> list[str]:
    plate = max(0, int(plate))
    if copies > 1 and plate == 0:
        # The CLI repeats one plate's model, never "every plate".
        plate = 1
    argv = [apprun, "--slice", str(plate),
            "--export-3mf", out.name, "--outputdir", str(out.parent)]
    settings = [str(p) for p in (machine, process) if p]
    if settings:
        argv += ["--load-settings", ";".join(settings)]
    if filaments:
        argv += ["--load-filaments", ";".join(str(p) for p in filaments)]
    if arrange:
        argv += ["--arrange", "1"]
    if orient:
        argv += ["--orient", "1"]
    if copies > 1:
        argv += ["--repetitions", str(int(copies))]
        if not arrange:
            argv += ["--arrange", "1"]
    argv.append(str(source))
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
    argv = command(str(run), source, out, plate=plate, machine=machine, process=process,
                   filaments=filaments, arrange=arrange, orient=orient, copies=copies)
    with _LOCK:
        JOBS[job["id"]] = job
        for old in sorted(JOBS.values(), key=lambda j: j["started"])[:-MAX_JOBS]:
            JOBS.pop(old["id"], None)
    threading.Thread(target=_run, args=(job, argv, out, env), daemon=True).start()
    return job


def _run(job: dict, argv: list[str], out: Path, env: dict | None) -> None:
    # The CLI writes beside itself in places; a scratch working directory
    # keeps that out of the library.
    work = Path(tempfile.mkdtemp(prefix="slice-"))
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
        job["log"] = job["log"] + [line[:300] for line in lines[-40:]]
        if result.returncode != 0 or not out.exists():
            reason = exit_reason(result.returncode) or next(
                (ln.strip()[:240] for ln in reversed(lines) if "error" in ln.lower()), "")
            named = rejected(lines)
            job["rejected"] = named
            job.update(state="failed", error=(
                f"Bambu Studio could not slice it (exit {result.returncode})"
                + (f": {reason}." if reason and not reason.endswith(".") else
                   f": {reason}" if reason else ".")
                + (f" It named: {'; '.join(named)}." if named else "")))
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
