"""Per job: build the REAL prompt with the job's own builder, and turn the
model's answer into the output its grader reads.

Every builder is imported from where the job lives, never copied: the
point of an eval is to measure the prompt that ships, and a copy measures
the release that made it. Other changes move these builders all the time,
so each adapter reaches for as little of a module as it can — the public
builder, the system prompt, the schema and the parser — and a builder that
has moved is a loud error in ``build`` (which the no-token CI run exercises
for every case), never a silently different prompt.

``build(case)`` -> ``Request``; ``run(case, model, ask)`` -> ``Trial``.
``ask`` is ``evals.model.ask`` or a stand-in with its signature.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .graders import first_look as first_look_grader
from .graders.common import dated

HERE = Path(__file__).resolve().parent
TESTS = HERE.parent
REPO = TESTS.parent
PANEL = REPO / "brain" / "panel"
SCRIPTS = REPO / "brain" / "scripts"
EXTRACTOR = SCRIPTS / "brain-memory-extract.py"
CONSOLIDATOR = SCRIPTS / "brain-memory-consolidate.sh"
TEE = HERE / "claude_tee.py"
CONSOLIDATE_TIMEOUT_S = 600

# What the Morph pass is told about itself in an eval. In the house the
# pass is a brAIn task with read-only Home Assistant tools; an eval run has
# no house to read, so the digest in the prompt is all it gets — which is
# also all the prompt promises it ("everything you need ... is below").
MORPH_SYSTEM = ("You are brAIn, answering one task Morph, the house's "
                "dashboard, sent you. Answer with the JSON its schema asks for.")


@dataclass
class Request:
    prompt: str = ""
    system: str = ""
    schema: dict | None = None
    extra: dict = field(default_factory=dict)
    # Set when the job's own code decided there was nothing to ask (the
    # extractor's worth-check): the output, with no model run at all.
    decided: dict | None = None


@dataclass
class Trial:
    output: dict | None = None
    tokens: int = 0
    models: list = field(default_factory=list)
    error: str = ""
    seconds: float = 0.0


def _panel_path() -> None:
    if str(PANEL) not in sys.path:
        sys.path.insert(0, str(PANEL))


# --------------------------------------------------------------- extractor

_EXTRACT_MOD = None


def extractor_module():
    """The extractor script, loaded under a name of its own (its file name
    has dashes). Loaded once: it reads its paths from the environment at
    import and touches nothing until a function is called."""
    global _EXTRACT_MOD
    if _EXTRACT_MOD is None:
        spec = importlib.util.spec_from_file_location("brain_memory_extract_eval",
                                                      EXTRACTOR)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _EXTRACT_MOD = mod
    return _EXTRACT_MOD


def write_transcript(turns: list, path: Path) -> None:
    """A case's ``transcript`` as Claude Code's JSONL: one event per turn,
    each with a uuid. A turn's ``content`` is a string or the CLI's content
    blocks — a ``tool_result`` block in a user event is a tool's output,
    which is exactly what the extractor must not learn from."""
    with path.open("w", encoding="utf-8") as fh:
        for i, turn in enumerate(turns or [], 1):
            role = turn.get("role", "user")
            fh.write(json.dumps({"type": role, "uuid": turn.get("uuid") or f"u{i}",
                                 "message": {"role": role,
                                             "content": turn.get("content", "")}}) + "\n")


def build_extractor(case: dict) -> Request:
    mod = extractor_module()
    data = case.get("input") or {}
    with tempfile.TemporaryDirectory(prefix="brain-eval-") as tmp:
        path = Path(tmp) / "transcript.jsonl"
        write_transcript(data.get("transcript") or [], path)
        turns = mod.read_new_turns(str(path), str(data.get("last_uuid") or ""))
    if not turns.get("text") or not mod.worth_extracting(turns.get("said", ""),
                                                         turns.get("new_users", 0)):
        return Request(decided={"facts": [], "skipped": "not worth a pass"})
    return Request(prompt="Conversation:\n" + turns["text"],
                   system=mod.EXTRACT_PROMPT)


def shape_extractor(case: dict, req: Request, res: dict) -> dict:
    return {"facts": extractor_module().parse_facts(res.get("text") or "")}


# ------------------------------------------------------------ consolidator

def _inbox_records(items: list, now: float) -> list[dict]:
    out = []
    n = len(items or [])
    for i, item in enumerate(items or []):
        rec = {"source": "assist", "confidence": "high"}
        rec.update({k: v for k, v in item.items() if k != "age_days"})
        if "ts" not in rec:
            # Oldest first, newest last, a minute apart — "newest last" is
            # what the prompt tells the model, so the order is the label.
            age = float(item.get("age_days", 0)) * 86400 + (n - i) * 60
            rec["ts"] = int(now - age)
        out.append(rec)
    return out


def _seed_memory_dir(case: dict, memory_dir: Path) -> None:
    data = dated(case.get("input") or {})
    inbox = memory_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (memory_dir / "memory.md").write_text(str(data.get("memory") or ""),
                                          encoding="utf-8")
    records = _inbox_records(data.get("inbox") or [], time.time())
    (inbox / "0001-eval.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    hyps = data.get("hypotheses") or []
    if hyps:
        (memory_dir / "hypotheses.jsonl").write_text(
            "".join(json.dumps(h) + "\n" for h in hyps), encoding="utf-8")


def _consolidator_env(memory_dir: Path, model: str, claude_cmd: str,
                      max_kb: int, tee_log: str = "") -> dict:
    env = dict(os.environ)
    env.update({
        "BRAIN_MEMORY_DIR": str(memory_dir),
        "BRAIN_SHARE_INBOX": str(memory_dir.parent / "share-inbox"),
        "BRAIN_CLAUDE_BIN": claude_cmd,
        "BRAIN_MEMORY_MODEL": model,
        "BRAIN_MEMORY_MAX_KB": str(max_kb),
        "BRAIN_RUN_SOURCE_LIB": "/nonexistent",
        "BRAIN_STORE_LOCK_LIB": "/nonexistent",
        "BRAIN_CONTEXT_GEN": "/nonexistent",
        "EVALS_TEE_LOG": tee_log,
    })
    return env


def build_consolidator(case: dict) -> Request:
    """The script's own ``build_prompt``, lifted by name and run — the way
    ``tests/test_memory_learning.py`` drives ``refresh_context``. Only the
    no-token check uses this; a real trial runs the whole script."""
    src = CONSOLIDATOR.read_text(encoding="utf-8")
    funcs = []
    # The heredoc inside build_prompt has a `}` alone on a line of its
    # own, so its end is the `PROMPT` terminator followed by the brace.
    for name, end in (("dead_ends_block", r"^\}$"), ("build_prompt", r"^PROMPT\n\}$")):
        match = re.search(rf"^{name}\(\) \{{\n.*?{end}", src, re.S | re.M)
        if not match:
            raise LookupError(f"brain-memory-consolidate.sh no longer defines {name}")
        funcs.append(match.group(0))
    data = dated(case.get("input") or {})
    inbox = "\n".join(json.dumps(r) for r in
                      _inbox_records(data.get("inbox") or [], time.time()))
    harness = ("HYPOTHESES_FILE=/nonexistent\nVOICE_SEPARATOR='-----VOICE-----'\n"
               f"VOICE_MAX_BYTES=2048\nMEMORY_MAX_KB={int(data.get('max_kb') or 32)}\n"
               + "\n".join(funcs) + '\nbuild_prompt "$1" "$2"\n')
    out = subprocess.run(["bash", "-c", harness, "eval", str(data.get("memory") or ""),
                          inbox], capture_output=True, text=True, check=True)
    return Request(prompt=out.stdout)


def run_consolidator(case: dict, model: str, ask) -> Trial:
    """One real ``--once`` pass against a scratch memory directory, with
    ``claude_tee.py`` as its `claude`. The script builds the prompt, reads
    the reply and applies its guards; the output is what it left on disk."""
    del ask  # the script asks; the tee counts
    data = dated(case.get("input") or {})
    max_kb = int(data.get("max_kb") or 32)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="brain-eval-") as tmp:
        memory_dir = Path(tmp) / "memory"
        _seed_memory_dir(case, memory_dir)
        tee_log = Path(tmp) / "tee.jsonl"
        env = _consolidator_env(memory_dir, model, f"{sys.executable} {TEE}",
                                max_kb, str(tee_log))
        try:
            proc = subprocess.run(["bash", str(CONSOLIDATOR), "--once"], env=env,
                                  capture_output=True, text=True, check=False,
                                  timeout=CONSOLIDATE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return Trial(error=f"the pass did not end inside {CONSOLIDATE_TIMEOUT_S}s")
        tokens, models, cli_error = 0, set(), ""
        from .model import models_used, usage_tokens  # noqa: PLC0415
        if tee_log.exists():
            for line in tee_log.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                envelope = row.get("envelope") or {}
                tokens += usage_tokens(envelope)
                models.update(models_used(envelope))
                if row.get("rc") not in (0, None) or envelope.get("is_error"):
                    cli_error = str(envelope.get("result") or f"exit {row.get('rc')}")[:300]
        read = lambda name: (memory_dir / name).read_text(encoding="utf-8") \
            if (memory_dir / name).exists() else ""  # noqa: E731
        output = {"rc": proc.returncode, "memory": read("memory.md"),
                  "voice": read("voice.md"), "memory_before": str(data.get("memory") or ""),
                  "log": proc.stdout[-2000:]}
    trial = Trial(output=output, tokens=tokens, models=sorted(models),
                  seconds=round(time.monotonic() - started, 1))
    if cli_error and not tokens:
        # The CLI never answered (signed out, no such model): that is not
        # the consolidator disagreeing with the case.
        trial.error = cli_error
    return trial


# ------------------------------------------------------------------ reflect

def reflect_candidates(case: dict) -> list[dict]:
    _panel_path()
    import outcomes  # noqa: PLC0415
    data = case.get("input") or {}
    if "candidates" in data:
        return list(data["candidates"])
    scopes = {}
    for scope, pool in (data.get("scopes") or {}).items():
        scopes[scope] = {name: {**outcomes._blank(), **tally}
                         for name, tally in pool.items()}
    return outcomes.candidates(scopes)


def build_reflect(case: dict) -> Request:
    _panel_path()
    import outcomes  # noqa: PLC0415
    cands = reflect_candidates(case)
    req = Request(prompt=outcomes.reflect_prompt(cands), system=outcomes.REFLECT_SYSTEM,
                  schema=outcomes.REFLECT_SCHEMA, extra={"candidates": cands})
    if not cands:
        # The code found no pattern, so the house asks the model nothing.
        req.decided = {"candidates": [], "reply": {"lessons": []}}
    return req


def shape_reflect(case: dict, req: Request, res: dict) -> dict:
    return {"candidates": req.extra["candidates"], "reply": res.get("data")}


# --------------------------------------------------------------- first look

def build_first_look(case: dict) -> Request:
    _panel_path()
    import outcomes  # noqa: PLC0415
    import resident  # noqa: PLC0415
    entry = first_look_grader.entry_for(case)
    return Request(prompt=outcomes.replay_prompt(entry),
                   system=resident.FIRST_LOOK_SYSTEM,
                   schema=resident.FIRST_LOOK_SCHEMA)


def shape_first_look(case: dict, req: Request, res: dict) -> dict:
    return {"reply": res.get("data")}


# ----------------------------------------------------------- Morph learning

DIGEST_DEFAULTS = {"cards": [], "sections": [], "never_used": [], "dead": [],
                   "tells": [], "suggestions": [], "days_with_use": 0,
                   "events": 0, "by_kind": {}, "log": {}}


_MORPH_LOCK = threading.Lock()


@contextlib.contextmanager
def morph_env():
    """Morph's service against a scratch tree (``tests/morph_env.py``). It
    patches ``os.environ`` and ``sys.modules`` for the whole process, so one
    at a time even when the runner has several workers; the model is asked
    outside it."""
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    from morph_env import MorphEnv  # noqa: PLC0415
    with _MORPH_LOCK, MorphEnv() as env:
        yield env


def _morph_inputs(case: dict) -> tuple:
    data = case.get("input") or {}
    digest = {**DIGEST_DEFAULTS, **(data.get("digest") or {})}
    return (digest, str(data.get("dash_text") or ""), list(data.get("lessons") or []),
            dict(data.get("declined") or {}), list(data.get("items") or []))


def build_morph_learning(case: dict) -> Request:
    with morph_env() as env:
        d, text, lessons, declined, items = _morph_inputs(case)
        prompt = env.learning.build_prompt(d, text, lessons, declined, items)
        schema = env.learning.SCHEMA
    return Request(prompt=prompt, system=MORPH_SYSTEM, schema=schema)


def shape_morph_learning(case: dict, req: Request, res: dict) -> dict:
    """The reply, and LEARNED.md after the code merged it on a scratch copy."""
    reply = res.get("data")
    out = {"reply": reply}
    if not isinstance(reply, dict) or not isinstance(reply.get("lessons"), list):
        return out
    with morph_env() as env:
        d, _text, lessons, _declined, _items = _morph_inputs(case)
        env.learning.write_lessons(lessons, commit=False)
        notes = [s.get("note") for s in d.get("suggestions") or [] if s.get("note")]
        if reply["lessons"]:
            env.learning.merge_pass_lessons(reply["lessons"], notes)
        out["merged_lessons"] = env.learning.read_lesson_rows()
    return out


# ---------------------------------------------------------- devloop streams

def build_devloop_streams(case: dict) -> Request:
    _panel_path()
    from devloop import streams  # noqa: PLC0415
    data = case.get("input") or {}
    stream = data.get("stream") or "gaps"
    prompt = streams.analyst_prompt(
        stream, str(data.get("context") or ""), str(data.get("topic") or ""),
        streams.reported_block(data.get("reported") or []),
        streams.rejected_block(data.get("rejected") or []))
    return Request(prompt=prompt, system=streams.analyst_system(stream),
                   schema=streams.reply_schema(stream))


def shape_devloop_streams(case: dict, req: Request, res: dict) -> dict:
    return {"reply": res.get("data")}


# --------------------------------------------------------------- the table

BUILDERS = {
    "extractor": (build_extractor, shape_extractor),
    "consolidator": (build_consolidator, None),
    "reflect": (build_reflect, shape_reflect),
    "first_look": (build_first_look, shape_first_look),
    "morph_learning": (build_morph_learning, shape_morph_learning),
    "devloop_streams": (build_devloop_streams, shape_devloop_streams),
}


def build(case: dict) -> Request:
    return BUILDERS[case["job"]][0](case)


def run(case: dict, model: str, ask) -> Trial:
    """One trial of one case: build, ask, shape. Never raises."""
    if case["job"] == "consolidator":
        try:
            return run_consolidator(case, model, ask)
        except Exception as exc:  # noqa: BLE001
            return Trial(error=f"the pass could not be run: {exc!r}")
    builder, shape = BUILDERS[case["job"]]
    try:
        req = builder(case)
    except Exception as exc:  # noqa: BLE001
        return Trial(error=f"the prompt could not be built: {exc!r}")
    if req.decided is not None:
        return Trial(output=req.decided)
    res = ask(req.prompt, req.system, model, schema=req.schema)
    trial = Trial(tokens=int(res.get("tokens") or 0), models=list(res.get("models") or []),
                  seconds=float(res.get("seconds") or 0))
    if not res.get("ok"):
        trial.error = str(res.get("error") or "the run failed")
        return trial
    try:
        trial.output = shape(case, req, res)
    except Exception as exc:  # noqa: BLE001
        trial.error = f"the answer could not be shaped: {exc!r}"
    return trial
