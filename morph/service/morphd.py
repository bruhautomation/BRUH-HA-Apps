#!/usr/bin/env python3
"""Morph's service: the half of Morph that owns the files.

One asyncio process, five jobs:

* **requests** — the integration drops a JSON file in
  ``/config/.morph/requests`` for anything that WRITES (a save from Edit,
  Undo, a Tell, a setting, an answer to a suggestion); this answers in
  ``responses``. Reads never come here: the integration reads the mirrors
  in ``/config/.morph`` directly, so opening the dashboard is a file read.
* **the watcher** — commits any change nobody announced (brAIn editing in a
  chat, somebody with a text editor) and republishes the mirror whenever
  the dashboard's text moves, which is what makes a change appear live.
* **learning** — loop one in `learning.py`, on its own schedule.
* **devloop** — loop two in `devloop.py`: the outbox brAIn reads.
* **health** — a loopback-only ``/api/health`` that run.sh polls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brain  # noqa: E402
import devloop  # noqa: E402
import generator  # noqa: E402
import gitrepo  # noqa: E402
import ha  # noqa: E402
import learning  # noqa: E402
import morphcode  # noqa: E402
import paths  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
import tell  # noqa: E402

log = logging.getLogger("morph")

VERSION = os.environ.get("ADDON_VERSION", "dev")
REDO_PATH = "Morph's own code"
REQUEST_POLL_S = 0.25
WATCH_S = 2.0
TICK_S = 60.0
MAX_REQUEST_AGE_S = 600

STATE: dict = {"bootstrapped": False, "last_revision": "", "generate_note": ""}

# One writer at a time in /config/morph: a save and the watcher's
# "edited outside Morph" commit must never interleave, or a person's save
# is committed under the wrong author and its own commit finds nothing.
LOCK = asyncio.Lock()
READ_ONLY_KINDS = ("history", "tell", "tell_answer", "learn_now", "tell_issue", "report", "report_withdraw")


# ------------------------------------------------------------- bootstrap

def install_docs() -> None:
    """AGENTS.md is Morph's to keep current (it describes the code that
    reads the dashboard), so it is replaced when the release changes;
    CLAUDE.md only points at it; LEARNED.md is the household's and is
    created once and never overwritten here."""
    paths.MORPH_DIR.mkdir(parents=True, exist_ok=True)
    paths.CARDS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("AGENTS.md", "CLAUDE.md"):
        src = paths.DEFAULTS / name
        dst = paths.MORPH_DIR / name
        if not src.exists():
            continue
        new = src.read_text(encoding="utf-8").replace("{{VERSION}}", VERSION)
        try:
            old = dst.read_text(encoding="utf-8")
        except OSError:
            old = ""
        if old != new:
            paths.write_text(dst, new)
    readme = paths.CARDS_DIR / "README.md"
    if not readme.exists() and (paths.DEFAULTS / "cards-README.md").exists():
        shutil.copyfile(paths.DEFAULTS / "cards-README.md", readme)
    if not paths.LEARNED.exists():
        learning.write_lessons([], commit=False)


async def bootstrap() -> None:
    await asyncio.to_thread(gitrepo.ensure)
    await asyncio.to_thread(install_docs)
    if not paths.DASHBOARD.exists():
        house = await ha.house()
        if house is None:
            STATE["generate_note"] = ("Home Assistant did not answer, so the first dashboard is "
                                      "empty. Morph will try again in a minute.")
            await asyncio.to_thread(store.write, store.empty())
            STATE["retry_generate"] = True
        else:
            dash = generator.build(house)
            await asyncio.to_thread(store.write, dash)
            STATE["generate_note"] = ""
    await asyncio.to_thread(gitrepo.commit, f"Morph {VERSION}", "morph")
    await asyncio.to_thread(publish)
    STATE["bootstrapped"] = True


async def retry_generate() -> None:
    """The first dashboard was written empty because Core was not up yet.
    Fill it once Core answers — but only while nobody has put anything in
    it, because then it is somebody's dashboard."""
    dash, _, _ = await asyncio.to_thread(store.read)
    if dash.get("floors"):
        STATE.pop("retry_generate", None)
        return
    house = await ha.house()
    if house is None:
        return
    await asyncio.to_thread(store.write, generator.build(house))
    await asyncio.to_thread(gitrepo.commit, "Built the first dashboard from the house", "morph")
    STATE.pop("retry_generate", None)
    STATE["generate_note"] = ""


