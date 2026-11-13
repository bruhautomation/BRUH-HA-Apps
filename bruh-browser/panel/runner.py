"""Run ONE errand: the seam.

`run_task(task, config, on_progress, stop)` is the only function the rest of
the panel calls to get an errand done, and it answers with an outcome dict
(`Outcome` below). Today it runs Claude Code in print mode with the Chrome
integration:

    claude --chrome -p --output-format stream-json --verbose
           --model <model> --max-turns <n>
           --append-system-prompt <system_prompt.md>
           --tools "" --allowedTools mcp__claude-in-chrome,StructuredOutput
           --disallowedTools <every built-in, javascript_tool, file uploads>
           --permission-mode dontAsk --settings <run settings with the hook>
           --json-schema <SCHEMA> [--resume <session>]
    (the errand's message, or the person's answer, on stdin)

**If print mode turns out not to work with `--chrome` on a real box** (the
docs neither promise nor rule it out), an interactive-session runner can
replace this function without touching the queue, the routes, the approval
or brAIn: it has to accept the same task dict and return the same outcome.

What it guarantees the caller:

* **Only the browser tools.** `--tools ""` removes the built-in set (checked
  against Claude Code 2.1.323: the 20 `mcp__claude-in-chrome__*` tools are
  still listed with it), the allow-list names the Chrome server and the
  structured-answer tool, `dontAsk` refuses whatever is not on it (print mode
  has nobody to ask), and the deny-list names the built-ins again plus the
  three Chrome tools an errand has no use for and that reach furthest:
  running JavaScript in a signed-in page and uploading files.
* **The spending guard on every call** (`purchase_hook.py`, through
  `--settings`), told by environment whether this errand may buy.
* **The documented failure signs turned into sentences** that name the setup
  step to redo (`diagnose`), and a run that started without its Chrome tools
  stopped at once rather than left to spend its turns.
* **A wall clock and a Stop** that end the whole process group.
* **A pause a person can answer** (`clean_question`): the structured answer
  carries what it needs as a KIND (`sign_in`, `captcha`, `verification`,
  `dialog`, `choice`, `confirm`, `other`), and a resumed run is told either
  that the person did it (`CONTINUE_PROMPT`) or what they answered
  (`answer_prompt`).
* **The extension never waits on a prompt nobody can see**: for this
  add-on's own Chrome the run sets `CLAUDE_CHROME_PERMISSION_MODE` to
  `skip_all_permission_checks` (the mode Claude Code itself sends the
  extension under `bypassPermissions`), and a tool result that says the
  extension is still waiting on its own prompt stops the run with a pause of
  kind `extension` (`EXTENSION_SIGNS`).
* **The browser it drives is the one `browsers.preflight` chose**, pinned
  by device id, and a `list_connected_browsers` answer that shows another
  browser in use, or Claude Code saying several are connected and none is
  chosen, stops the run with a `choice` (`_wrong_browser`).
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

CHROME_PREFIX = "mcp__claude-in-chrome__"
ALLOWED = ("mcp__claude-in-chrome", "StructuredOutput")
DENIED = (
    "Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob",
    "Grep", "LS", "WebFetch", "WebSearch", "Task", "Agent", "TodoWrite",
    "SendMessage", "ListAgents", "ListPeers", "RemoteTrigger",
    "PushNotification", "SendUserMessage", "CronCreate", "CronDelete",
    "CronList", "ScheduleWakeup", "Monitor", "TeamCreate", "TeamDelete",
    f"{CHROME_PREFIX}javascript_tool", f"{CHROME_PREFIX}file_upload",
    f"{CHROME_PREFIX}upload_image",
    # Choosing or pairing a browser is the panel's (browsers.preflight), never
    # the model's: select_browser persists its pick for every later run, and
    # switch_browser broadcasts a Connect prompt to every Chrome on the account.
    f"{CHROME_PREFIX}select_browser", f"{CHROME_PREFIX}switch_browser",
    # Older CLIs: a plan the person approves in the extension's side panel,
    # which a -p run has nobody to approve, and saved shortcuts that run there.
    f"{CHROME_PREFIX}update_plan", f"{CHROME_PREFIX}shortcuts_execute",
    f"{CHROME_PREFIX}shortcuts_list",
    # Asking the person goes through the structured answer, not a dialog.
    "AskUserQuestion",
)
# What Claude Code is never handed: either of these keeps the Chrome
# integration off (the docs: an API key or a setup-token disables it).
STRIPPED_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")

# What a paused errand asks of a person. The first four are done in the
# browser and answered with "I've done it"; a choice or a confirm is answered
# with words; `other` takes either. `extension` is the runner's own (the
# extension waiting on its own prompt), never the model's.
IN_BROWSER = ("sign_in", "captcha", "verification", "dialog")
KINDS = IN_BROWSER + ("choice", "confirm", "other")
PERSON_ONLY = IN_BROWSER + ("extension",)

SCHEMA = {
    "type": "object",
    "required": ["outcome", "report"],
    "properties": {
        "outcome": {"type": "string", "enum": ["done", "needs_you", "failed"]},
        "report": {"type": "string"},
        "needs_you": {"type": "string"},
        "question": {
            "type": "object",
            "required": ["text", "kind"],
            "properties": {
                "text": {"type": "string"},
                "kind": {"type": "string", "enum": list(KINDS)},
                "options": {"type": "array", "items": {"type": "string"},
                            "maxItems": 4},
                "money": {"type": "boolean"},
            },
        },
        "cart": {
            "type": "object",
            "properties": {
                "store": {"type": "string"},
                "items": {"type": "array", "items": {
                    "type": "object",
                    "required": ["name", "quantity"],
                    "properties": {"name": {"type": "string"},
                                   "quantity": {"type": "number"},
                                   "price": {"type": "number"}}}},
                "substitutions": {"type": "array", "items": {"type": "string"}},
                "left_out": {"type": "array", "items": {"type": "string"}},
                "fees": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"},
                                   "amount": {"type": "number"}}}},
                "delivery": {"type": "string"},
                "total": {"type": "number"},
                "currency": {"type": "string"},
                "on_review_page": {"type": "boolean"},
            },
        },
        "order_placed": {"type": "boolean"},
        "order_number": {"type": "string"},
    },
}

CONTINUE_PROMPT = (
    "The person says they have done what you asked in the BRUH Browser tab. "
    "Look at the page again and carry on with the same errand from where you "
    "stopped. The same rules apply.")


def answer_prompt(answer: str) -> str:
    """The person's answer to the question the errand paused on: their words
    are the household's instruction for that point of the errand."""
    return ("The person answered the question you stopped on. Their answer, in "
            "their own words (this is the household speaking, so follow it for "
            "this point of the errand):\n"
            f"<answer>\n{str(answer)[:1000]}\n</answer>\n"
            "Look at the page again and carry on with the same errand from where "
            "you stopped. The same rules apply; an answer never approves a "
            "purchase.")


