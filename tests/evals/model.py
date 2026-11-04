"""Asking a pinned model, through the `claude` CLI headless.

The same door the house's jobs use (`claude -p --output-format json`), with
everything around the run taken away: no tools, no MCP servers, no project
or user settings, Claude Code's own memory off, and a scratch working
directory, so what is graded is the prompt and the model and nothing the
runner's machine happens to have lying about.

The model is always named. ``""`` is refused rather than passed through as
"the CLI's default", because a number with no model attached is a number
that moves when the account's default does and says nothing about why.

``EVALS_CLAUDE_BIN`` replaces the binary (split like a shell word list),
which is how the runner's own tests stand a fake in for the real CLI.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import time

# The models each job is graded on, pinned to full ids rather than the tier
# aliases the add-on uses (`model_plan`): an alias is the account's choice
# and moves under the number. The tier is the job's own in model_plan.py.
PINNED_MODELS = {
    "extractor": "claude-haiku-5-5",
    "consolidator": "claude-haiku-5-5",
    "reflect": "claude-haiku-5-5",
    "first_look": "claude-haiku-5-5",
    "morph_learning": "claude-sonnet-5-5",
    "devloop_streams": "claude-sonnet-5-5",
}

DEFAULT_TIMEOUT_S = 300
ISOLATION_SETTINGS = {"autoMemoryEnabled": False}


def claude_argv() -> list[str]:
    override = os.environ.get("EVALS_CLAUDE_BIN", "").strip()
    return shlex.split(override) if override else ["claude"]


def child_env() -> dict:
    env = dict(os.environ)
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    env["CLAUDE_CODE_DISABLE_ADVISOR_TOOL"] = "1"
    return env


def usage_tokens(envelope: dict) -> int:
    usage = envelope.get("usage") if isinstance(envelope, dict) else None
    if not isinstance(usage, dict):
        return 0
    return sum(int(usage.get(k) or 0) for k in (
        "input_tokens", "output_tokens", "cache_creation_input_tokens",
        "cache_read_input_tokens"))


def models_used(envelope: dict) -> list[str]:
    """The model ids the CLI reports it actually ran, which can differ from
    the one asked for (a fallback). Recorded beside every score."""
    used = envelope.get("modelUsage") if isinstance(envelope, dict) else None
    return sorted(used) if isinstance(used, dict) else []


def read_envelope(stdout: str) -> dict:
    try:
        env = json.loads(stdout or "")
    except ValueError:
        return {}
    return env if isinstance(env, dict) else {}


def extract_json(text: str):
    """The first JSON object in a reply, or None."""
    text = str(text or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


def ask(prompt: str, system: str, model: str, *, schema: dict | None = None,
        timeout: int = DEFAULT_TIMEOUT_S) -> dict:
    """One headless turn. ``{ok, text, data, tokens, models, error, seconds}``.

    ``data`` is the CLI's schema-validated object when a schema was given
    and it answered with one, else the first JSON object in the text.
    """
    if not model:
        raise ValueError("an eval run always names its model")
    argv = claude_argv() + [
        "-p", "--output-format", "json", "--model", model,
        "--tools", "", "--strict-mcp-config", "--setting-sources", "",
        "--settings", json.dumps(ISOLATION_SETTINGS, separators=(",", ":")),
    ]
    if system:
        argv += ["--system-prompt", system]
    if schema:
        argv += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="brain-eval-") as cwd:
        try:
            proc = subprocess.run(argv, input=prompt, capture_output=True,
                                  text=True, timeout=timeout, cwd=cwd,
                                  env=child_env(), check=False)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"no answer inside {timeout}s",
                    "text": "", "data": None, "tokens": 0, "models": [],
                    "seconds": round(time.monotonic() - started, 1)}
        except OSError as exc:
            return {"ok": False, "error": f"could not start the CLI: {exc}",
                    "text": "", "data": None, "tokens": 0, "models": [],
                    "seconds": 0.0}
    seconds = round(time.monotonic() - started, 1)
    envelope = read_envelope(proc.stdout)
    text = envelope.get("result") if isinstance(envelope.get("result"), str) \
        else (proc.stdout or "")
    failed = proc.returncode != 0 or envelope.get("is_error") is True
    data = envelope.get("structured_output")
    if not isinstance(data, dict):
        data = extract_json(text)
    out = {"ok": not failed, "text": text, "data": data,
           "tokens": usage_tokens(envelope), "models": models_used(envelope),
           "seconds": seconds, "error": ""}
    if failed:
        tail = (text or proc.stderr or "").strip().splitlines()
        out["error"] = (tail[-1] if tail else f"exit {proc.returncode}")[:300]
    return out
