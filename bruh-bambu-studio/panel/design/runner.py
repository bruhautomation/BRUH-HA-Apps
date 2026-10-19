"""Run a design script's build in a process of its own.

The CAD stack (CadQuery, OpenCascade, trimesh) lives in its own virtualenv
at /opt/cad so its pinned libraries never meet the panel's. The build gets
an environment with nothing in it but a PATH and a scratch HOME — no
SUPERVISOR_TOKEN, no proxy settings, nothing inherited — a CPU-time limit,
and a cap on how much it may write.
"""
from __future__ import annotations

import json
import os
import resource
import subprocess
import tempfile
from pathlib import Path

CAD_PYTHON = os.environ.get("BAMBU_CAD_PYTHON", "/opt/cad/bin/python")
CAD_DIR = Path(os.environ.get("BAMBU_CAD_DIR", "/opt/bruh-bambu/cad"))
TIMEOUT_S = 300
MAX_WRITE_BYTES = 512 * 1024 * 1024


def available() -> bool:
    return os.path.isfile(CAD_PYTHON) and (CAD_DIR / "build.py").is_file()


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_S, TIMEOUT_S + 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_WRITE_BYTES, MAX_WRITE_BYTES))


def build(script: Path, outdir: Path) -> dict:
    """Run the build; return its report (always a dict with `ok`)."""
    if not available():
        return {"ok": False, "stage": "setup",
                "error": "The CAD tools are not installed in this add-on image."}
    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cad-home-") as home:
        env = {"PATH": "/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8",
               "PYTHONDONTWRITEBYTECODE": "1", "MPLBACKEND": "Agg"}
        try:
            result = subprocess.run(
                [CAD_PYTHON, str(CAD_DIR / "build.py"), str(script), str(outdir)],
                cwd=str(outdir), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=TIMEOUT_S + 30, preexec_fn=_limits, check=False)
        except subprocess.TimeoutExpired:
            return {"ok": False, "stage": "timeout",
                    "error": f"The build took longer than {TIMEOUT_S // 60} minutes."}
    try:
        report = json.loads((outdir / "report.json").read_text())
    except (OSError, ValueError):
        tail = result.stdout.decode(errors="replace").strip().splitlines()[-6:]
        report = {"ok": False, "stage": "crash",
                  "error": f"The build stopped (exit {result.returncode}) without a report.",
                  "traceback": tail}
    report["exit"] = result.returncode
    return report