# The extension waiting on its own prompt (its side panel in the live
# browser), or refusing because nobody answered it. Strings from Claude
# Code 2.1.323's bundle and its error codes.
EXTENSION_SIGNS = (
    "no response to the claude in chrome permission prompt",
    "claude in chrome permission prompt window couldn't be opened",
    "permission_prompt_timed_out", "permission_prompt_unavailable",
    "permission_handler_missing", "permission_denied_user", "plan_rejected_user",
    "site_not_permitted", "user denied permission")
EXTENSION_SENTENCE = (
    "The Claude extension is waiting for someone to allow it to act on this site. "
    "It asks in its own side panel in the live browser, not on this page: click the "
    "Claude icon in Chrome's toolbar (or the puzzle-piece icon, then Claude), answer "
    "Allow, then press I've done it, carry on.")
# Claude Code saying it has several browsers and has not been told which.
MANY_BROWSERS_SIGNS = ("browsers are connected and none is selected",
                       "several browsers are connected")

# The documented ways this goes wrong, as (signs, setup step, sentence). A
# step of 1 means "the extension" (steps 1 and 2); 3 is Claude Code's sign-in.
SIGNS = (
    (("browser extension is not connected", "extension is not connected",
      "extension isn't connected", "no browser is connected",
      "no connected browser", "could not connect to the browser",
      "chrome extension not connected", "the browser chosen for this session could not"), 1,
     "Claude Code could not reach the Claude extension in this Chrome. Check step 1 "
     "(the extension is installed and switched on) and step 2 (it is signed in to "
     "claude.ai with the same Claude account as Claude Code), then press Test."),
    (("the extension may need to be re-authenticated",), 2,
     "The Claude extension in this Chrome is signed out. Redo step 2: open the "
     "Claude side panel in the live browser and sign in to claude.ai with the same "
     "Claude account as Claude Code, then press Test."),
    (("unknown option '--chrome'", 'unknown option "--chrome"'), None,
     "This add-on's Claude Code does not know --chrome. Update BRUH Browser."),
    (("invalid api key", "please run /login", "not logged in", "authentication_error",
      "oauth token has expired", "oauth token is invalid", "login required",
      "not authenticated", "authentication failed"), 3,
     "Claude Code is not signed in, or its sign-in expired. Redo step 3: open the "
     "sign-in window and sign in with /login."),
    (("claude in chrome requires", "chrome integration is not available",
      "claude in chrome is not available", "requires a claude.ai",
      "requires a paid", "not available with api", "chrome integration is disabled"), 3,
     "Claude Code's Chrome integration is off for this sign-in. It needs a paid "
     "Claude plan signed in with /login, not an API key: redo step 3."),
    (("usage limit", "rate limit", "rate_limit_error", "credit balance is too low",
      "out of extra usage"), None,
     "Your Claude plan's usage limit was reached, so the errand stopped. Try again "
     "when it resets."),
)
DIALOG_SIGNS = ("javascript dialog", "dialog is open", "alert dialog", "beforeunload",
                "dialog blocking", "blocked by a dialog")