# ---------------------------------------------------------------- mirrors

def publish() -> dict:
    mirror = store.publish(gitrepo.head())
    STATE["last_revision"] = mirror["revision"]
    publish_state()
    return mirror


tell.ON_PUBLISH = publish


def publish_state() -> None:
    s = settings.load()
    paths.write_json(paths.STATE, {
        "version": VERSION,
        "at": time.time(),
        "head": gitrepo.head(),
        "settings": s,
        "brain": brain.status(),
        "learning": {**learning.state(), "scorecard": learning.scorecard(),
                     "lessons": learning.read_lessons()},
        "suggestions": learning.listing(),
        # What brAIn is doing for Morph right now, so a tell that is still
        # running is visible after its box was closed or the page reloaded.
        "activity": tell.activity(),
        "devloop": devloop.status(),
        # Morph's own files this house has changed, and whether each is in
        # use (morphcode.py); code.json is what the integration serves from.
        "code": morphcode.publish(VERSION),
        "note": STATE.get("generate_note", ""),
    })


# --------------------------------------------------------------- requests

async def handle(kind: str, p: dict) -> dict:
    if kind == "save":
        _, _, text = await asyncio.to_thread(store.read)
        base = str(p.get("base") or "")
        if base and base != store.revision(text):
            return {"ok": False, "conflict": True,
                    "error": "The dashboard changed while you were editing (brAIn, probably). "
                             "It has been reloaded; make the change again."}
        await asyncio.to_thread(gitrepo.commit_pending)
        await asyncio.to_thread(store.write, p.get("dashboard") or {})
        sha = await asyncio.to_thread(gitrepo.commit, str(p.get("message") or "Edited the dashboard"),
                                      p.get("who") if p.get("who") in ("person", "learning") else "person")
        await asyncio.to_thread(publish)
        return {"ok": True, "commit": sha, "revision": STATE["last_revision"]}
    if kind == "save_yaml":
        text = str(p.get("text") or "")
        _, problems = store.load_text(text)
        if problems and any("could not be read" in x for x in problems):
            return {"ok": False, "error": problems[0]}
        await asyncio.to_thread(gitrepo.commit_pending)
        await asyncio.to_thread(paths.write_text, paths.DASHBOARD, text)
        sha = await asyncio.to_thread(gitrepo.commit, "Edited dashboard.yaml", "person")
        await asyncio.to_thread(publish)
        return {"ok": True, "commit": sha, "problems": problems}
    if kind in ("undo_commit", "restore"):
        fn = gitrepo.revert if kind == "undo_commit" else gitrepo.restore
        ok, detail = await asyncio.to_thread(fn, str(p.get("sha") or ""))
        await asyncio.to_thread(publish)
        return {"ok": ok, "commit": detail} if ok else {"ok": False, "error": detail}
    if kind == "history":
        return {"ok": True, "log": await asyncio.to_thread(gitrepo.log, int(p.get("limit") or 80))}
    if kind == "tell":
        # No scope off the wire: a request from the panel is a dashboard
        # request, and its words decide whether it may reach the house.
        st = tell.start(p.get("target") or {}, str(p.get("text") or ""), str(p.get("previous") or ""),
                        shot=str(p.get("shot") or ""), view=p.get("view"))
        await asyncio.to_thread(publish_state)
        return {"ok": "error" not in st, **st}
    if kind == "tell_answer":
        st = tell.answer_question(str(p.get("id") or ""), p.get("choice"))
        await asyncio.to_thread(publish_state)
        return {"ok": "error" not in st, **st}
    if kind == "tell_issue":
        out = await asyncio.to_thread(tell.answer_issue, str(p.get("id") or ""), str(p.get("verb") or ""))
        await asyncio.to_thread(devloop.publish, VERSION)
        await asyncio.to_thread(publish_state)
        return out
    if kind == "report":
        context = f"Morph {VERSION} · dashboard at {gitrepo.head() or 'no commit yet'}"
        out = await asyncio.to_thread(devloop.note_request, str(p.get("text") or ""),
                                      bool(p.get("ui")), context)
        await asyncio.to_thread(devloop.publish, VERSION)
        await asyncio.to_thread(publish_state)
        return out
    if kind == "report_withdraw":
        out = await asyncio.to_thread(devloop.withdraw, str(p.get("fp") or ""))
        await asyncio.to_thread(devloop.publish, VERSION)
        await asyncio.to_thread(publish_state)
        return out
    if kind == "tell_undo":
        out = tell.undo(str(p.get("id") or ""))
        await asyncio.to_thread(publish)
        return out
    if kind == "settings":
        s = await asyncio.to_thread(settings.update, p.get("patch") or {})
        await asyncio.to_thread(publish_state)
        return {"ok": True, "settings": s}
    if kind == "suggestion":
        verb = str(p.get("verb") or "")
        sid = str(p.get("id") or "")
        item = next((it for it in learning.all_items() if it.get("id") == sid), None)
        # A change to Morph's own code is made here like any other (brAIn
        # changes this house's copy of Morph, and the Tell then asks whether
        # to send it on); "send" alone files it without making it.
        if verb == "do":
            if not item:
                return {"ok": False, "error": "That suggestion is gone."}
            target = {"kind": "card" if item.get("card") else "section" if item.get("section") else "dashboard",
                      "id": item.get("card") or item.get("section") or "",
                      "label": item["title"], "path": "A suggestion Morph made"}
            st = tell.start(target, item["change"])
            if "error" in st:
                return {"ok": False, "error": st["error"]}
            await asyncio.to_thread(learning.mark_doing, sid, st["id"])
            await asyncio.to_thread(publish_state)
            return {"ok": True, "tell": st["id"]}
        out = await asyncio.to_thread(learning.decide, sid, verb, str(p.get("note") or ""))
        if verb == "send":
            await asyncio.to_thread(devloop.publish, VERSION)
        await asyncio.to_thread(publish_state)
        return out
    if kind == "learn_now":
        if learning.state().get("running"):
            return {"ok": False, "error": "A learning pass is already running."}
        asyncio.get_running_loop().create_task(_learn(pressed=True))
        return {"ok": True}
    if kind == "regenerate":
        house = await ha.house()
        if house is None:
            return {"ok": False, "error": "Home Assistant did not answer, so nothing was rebuilt."}
        await asyncio.to_thread(gitrepo.commit_pending)
        await asyncio.to_thread(store.write, generator.build(house))
        sha = await asyncio.to_thread(gitrepo.commit, "Rebuilt the dashboard from the house", "person")
        await asyncio.to_thread(publish)
        return {"ok": True, "commit": sha}
    if kind == "code_reset":
        name = str(p.get("name") or "")
        await asyncio.to_thread(gitrepo.commit_pending)
        ok, err = await asyncio.to_thread(morphcode.reset, name)
        if not ok:
            return {"ok": False, "error": err}
        sha = await asyncio.to_thread(gitrepo.commit, f"Put back Morph's own {name}", "person")
        await asyncio.to_thread(publish_state)
        return {"ok": True, "commit": sha}
    if kind == "code_redo":
        name = str(p.get("name") or "")
        # A second press while brAIn is still at it shows the same request
        # rather than starting another one on the same file.
        for a in tell.activity():
            if a.get("path") == REDO_PATH and a.get("label") == name:
                return {"ok": True, "already": True, **(tell.read_state(a["id"]) or {"id": a["id"]})}
        if not any(r["name"] == name and r["status"] == "paused" for r in morphcode.status()):
            return {"ok": False, "error": "That change is not paused."}
        history = [c["message"] for c in await asyncio.to_thread(gitrepo.log, 12, f"frontend/{name}")]
        st = tell.start({"kind": "code", "id": name, "label": name, "path": REDO_PATH},
                        morphcode.redo_words(name, VERSION, history))
        await asyncio.to_thread(publish_state)
        return {"ok": "error" not in st, **st}
    if kind == "lessons":
        await asyncio.to_thread(learning.write_lessons, [str(x) for x in (p.get("lessons") or [])])
        await asyncio.to_thread(publish_state)
        return {"ok": True}
    return {"ok": False, "error": f"Unknown request {kind!r}"}


