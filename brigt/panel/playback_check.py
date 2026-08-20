"""Why nothing is playing — asked one step at a time.

`media_player.play_media` answers "accepted", not "playing". Everything that
can go wrong afterwards goes wrong somewhere BRigt cannot see: Core resolves
the media id, signs a path, puts a *host* in front of it, and hands the
result to a speaker that then fetches it over the network on its own. A
Chromecast that cannot resolve that host simply plays nothing, and the
service call that started it returned 200 several seconds earlier.

So this walks the chain and reports each link:

1. **the file** — is it on disk, and is it the size it should be
2. **the media id** — does *Core* resolve it, with the same call the cast
   integration makes (which is what catches a `media_dirs` that has been
   renamed away from `local`, and a file Core cannot see)
3. **the host** — what Core will put in front of the path it signed, and
   whether a speaker can be expected to reach it
4. **the player** — does the entity exist, and does it accept play_media
5. **the command** — did Core accept it
6. **playing** — did the player actually get there, or is it still idle

Step 3 is the one that took research rather than reading. Core builds the
speaker's URL with `get_url()`: `internal_url` when it is set, and otherwise
the machine's own detected IP. Chromecast and Google speakers resolve names
through Google's public DNS (8.8.8.8) rather than the router's, so an
`internal_url` of `http://homeassistant.local:8123` — which is what a great
many installs have — is a name the speaker asks Google about and is told
does not exist. Nothing plays, nothing errors, and Home Assistant's own
documentation says to use an IP address for exactly this reason.
"""
from __future__ import annotations

import asyncio
import ipaddress
import time
from pathlib import Path
from urllib.parse import urlsplit

import ha_client
import ha_ws

# MediaPlayerEntityFeature.PLAY_MEDIA, from Home Assistant's own enum. A
# player without it cannot be sent media at all, whatever else is true.
FEATURE_PLAY_MEDIA = 512

# How long to wait for the player to admit it is playing. A Chromecast that
# is going to work usually gets there in two or three seconds; one that
# cannot fetch the URL never does, and the wait is what tells them apart.
PLAY_WAIT_S = 10.0
POLL_S = 0.5

PLAYING_STATES = ("playing", "buffering")


def _flat(value: object, limit: int = 200) -> str:
    """Text from somewhere else, on one line.

    Every detail below quotes something BRigt did not write — an entity id,
    a state Home Assistant reported, an error string — and these lines are
    logged as well as rendered. A newline in a logged value is a caller
    writing its own log lines, so the line breaks go here rather than in
    each caller (same reasoning as the panel's `_for_log`).
    """
    return (str(value)
            .replace("\r\n", " ").replace("\n", " ")
            .replace("\r", " ").replace("\t", " ")[:limit])


def _step(name: str, ok: bool | None, detail: str, fix: str = "") -> dict:
    """One link in the chain. `ok` is None for "could not tell", which is
    not the same as a failure and must not be reported as one."""
    step = {"name": name, "ok": ok, "detail": detail}
    if fix:
        step["fix"] = fix
    return step


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def base_url_step(config: dict) -> dict:
    """What Core will put in front of the media path, and who can reach it.

    Mirrors `homeassistant.helpers.network.get_url`: `internal_url` if set,
    otherwise the detected local IP — which is always fetchable, so an unset
    internal URL is the *good* case here rather than a missing setting.
    """
    if config.get("error"):
        return _step("host", None, f"could not read Home Assistant's "
                                   f"configuration: {_flat(config['error'])}")
    internal = str(config.get("internal_url") or "").strip()
    external = str(config.get("external_url") or "").strip()
    chosen = internal or external
    if not chosen:
        return _step("host", True,
                     "Home Assistant has no internal URL set, so it hands "
                     "speakers its own IP address — which they can fetch")

    parts = urlsplit(chosen)
    host = parts.hostname or ""
    where = "internal URL" if internal else "external URL"
    if _is_ip(host):
        if parts.scheme == "https":
            return _step("host", None,
                         f"{where} is {chosen} — an IP address over HTTPS",
                         "Chromecast and Google speakers refuse certificates "
                         "they cannot verify, and a certificate for an IP "
                         "address is usually one of those. If nothing plays, "
                         "set the internal URL to http://<ip>:8123.")
        return _step("host", True, f"{where} is {chosen} — an address a "
                                   f"speaker can fetch")

    if host.endswith(".local"):
        return _step(
            "host", False,
            f"{where} is {chosen}, and .local names are resolved by mDNS",
            "This is the most common reason a Chromecast or Google speaker "
            "plays nothing: they resolve names through Google's public DNS "
            "(8.8.8.8), not your router's, so a .local name does not exist "
            "as far as they are concerned. Set Settings → System → Network → "
            "Internal URL to http://<your Home Assistant IP>:8123.")

    return _step(
        "host", None,
        f"{where} is {chosen} — a name rather than an address",
        "Your speaker has to be able to resolve that name on its own. "
        "Chromecast and Google speakers use Google's public DNS, so a name "
        "that only your router knows about will not resolve for them; an IP "
        "address in Settings → System → Network → Internal URL always works.")


def file_step(path: Path | None, expected_size: int | None = None) -> dict:
    if path is None:
        return _step("file", None, "not a local file")
    try:
        size = path.stat().st_size
    except OSError as exc:
        return _step("file", False, f"{path} is not readable: {_flat(exc)}",
                     "BRigt can only play files it can see under /media.")
    if expected_size is not None and size != expected_size:
        return _step("file", False,
                     f"{path} is {size} bytes, expected {expected_size}",
                     "Restart the add-on — it rewrites the click track when "
                     "the one on disk is not the right length.")
    return _step("file", True, f"{path} · {size:,} bytes")