FATAL_STEPS = (1, 2, 3)


def diagnose(text: str) -> tuple[int | None, str] | None:
    low = str(text or "").lower()
    for signs, step, sentence in SIGNS:
        if any(sign in low for sign in signs):
            return step, sentence
    return None


@dataclass
class RunConfig:
    claude_bin: str = "claude"
    model: str = "sonnet"
    max_turns: int = 80
    timeout_s: int = 1800
    system_prompt: str = ""
    hook: str = ""
    run_dir: Path = Path("/data/run")
    cwd: Path = Path("/data/home/errands")
    env: dict = field(default_factory=dict)


def settings_file(cfg: RunConfig) -> Path:
    """The run's own settings: the spending guard, and the same allow and
    deny lists as the flags, so a CLI that ignored one still meets the other."""
    hook = f"python3 {cfg.hook}"
    doc = {
        "hooks": {
            "PreToolUse": [{"matcher": f"{CHROME_PREFIX}.*", "hooks": [
                {"type": "command", "command": f"{hook} pre", "timeout": 10}]}],
            "PostToolUse": [{"matcher": f"{CHROME_PREFIX}.*", "hooks": [
                {"type": "command", "command": f"{hook} post", "timeout": 10}]}],
        },
        "permissions": {"allow": list(ALLOWED), "deny": list(DENIED)},
        "autoMemoryEnabled": False,
    }
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.run_dir / "settings.json"
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


def command(task: dict, cfg: RunConfig, settings: Path) -> list[str]:
    argv = [cfg.claude_bin, "--chrome", "-p",
            "--output-format", "stream-json", "--verbose",
            "--model", cfg.model, "--max-turns", str(cfg.max_turns),
            "--append-system-prompt", cfg.system_prompt,
            "--tools", "",
            "--allowedTools", ",".join(ALLOWED),
            "--disallowedTools", ",".join(DENIED),
            "--permission-mode", "dontAsk",
            "--settings", str(settings),
            "--json-schema", json.dumps(SCHEMA, separators=(",", ":"))]
    if task.get("resume_session"):
        argv += ["--resume", str(task["resume_session"])]
    return argv


def opening(task: dict) -> str:
    """What the run is told on stdin: the errand, the person's answer, or
    that they did what it asked in the browser."""
    if not task.get("resume_session"):
        return task["message"]
    if str(task.get("reply") or "").strip():
        return answer_prompt(task["reply"])
    return CONTINUE_PROMPT


def environment(task: dict, cfg: RunConfig, state_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}
    env.update(cfg.env)
    env["BROWSER_PURCHASE_APPROVED"] = "1" if task.get("purchase_approved") else "0"
    env["BROWSER_TASK_STATE"] = str(state_path)
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    # Which browser: the device browsers.preflight chose (also written into
    # ~/.claude.json, which the CLI reads first).
    env.pop("CLAUDE_CHROME_PAIRED_DEVICE_ID", None)
    if task.get("browser_device"):
        env["CLAUDE_CHROME_PAIRED_DEVICE_ID"] = str(task["browser_device"])
    # The extension's own ask-before-acting: off in this add-on's Chrome,
    # where nobody can answer it during a -p run; left as the extension has
    # it on another computer, where its person can.
    if task.get("browser_own", True):
        env["CLAUDE_CHROME_PERMISSION_MODE"] = "skip_all_permission_checks"
    else:
        env.pop("CLAUDE_CHROME_PERMISSION_MODE", None)
    return env