async def requests_loop() -> None:
    paths.REQUESTS.mkdir(parents=True, exist_ok=True)
    paths.RESPONSES.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            for f in sorted(paths.REQUESTS.glob("*.json")):
                await _one(f)
        except Exception:  # noqa: BLE001 — the loop must outlive one bad file
            log.exception("request loop")
        await asyncio.sleep(REQUEST_POLL_S)


async def _one(f: Path) -> None:
    try:
        req = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        if time.time() - f.stat().st_mtime > 5:
            f.unlink(missing_ok=True)
        return
    f.unlink(missing_ok=True)
    rid = str(req.get("id") or "")
    if not rid.isalnum() or len(rid) > 64:
        return
    if time.time() - float(req.get("ts") or time.time()) > MAX_REQUEST_AGE_S:
        return
    kind = str(req.get("kind") or "")
    try:
        if kind in READ_ONLY_KINDS:
            out = await handle(kind, req.get("payload") or {})
        else:
            async with LOCK:
                out = await handle(kind, req.get("payload") or {})
    except Exception as exc:  # noqa: BLE001
        log.exception("request %s failed", req.get("kind"))
        out = {"ok": False, "error": f"Morph could not do that: {exc}"}
    paths.write_json(paths.RESPONSES / f"{rid}.json", out)