async def resolve_step(media_content_id: str) -> tuple[dict, dict]:
    """Ask Core to resolve the media id, exactly as the speaker's integration
    will. Returns the step and the raw answer (for the caller's summary)."""
    answer = await ha_ws.resolve_media(media_content_id)
    if answer.get("error"):
        return _step(
            "media", False,
            f"Home Assistant will not resolve {_flat(media_content_id)}: "
            f"{_flat(answer['error'])}",
            "The id is built from where the file sits under /media. If you "
            "set `media_dirs` in configuration.yaml, Home Assistant's local "
            "media source is no longer called `local` and BRigt's ids will "
            "not resolve — see the add-on documentation.",
        ), answer
    url = _flat(answer.get("url") or "")
    mime = _flat(answer.get("mime_type") or "")
    if not mime:
        return _step("media", None,
                     f"resolved to {url}, but Home Assistant reported no "
                     f"media type"), answer
    return _step("media", True, f"{mime} · {url}"), answer


def player_step(state: dict, entity_id: str) -> dict:
    if state.get("error"):
        return _step("player", False,
                     f"{_flat(entity_id)}: {_flat(state['error'])}",
                     "Pick a media player that exists — the list comes from "
                     "Home Assistant.")
    attributes = state.get("attributes") or {}
    try:
        features = int(attributes.get("supported_features") or 0)
    except (TypeError, ValueError):
        features = 0
    name = _flat(attributes.get("friendly_name") or entity_id)
    if not features & FEATURE_PLAY_MEDIA:
        return _step("player", False,
                     f"{name} does not accept play_media",
                     "This entity cannot be sent media at all. Group members "
                     "and some remotes look like players and are not.")
    return _step("player", True,
                 f"{name} · state {_flat(state.get('state'))!r}")


async def wait_for_playing(entity_id: str, *, wait_s: float = PLAY_WAIT_S,
                           poll_s: float = POLL_S,
                           now=time.monotonic) -> dict:
    """Poll until the player admits it is playing, or the wait runs out.

    This is the step that separates "Home Assistant accepted the command"
    from "the speaker is making sound", and nothing before it can answer
    that question — the fetch happens on the speaker, over the network,
    after the service call has already returned.
    """
    deadline = now() + wait_s
    seen: list[str] = []
    while True:
        state = await asyncio.to_thread(ha_client.get_state, entity_id)
        current = _flat(state.get("state") or "unknown", 32)
        if not seen or seen[-1] != current:
            seen.append(current)
        if current in PLAYING_STATES:
            attributes = state.get("attributes") or {}
            title = _flat(attributes.get("media_title") or attributes.get(
                "media_content_id") or "")
            detail = f"{_flat(entity_id)} is {current}"
            return _step("playing", True,
                         f"{detail} — {title}" if title else detail)
        if now() >= deadline:
            trail = " → ".join(seen) or current
            return _step(
                "playing", False,
                f"{_flat(entity_id)} never started playing (state: {trail})",
                "Home Assistant accepted the command, so the speaker was "
                "told to play and did not. That is almost always the URL it "
                "was given: see the host step above.")
        await asyncio.sleep(poll_s)


async def check(entity_id: str, media_content_id: str, *,
                path: Path | None = None, expected_size: int | None = None,
                wait_s: float = PLAY_WAIT_S) -> dict:
    """The whole chain, in order, stopping at the first link that breaks it.

    A step that fails and makes the next ones meaningless ends the walk —
    telling somebody their speaker never started playing is noise when the
    file was never there to play.
    """
    steps: list[dict] = []

    step = file_step(path, expected_size)
    steps.append(step)
    if step["ok"] is False:
        return _verdict(steps)

    step, _ = await resolve_step(media_content_id)
    steps.append(step)
    if step["ok"] is False:
        return _verdict(steps)

    config = await asyncio.to_thread(ha_client.get_config)
    steps.append(base_url_step(config))

    state = await asyncio.to_thread(ha_client.get_state, entity_id)
    step = player_step(state, entity_id)
    steps.append(step)
    if step["ok"] is False:
        return _verdict(steps)

    result = await asyncio.to_thread(
        ha_client.play_media, entity_id, media_content_id)
    if isinstance(result, dict) and result.get("error"):
        steps.append(_step("command", False,
                           f"Home Assistant refused the play command: "
                           f"{_flat(result['error'])}"))
        return _verdict(steps)
    steps.append(_step("command", True, "Home Assistant accepted the command"))

    steps.append(await wait_for_playing(entity_id, wait_s=wait_s))
    return _verdict(steps)


def _verdict(steps: list[dict]) -> dict:
    """The steps plus the one sentence somebody reads first."""
    broken = next((s for s in steps if s["ok"] is False), None)
    if broken is not None:
        return {"ok": False, "steps": steps,
                "summary": broken["detail"],
                "fix": broken.get("fix", "")}
    warned = next((s for s in steps if s["ok"] is None and s.get("fix")), None)
    if warned is not None:
        return {"ok": True, "steps": steps,
                "summary": "It played, but one thing here is worth reading.",
                "fix": warned["fix"]}
    return {"ok": True, "steps": steps,
            "summary": "Playback works: the speaker fetched the file and "
                       "started playing it."}