def describe(name: str, args) -> str:
    """A tool call as a progress line a person can read."""
    short = name[len(CHROME_PREFIX):] if name.startswith(CHROME_PREFIX) else name
    args = args if isinstance(args, dict) else {}
    if short == "navigate":
        return f"Opening {str(args.get('url') or 'a page')[:90]}"
    if short == "computer":
        action = str(args.get("action") or "")
        return {"left_click": "Clicking", "right_click": "Clicking",
                "double_click": "Clicking", "triple_click": "Clicking",
                "type": "Typing", "key": "Pressing a key",
                "screenshot": "Looking at the page", "scroll": "Scrolling",
                "wait": "Waiting for the page"}.get(action, "Using the page")
    if short == "find":
        return f"Looking for {str(args.get('query') or 'something')[:70]}"
    if short == "form_input":
        return "Filling in a field"
    if short in ("read_page", "get_page_text"):
        return "Reading the page"
    if short in ("tabs_create_mcp", "tabs_context_mcp"):
        return "Getting a tab ready"
    if short == "list_connected_browsers":
        return "Checking which browser it is using"
    if short == "browser_batch":
        steps = args.get("actions") or args.get("steps") or []
        return f"Doing {len(steps) if isinstance(steps, list) else 'several'} steps"
    if short == "StructuredOutput":
        return "Writing the report"
    return short.replace("_", " ").capitalize()


def _texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    out = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if isinstance(block.get("text"), str):
                    out.append(block["text"])
                elif "content" in block:
                    out.extend(_texts(block["content"]))
    return out