# --------------------------------------------------------- watcher, ticks

async def watch_loop() -> None:
    last_state = 0.0
    while True:
        try:
            if not tell._RUNNING and not LOCK.locked():
                async with LOCK:
                    sha = await asyncio.to_thread(gitrepo.commit_pending)
                if sha:
                    log.info("Committed a change made outside Morph (%s)", sha)
            text = ""
            try:
                text = paths.DASHBOARD.read_text(encoding="utf-8")
            except OSError:
                pass  # a missing file publishes as an empty dashboard below
            mods = (sorted((f.name, int(f.stat().st_mtime)) for f in paths.CARDS_DIR.glob("*.js"))
                    if paths.CARDS_DIR.is_dir() else []) \
                + [("frontend/" + f.name, int(f.stat().st_mtime)) for f in morphcode.copies()]
            if store.revision(text) != STATE["last_revision"] or mods != STATE.get("modules"):
                STATE["modules"] = mods
                await asyncio.to_thread(publish)
            elif time.time() - last_state > 15:
                await asyncio.to_thread(publish_state)
                last_state = time.time()
        except Exception:  # noqa: BLE001
            log.exception("watch loop")
        await asyncio.sleep(WATCH_S)


async def _learn(pressed: bool = False) -> None:
    house = await ha.house()
    states = {s["entity_id"]: s for s in (house or {}).get("states") or []}
    await learning.run_pass(states, pressed=pressed)
    await asyncio.to_thread(publish_state)


async def tick_loop() -> None:
    while True:
        try:
            if STATE.get("retry_generate"):
                await retry_generate()
            await asyncio.to_thread(learning.settle_doing, tell.read_state)
            if learning.due() and not learning.state().get("running"):
                await _learn()
            await asyncio.to_thread(devloop.ingest_errors)
            await asyncio.to_thread(devloop.publish, VERSION)
            await asyncio.to_thread(tell.prune)
        except Exception:  # noqa: BLE001
            log.exception("tick loop")
        await asyncio.sleep(TICK_S)


async def health_server() -> None:
    from aiohttp import web

    async def health(_):
        return web.json_response({"ok": True, "version": VERSION, "ready": STATE["bootstrapped"]})

    app = web.Application()
    app.router.add_get("/api/health", health)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    port = int(os.environ.get("MORPH_HEALTH_PORT", "8096"))
    await web.TCPSite(runner, "127.0.0.1", port).start()


async def main() -> None:
    level = os.environ.get("MORPH_LOG_LEVEL", "info").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # A learning pass that was running when the add-on stopped never answers.
    if learning.state().get("running"):
        learning._set_state(running="")
    await health_server()
    await bootstrap()
    log.info("Morph %s ready; dashboard at %s", VERSION, paths.DASHBOARD)
    await asyncio.gather(requests_loop(), watch_loop(), tick_loop())


if __name__ == "__main__":
    asyncio.run(main())
