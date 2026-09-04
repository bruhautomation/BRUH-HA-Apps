#!/usr/bin/env python3
"""Boot the real brAIn panel against a seeded demo home, for screenshots.

The docs on bruhautomation.com show the actual product, not mockups, and
this is how. Everything the panel reads is env-var driven, so we point every
path at a scratch directory, fill it with a plausible house, and run the
real `server.py`. No Claude process is ever spawned — engine.run_claude and
run_agent are stubbed — so this is safe to run anywhere and needs no
credential.

    python3 tests/manual/demo_panel.py /tmp/brain-demo    # serves :8099
    node tests/manual/shoot-panel.mjs                      # writes the PNGs

The house lives in demo_home.py. Every number in it is meant to survive a
reader checking it: the kWh add up, the percentages divide, and the tool
calls in the chat transcript use the argument names the MCP server actually
takes. A screenshot with arithmetic that does not work is worse than no
screenshot, because the whole pitch is that brAIn's numbers are real.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent / "brain" / "panel"
DEMO = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/brain-demo")
PORT = os.environ.get("DEMO_PORT", "8099")

DEMO.mkdir(parents=True, exist_ok=True)
for sub in ("insights", "memory", "memory/inbox", "findings-inbox", "secrets",
            "study_requests", "www", "shared"):
    (DEMO / sub).mkdir(parents=True, exist_ok=True)

env = {
    "BRAIN_DIR": str(DEMO / "insights"),
    "BRAIN_SETTINGS_FILE": str(DEMO / "settings.json"),
    "BRAIN_FINDINGS_FILE": str(DEMO / "findings.json"),
    "BRAIN_FINDINGS_INBOX": str(DEMO / "findings-inbox"),
    "BRAIN_FINDINGS_SETTLED": str(DEMO / "findings-settled.json"),
    "BRAIN_KNOWLEDGE_FILE": str(DEMO / "knowledge.json"),
    "BRAIN_MEMORY_DIR": str(DEMO / "memory"),
    "BRAIN_MEMORY_FILE": str(DEMO / "memory" / "memory.md"),
    "BRAIN_MEMORY_INBOX": str(DEMO / "memory" / "inbox"),
    "BRAIN_MEMORY_MARKER": str(DEMO / "memory" / ".last_consolidated"),
    "BRAIN_HYPOTHESES_FILE": str(DEMO / "memory" / "hypotheses.jsonl"),
    "BRAIN_ONBOARDING_STATE": str(DEMO / "onboarding.json"),
    "BRAIN_STUDY_REQUESTS": str(DEMO / "study_requests"),
    "BRAIN_PROMPTS_FILE": str(DEMO / "prompts.json"),
    "BRAIN_FEEDBACK_FILE": str(DEMO / "feedback.json"),
    "BRAIN_CARD_TAGS_FILE": str(DEMO / "card_tags.json"),
    "BRAIN_USAGE_FILE": str(DEMO / "usage.json"),
    "BRAIN_USAGE_LIMITS": str(DEMO / "usage_limits.json"),
    "BRAIN_SECRETS": str(DEMO / "secrets"),
    "BRAIN_SHARED_AUTH": str(DEMO / "shared" / "auth.json"),
    "BRAIN_SHARED_DIR": str(DEMO / "shared"),
    "BRAIN_HOME": str(DEMO / "home"),
    "BRAIN_CHAT_TRANSCRIPT": str(DEMO / "chat_transcript.json"),
    "BRAIN_CHAT_TRANSCRIPT_DIR": str(DEMO / "chat"),
    "BRAIN_CHAT_WORKDIR": str(DEMO / "config"),
    "BRAIN_CONTEXT_FILE": str(DEMO / "CLAUDE.md"),
    "BRAIN_ENABLE_TERMINAL": "true",
    "BIND_PORT": PORT,
    "SUPERVISOR_TOKEN": "demo",
}
os.environ.update(env)
sys.path.insert(0, str(ROOT))

import engine            # noqa: E402
import settings_store    # noqa: E402
import findings_store    # noqa: E402
import knowledge_store   # noqa: E402
import hypotheses        # noqa: E402
import usage_store       # noqa: E402

# Nothing here may reach a real Claude CLI.
engine.run_claude = lambda *a, **k: {"ok": True, "text": "OK", "error": "", "meta": {}}
engine.run_agent = lambda *a, **k: {"ok": True, "text": "{}", "error": "", "meta": {}}
engine.save_auth("sk-ant-oat01-" + "d" * 40)

settings_store.save({
    "onboarded": True,
    "auto_enabled": True,
    "plan": "max5",
    "budget_percent": 80,
    "refresh_hours": 12,
    "terminal_ui": "chat",
})
Path(env["BRAIN_ONBOARDING_STATE"]).write_text(json.dumps({
    "state": "done", "studied_at": "2026-07-29T09:12:00",
}), encoding="utf-8")

# --- usage: a believable mid-week position -------------------------------
import datetime  # noqa: E402


def iso_in(hours):
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=hours)).isoformat()


Path(env["BRAIN_USAGE_LIMITS"]).write_text(json.dumps({
    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "five_hour": {"utilization": 19, "resets_at": iso_in(3.5)},
    "seven_day": {"utilization": 46, "resets_at": iso_in(74)},
}), encoding="utf-8")

# Only the cards this home actually kept — a fresh install ships none, and
# every card below has a generated insight behind it.
Path(env["BRAIN_PROMPTS_FILE"]).write_text(json.dumps({"categories": {
    cid: {"hidden": True} for cid in
    ("overview", "climate", "lighting", "security", "media", "automations")
}}), encoding="utf-8")


import demo_home as demo  # noqa: E402

for c in demo.CARDS:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S",
                          time.localtime(time.time() - c["minutes_ago"] * 60))
    rec = {k: v for k, v in c.items() if k != "minutes_ago"}
    rec["generated_at"] = stamp
    # A real card's cost, so the foot renders the tokens span and its
    # tooltip — the measurement scripts can only check what is on screen.
    rec["meta"] = {"duration_ms": 31000,
                   "cost": {"input": 33_100, "output": 8_150,
                            "cached": 0, "total": 41_250}}
    (DEMO / "insights" / f"{c['id']}.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")

    # Book each demo card's cost against the run ledger too, so the usage
    # pill's popover has a spend breakdown to itemize. A demo panel whose
    # every card cost 41k and whose session reads "spent by nobody" is a
    # screenshot of a bug that isn't there.
    usage_store.record_run(41_250, c["id"],
                           now=time.time() - c["minutes_ago"] * 60)

findings_store.add_many(demo.FINDINGS)

(DEMO / "memory" / "memory.md").write_text(demo.MEMORY_MD, encoding="utf-8")
(DEMO / "memory" / "inbox" / "1722334455.jsonl").write_text(
    "\n".join(json.dumps({"text": t, "ts": int(time.time()) - 600 * (i + 1),
                          "source": "study"})
              for i, t in enumerate(demo.PENDING_FACTS)) + "\n", encoding="utf-8")

for text, topic in demo.HYPOTHESES:
    hypotheses.propose(text, topic=topic)

# The ledger and the inbox describe the same three discoveries, because that
# is what an unconsolidated pass actually leaves behind.
for fact in demo.PENDING_FACTS:
    knowledge_store.add_fact(fact, source="study")

Path(env["BRAIN_CHAT_TRANSCRIPT"]).write_text(json.dumps({
    "session_id": "demo-session", "events": demo.chat_events()},
    ensure_ascii=False), encoding="utf-8")

print(f"seeded {DEMO}", file=sys.stderr)

import server  # noqa: E402
from aiohttp import web  # noqa: E402

web.run_app(server.make_app(), host="127.0.0.1", port=int(PORT), print=None)