def _number(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def clean_cart(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    items = []
    for row in raw.get("items") or []:
        if not isinstance(row, dict) or not str(row.get("name") or "").strip():
            continue
        items.append({"name": str(row["name"]).strip()[:200],
                      "quantity": _number(row.get("quantity")) or 1,
                      "price": _number(row.get("price"))})
    fees = [{"name": str(f.get("name") or "fee")[:80], "amount": _number(f.get("amount"))}
            for f in raw.get("fees") or [] if isinstance(f, dict)]
    return {"store": str(raw.get("store") or "")[:120],
            "items": items[:200],
            "substitutions": [str(s)[:200] for s in raw.get("substitutions") or []][:50],
            "left_out": [str(s)[:200] for s in raw.get("left_out") or []][:50],
            "fees": fees[:20],
            "delivery": str(raw.get("delivery") or "")[:200],
            "total": _number(raw.get("total")),
            "currency": str(raw.get("currency") or "")[:8],
            "on_review_page": bool(raw.get("on_review_page"))}


def clean_question(raw, fallback: str = "") -> dict:
    """The question a paused errand asks, in a shape the page and brAIn can
    always offer an answer to: a kind it knows, a sentence, and for a choice
    2-4 short options (a confirm is Yes/No)."""
    raw = raw if isinstance(raw, dict) else {}
    text = " ".join(str(raw.get("text") or fallback or "").split())[:600]
    kind = raw.get("kind") if raw.get("kind") in KINDS else "other"
    options = []
    for opt in raw.get("options") or []:
        words = " ".join(str(opt or "").split())[:80]
        if words and words not in options:
            options.append(words)
    if kind == "confirm":
        options = options[:2] if len(options) == 2 else ["Yes", "No"]
    elif kind == "choice":
        options = options[:4]
        if len(options) < 2:
            kind = "other"
            options = []
    else:
        options = []
    return {"text": text or "It needs a person to look at the live browser.",
            "kind": kind, "options": options, "money": bool(raw.get("money"))}


def _browsers_in(text: str) -> list[dict] | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return [r for r in data if isinstance(r, dict) and r.get("deviceId")]


def _wrong_browser(text: str, expect: str | None) -> str | None:
    """Why this tool result says the run is on the wrong browser, or None."""
    low = text.lower()
    if any(sign in low for sign in MANY_BROWSERS_SIGNS) and "is the one" not in low:
        return "Claude Code found several browsers on this Claude account and none chosen."
    if not expect:
        return None
    rows = _browsers_in(text.strip())
    if rows is None:
        return None
    in_use = [r for r in rows if r.get("inUse")]
    if in_use and in_use[0].get("deviceId") != expect:
        name = str(in_use[0].get("name") or "another browser")[:60]
        return f"Claude Code was about to use {name}, not the browser this errand was meant for."
    return None


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        proc.wait(timeout=10)


def run_task(task: dict, cfg: RunConfig, on_progress=None,
             stop: threading.Event | None = None) -> dict:
    """Run one errand to its end. Never raises; always returns an outcome:
    {state, answer, needs_you, error, setup_step, cart, order_placed,
     order_number, session_id, turns, cost_usd, steps}."""
    out = _run(task, cfg, on_progress, stop)
    if out["state"] != "needs_you":
        # The guard's notes on this errand's pages; a continued errand keeps them.
        try:
            (cfg.run_dir / f"task-{task.get('id')}.json").unlink()
        except OSError:
            pass
    return out


def _run(task: dict, cfg: RunConfig, on_progress, stop) -> dict:
    stop = stop or threading.Event()
    say = on_progress or (lambda _line: None)
    out = {"state": "failed", "answer": "", "needs_you": "", "question": None, "error": "",
           "setup_step": None, "cart": None, "order_placed": False,
           "order_number": "", "session_id": task.get("resume_session") or "",
           "turns": None, "cost_usd": None, "steps": 0}
    try:
        settings = settings_file(cfg)
        cfg.cwd.mkdir(parents=True, exist_ok=True)
        state_path = cfg.run_dir / f"task-{task['id']}.json"
        prompt = opening(task)
        proc = subprocess.Popen(command(task, cfg, settings), cwd=cfg.cwd,
                                env=environment(task, cfg, state_path),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
    except (OSError, KeyError) as exc:
        out["error"] = f"Claude Code could not be started: {exc}"
        return out
    try:
        proc.stdin.write(prompt.encode())
        proc.stdin.close()
    except OSError:
        pass  # it died at once; its own words are on stderr

    lines: queue.Queue = queue.Queue()
    err_tail: list[str] = []

    def pump_out():
        for raw in iter(proc.stdout.readline, b""):
            lines.put(raw)
        lines.put(None)

    def pump_err():
        for raw in iter(proc.stderr.readline, b""):
            err_tail.append(raw.decode(errors="replace").rstrip()[:400])
            del err_tail[:-40]

    threading.Thread(target=pump_out, daemon=True).start()
    threading.Thread(target=pump_err, daemon=True).start()

    deadline = time.monotonic() + cfg.timeout_s
    result = None
    fatal = None
    dialog = False
    blocked = ""      # the extension is waiting on its own prompt
    wrong = ""        # the run is on a browser nobody chose
    ended_by = ""
    browser_calls: dict[str, str] = {}
    while True:
        if stop.is_set():
            ended_by = "stop"
            break
        if time.monotonic() > deadline:
            ended_by = "timeout"
            break
        try:
            raw = lines.get(timeout=0.5)
        except queue.Empty:
            continue
        if raw is None:
            break
        try:
            event = json.loads(raw.decode(errors="replace"))
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            out["session_id"] = str(event.get("session_id") or out["session_id"])
            tools = [str(t) for t in event.get("tools") or []]
            if not any(t.startswith(CHROME_PREFIX) for t in tools):
                servers = ", ".join(f"{s.get('name')}: {s.get('status')}"
                                    for s in event.get("mcp_servers") or []
                                    if isinstance(s, dict)) or "none"
                fatal = (3, "Claude Code started without its Chrome tools, so the "
                            "Chrome integration is off (MCP servers: " + servers +
                            "). It needs a paid Claude plan signed in with /login, "
                            "not an API key: redo step 3, then press Test.")
                ended_by = "fatal"
                break
            say("Starting")
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    out["steps"] += 1
                    browser_calls[str(block.get("id") or "")] = str(block.get("name") or "")
                    say(describe(str(block.get("name") or ""), block.get("input")))
                elif block.get("type") == "text" and str(block.get("text") or "").strip():
                    say(str(block["text"]).strip().splitlines()[0][:160])
        elif kind == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                text = " ".join(_texts(block.get("content")))
                low = text.lower()
                if any(sign in low for sign in DIALOG_SIGNS):
                    dialog = True
                if any(sign in low for sign in EXTENSION_SIGNS):
                    blocked = EXTENSION_SENTENCE
                    ended_by = "blocked"
                    break
                called = browser_calls.get(str(block.get("tool_use_id") or ""), "")
                if called.endswith("list_connected_browsers") or any(
                        sign in low for sign in MANY_BROWSERS_SIGNS):
                    wrong = _wrong_browser(text, task.get("browser_device")) or ""
                    if wrong:
                        ended_by = "wrong_browser"
                        break
                found = diagnose(text) if block.get("is_error") else None
                if found and found[0] in FATAL_STEPS:
                    fatal = found
                    ended_by = "fatal"
                    break
            if ended_by in ("fatal", "blocked", "wrong_browser"):
                break
        elif kind == "result":
            result = event
    if proc.poll() is None:
        if ended_by:
            _kill(proc)
        else:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                _kill(proc)
    time.sleep(0.05)  # let the stderr pump catch the last lines

    if ended_by == "stop":
        out.update(state="stopped", error="Stopped.")
        return out
    if ended_by == "timeout":
        out["error"] = (f"The errand took longer than {cfg.timeout_s // 60} minutes "
                        "(the task_timeout_minutes option) and was stopped.")
        return out
    if fatal:
        out.update(setup_step=fatal[0], error=fatal[1])
        return out
    if blocked:
        out.update(state="needs_you", needs_you=blocked, setup_step=4,
                   question={"text": blocked, "kind": "extension", "options": [],
                             "money": False})
        return out
    if wrong:
        out.update(state="needs_you", session_id="", needs_you=wrong,
                   question={"text": wrong + " Which browser should this errand use?",
                             "kind": "choice", "options": [], "money": False,
                             "pick_browser": True})
        return out
    if result is None:
        tail = " ".join(err_tail[-6:])
        found = diagnose(tail)
        if found:
            out.update(setup_step=found[0], error=found[1])
        else:
            out["error"] = (f"Claude Code ended (exit {proc.returncode}) without an "
                            f"answer. Its last words: {tail[-600:] or 'none'}")
        return out

    out["session_id"] = str(result.get("session_id") or out["session_id"])
    out["turns"] = result.get("num_turns")
    out["cost_usd"] = result.get("total_cost_usd")
    subtype = str(result.get("subtype") or "")
    text = str(result.get("result") or "")
    if subtype == "error_max_turns":
        out["error"] = (f"The errand used all {cfg.max_turns} steps (the max_turns "
                        "option) before it finished. It can be continued, or asked "
                        "again with less to do.")
        out["state"] = "needs_you"
        out["needs_you"] = ("It ran out of steps before it finished. Let it carry on, "
                            "or stop it here.")
        out["question"] = {"text": out["needs_you"], "kind": "confirm",
                           "options": ["Carry on", "Stop here"], "money": False,
                           "ran_out": True}
        return out
    if result.get("is_error") or subtype not in ("success", ""):
        found = diagnose(text + " " + " ".join(err_tail[-6:]))
        if found:
            out.update(setup_step=found[0], error=found[1])
        else:
            out["error"] = f"The errand failed: {(text or subtype)[:600]}"
        return out
    data = result.get("structured_output")
    if isinstance(data, dict):
        outcome = data.get("outcome") if data.get("outcome") in (
            "done", "needs_you", "failed") else "done"
        out["state"] = outcome
        out["answer"] = str(data.get("report") or text)[:4000]
        out["needs_you"] = str(data.get("needs_you") or "")[:1000]
        if outcome == "needs_you":
            out["question"] = clean_question(data.get("question"),
                                             out["needs_you"] or out["answer"])
            out["needs_you"] = out["question"]["text"]
        out["cart"] = clean_cart(data.get("cart"))
        out["order_placed"] = bool(data.get("order_placed"))
        out["order_number"] = str(data.get("order_number") or "")[:80]
        if outcome == "failed":
            out["error"] = out["answer"][:1000] or "The errand could not be done."
        if outcome == "needs_you" and not out["needs_you"]:
            out["needs_you"] = out["answer"][:1000]
    else:
        # A CLI that ran without the structured answer: the prose is the
        # report, and there is no cart a purchase could be approved against.
        out["state"] = "done"
        out["answer"] = text[:4000]
    if dialog and out["state"] != "done" and not out["needs_you"]:
        out["state"] = "needs_you"
        out["needs_you"] = ("A dialog on the page is blocking the browser. Close it "
                            "in the live browser below, then press I've done it, carry on.")
        out["question"] = {"text": out["needs_you"], "kind": "dialog", "options": [],
                           "money": False}
    return out
