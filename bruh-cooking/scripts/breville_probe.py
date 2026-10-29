#!/usr/bin/env python3
"""Probe the Breville+ cloud with your own account.

Verifies the reverse-engineered API before it goes into the Home Assistant
integration. Every request and websocket message is written, with tokens and
personal details redacted, to probe-output/capture-*.jsonl.

  python3 scripts/breville_probe.py login
  python3 scripts/breville_probe.py appliances
  python3 scripts/breville_probe.py watch --seconds 600
  python3 scripts/breville_probe.py start --temp 55 --minutes 30 --confirm-water
  python3 scripts/breville_probe.py finish-wait      # food is in: start the timer
  python3 scripts/breville_probe.py set-temp --temp 57
  python3 scripts/breville_probe.py stop

Tokens are kept in ~/.cache/ha-bruh-cooking/tokens.json (mode 600).
Set BREVILLE_EMAIL / BREVILLE_PASSWORD to skip the login prompts.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import json
import os
import re
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

try:
    import certifi
except ImportError:  # fall back to the system store
    certifi = None

REPO = Path(__file__).resolve().parent.parent
API_PATH = REPO / "custom_components" / "bruh_cooking" / "api.py"
STATE_DIR = Path.home() / ".cache" / "ha-bruh-cooking"
OUT_DIR = REPO / "probe-output"


def load_api():
    """Import api.py by path so Home Assistant isn't needed."""
    spec = importlib.util.spec_from_file_location("breville_api", API_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


api = load_api()

# Returned by Probe.call(quiet=True) when the cloud answered with an error.
FAILED = object()

SENSITIVE = re.compile(
    r"token|password|secret|e-?mail|phone|address|street|postal|zip|"
    r"first_?name|last_?name|given_name|family_name|mfa",
    re.IGNORECASE,
)


def ssl_context() -> ssl.SSLContext:
    """Verify TLS with certifi, as Home Assistant does.

    The python.org macOS installer ships without a CA store, so the default
    context can't verify anything until "Install Certificates" has been run.
    """
    if certifi:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: "<redacted>" if SENSITIVE.search(str(k)) and v not in (None, "") else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class Capture:
    def __init__(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / f"capture-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
        self._fh = self.path.open("a", encoding="utf-8")

    def record(self, kind: str, **fields: Any) -> None:
        entry = {"ts": datetime.now().isoformat(timespec="milliseconds"), "kind": kind}
        entry.update(redact(fields))
        self._fh.write(json.dumps(entry, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class TokenStore:
    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "tokens.json"

    def load(self):
        if not self.path.exists():
            return None
        return api.Tokens.from_dict(json.loads(self.path.read_text()))

    def save(self, tokens) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(tokens.as_dict(), fh)


def field(obj: dict[str, Any], *names: str) -> Any:
    for name in names:
        if obj.get(name) not in (None, ""):
            return obj[name]
    return None


def serial_of(appliance: dict[str, Any]) -> str | None:
    return field(appliance, "serialNumber", "serial", "serial_number")


def model_of(appliance: dict[str, Any]) -> str | None:
    return field(appliance, "model", "applianceModel", "modelNumber", "productModel")


def step_name(step: Any) -> str:
    try:
        return api.CsjProgramStep(step).name
    except ValueError:
        return str(step)


def summarize(msg: Any) -> str:
    if not isinstance(msg, dict):
        return repr(msg)[:200]
    parsed = api.state_from_message(msg)
    if not parsed:
        return f"{msg.get('messageType')} {json.dumps(redact(msg))[:160]}"
    _, s = parsed
    parts = [msg["messageType"], s.get("state", "?")]
    if s.get("programStep"):
        parts.append(step_name(s["programStep"]))
    if isinstance(s.get("bathTemp"), (int, float)):
        parts.append(f"bath={s['bathTemp']:.1f}°C")
    if isinstance(s.get("setPoint"), (int, float)):
        parts.append(f"target={s['setPoint']:.1f}°C")
    if s.get("cookTime"):
        parts.append(f"timer={s.get('timeRemaining', 0)}/{s['cookTime']}s")
    if s.get("errorState"):
        parts.append(f"error={s['errorState']} event={s.get('eventType')}/{s.get('eventReason')}")
    return " ".join(parts)


def temp_c_from(args: argparse.Namespace) -> float | None:
    if getattr(args, "temp", None) is not None:
        return args.temp
    if getattr(args, "temp_f", None) is not None:
        return (args.temp_f - 32) * 5 / 9
    return None


class Probe:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.store = TokenStore(Path(args.state_dir))
        self.capture = Capture(Path(args.out))

    async def run(self) -> int:
        connector = aiohttp.TCPConnector(ssl=ssl_context())
        async with aiohttp.ClientSession(connector=connector) as session:
            self.client = api.BrevilleClient(
                session,
                self.store.load(),
                endpoints=api.BRANDS[self.args.brand],
                on_tokens_updated=self.store.save,
            )
            try:
                return await getattr(self, f"cmd_{self.args.command.replace('-', '_')}")()
            except api.BrevilleMfaRequired:
                print("Login needs multi-factor authentication, which the probe doesn't support yet.")
                return 2
            except api.BrevilleAuthError as err:
                self.capture.record("error", error=str(err))
                print(f"Authentication failed: {err}")
                return 2
            except api.BrevilleApiError as err:
                if err.method == "POST" and err.url == self.client.endpoints.token_url:
                    self.capture.record("rest", call="oauth_token", url=err.url,
                                        status=err.status, response=err.body)
                print(f"Unexpected response: HTTP {err.status} from {err.method} {err.url}")
                print(json.dumps(redact(err.body), indent=2)[:2000])
                return 1
            except aiohttp.ClientConnectorCertificateError as err:
                print(f"TLS certificate check failed for {err.host}: {err.certificate_error}")
                print("Install certifi (pip install certifi) or run Python's "
                      "'Install Certificates.command', then try again.")
                return 1
            except (aiohttp.ClientError, TimeoutError) as err:
                self.capture.record("error", error=f"{type(err).__name__}: {err}")
                print(f"Network error: {type(err).__name__}: {err}")
                return 1
            finally:
                self.capture.close()
                print(f"\nCapture written to {self.capture.path}")

    def require_login(self) -> None:
        if not self.client.tokens:
            raise api.BrevilleAuthError("No saved session; run the 'login' command first")

    async def call(self, label: str, coro, request: Any = None, *, quiet: bool = False) -> Any:
        """Await a client call and record the outcome either way."""
        started = time.monotonic()
        try:
            data = await coro
        except api.BrevilleApiError as err:
            self.capture.record("rest", call=label, request=request, url=err.url,
                                status=err.status, response=err.body)
            if not quiet:
                raise
            print(f"  {label}: HTTP {err.status} {json.dumps(redact(err.body))[:500]}")
            return FAILED
        self.capture.record("rest", call=label, request=request, status="ok",
                            elapsed_ms=round((time.monotonic() - started) * 1000),
                            response=data)
        return data

    # -- commands ---------------------------------------------------------

    async def cmd_login(self) -> int:
        email = os.environ.get("BREVILLE_EMAIL") or input("Breville account email: ").strip()
        password = os.environ.get("BREVILLE_PASSWORD") or getpass.getpass("Password: ")
        tokens = await self.client.login(email, password)
        claims = tokens.claims
        self.capture.record("login", ok=True, claim_keys=sorted(claims),
                            iss=claims.get("iss"), aud=claims.get("aud"))
        expires = datetime.fromtimestamp(tokens.expires_at)
        print("Login OK.")
        print(f"  user id (sub): {tokens.user_id}")
        print(f"  id_token expires: {expires:%Y-%m-%d %H:%M}")
        print(f"  refresh token: {'yes' if tokens.refresh_token else 'NO'}")
        return 0

    async def load_appliances(self) -> list[dict[str, Any]]:
        self.require_login()
        data = await self.call("get_appliances", self.client.get_appliances())
        return data["appliances"]

    async def pick(self) -> dict[str, Any]:
        appliances = await self.load_appliances()
        if self.args.serial:
            for appliance in appliances:
                if serial_of(appliance) == self.args.serial:
                    return appliance
            raise SystemExit(f"No appliance with serial {self.args.serial} on this account")
        joules = [a for a in appliances if model_of(a) == api.MODEL_CSJ100]
        if len(joules) == 1:
            return joules[0]
        found = ", ".join(f"{model_of(a)}:{serial_of(a)}" for a in appliances) or "none"
        raise SystemExit(f"Pass --serial; found {len(joules)} CSJ100 (appliances: {found})")

    async def cmd_appliances(self) -> int:
        appliances = await self.load_appliances()
        print(f"{len(appliances)} appliance(s):")
        for appliance in appliances:
            print(f"  model={model_of(appliance)} serial={serial_of(appliance)} "
                  f"name={field(appliance, 'name', 'applianceName', 'nickname')}")
            print(f"    keys: {', '.join(sorted(appliance))}")
            serial = serial_of(appliance)
            if serial:
                detail = await self.call("get_model", self.client.get_model(serial),
                                         serial, quiet=True)
                if detail is not FAILED:
                    print(f"    /model: {json.dumps(redact(detail))[:300]}")
        return 0

    async def watch(self, appliances: list[dict[str, Any]], seconds: float, action=None) -> None:
        """Stream live state; run action once the first state has arrived."""
        self.states: dict[str, dict[str, Any]] = {}
        have_state = asyncio.Event()
        sock = self.client.websocket()
        await sock.connect()
        self.capture.record("ws", event="connected")

        async def pump() -> None:
            async for msg in sock.messages():
                self.capture.record("ws", event="message", message=msg)
                print(f"[{datetime.now():%H:%M:%S}] {summarize(msg)}")
                parsed = api.state_from_message(msg)
                if parsed:
                    self.states.setdefault(parsed[0], {}).update(parsed[1])
                    have_state.set()

        pump_task = asyncio.create_task(pump())
        try:
            for appliance in appliances:
                await sock.subscribe(serial_of(appliance), model_of(appliance))
                self.capture.record("ws", event="subscribed", serial=serial_of(appliance),
                                    model=model_of(appliance))
            span = f"for {seconds:.0f}s" if seconds else "until Ctrl-C"
            print(f"Websocket connected; listening {span}.")
            if action:
                try:
                    await asyncio.wait_for(have_state.wait(), 20)
                except TimeoutError:
                    print("No appliance state received in 20s; is the Joule plugged in and online?")
                    return
                await action()
            try:
                await asyncio.wait_for(asyncio.shield(pump_task), seconds or None)
                print("Websocket closed by server.")
            except TimeoutError:
                print("Done listening.")
        finally:
            pump_task.cancel()
            await asyncio.gather(pump_task, return_exceptions=True)
            await sock.close()

    async def send(self, label: str, coro, request: Any) -> bool:
        print(f"Sending {label}: {json.dumps(request)}")
        result = await self.call(label, coro, request, quiet=True)
        if result is FAILED:
            return False
        print(f"  cloud accepted it: {json.dumps(redact(result))[:300]}")
        return True

    async def cmd_watch(self) -> int:
        if self.args.serial:
            targets = [await self.pick()]
        else:
            targets = [a for a in await self.load_appliances() if serial_of(a)]
        if not targets:
            print("No appliances to watch.")
            return 1
        await self.watch(targets, self.args.seconds)
        return 0

    async def cmd_start(self) -> int:
        if not self.args.confirm_water:
            print("Refusing to start: put the Joule in a pot of water, then re-run with --confirm-water.")
            return 2
        cook_time = int(self.args.minutes * 60) if self.args.minutes else None
        try:
            steps = api.build_csj_manual_steps(
                temp_c_from(self.args), cook_time, auto_start_timer=self.args.auto_start_timer
            )
        except ValueError as err:
            print(f"Invalid cook settings: {err}")
            return 2
        appliance = await self.pick()
        serial, model = serial_of(appliance), model_of(appliance)
        if model != api.MODEL_CSJ100:
            print(f"The probe only builds Joule (CSJ100) cooks; {model} is supported by the integration.")
            return 2

        async def act() -> None:
            state = self.states.get(serial, {})
            if api.csj_is_ul_certified(state) and temp_c_from(self.args) > api.CSJ_COMPLIANCE_PRESS_ABOVE_C:
                print("Note: this Joule is UL-certified; above 85 °C press its top button to start.")
            firmware = api.csj_firmware(state)
            await self.send(
                "load-manual-recipe",
                self.client.load_manual_recipe(serial, model, firmware, steps),
                {"firmware": firmware, "steps": steps},
            )

        await self.watch([appliance], self.args.watch, act)
        return 0

    async def cmd_set_temp(self) -> int:
        appliance = await self.pick()
        serial = serial_of(appliance)
        if model_of(appliance) != api.MODEL_CSJ100:
            print("The probe only edits Joule (CSJ100) cooks.")
            return 2
        cook_time = int(self.args.minutes * 60) if self.args.minutes is not None else None

        async def act() -> None:
            try:
                program = api.build_csj_edit_program(
                    self.states.get(serial, {}), set_point_c=temp_c_from(self.args),
                    cook_time_s=cook_time,
                )
            except ValueError as err:
                print(f"Can't change the cook: {err}")
                return
            await self.send(
                "startProgramRequest (edit)", self.client.csj_update_program(serial, program), program
            )

        await self.watch([appliance], self.args.watch, act)
        return 0

    async def cmd_finish_wait(self) -> int:
        appliance = await self.pick()
        serial, model = serial_of(appliance), model_of(appliance)

        async def act() -> None:
            step = self.states.get(serial, {}).get("programStep")
            if step not in (api.CsjProgramStep.WAIT_FOR_FOOD, api.CsjProgramStep.WAIT_FOR_REMOVE_FOOD):
                print(f"Note: the Joule is at {step_name(step)}, not waiting for food; sending anyway.")
            await self.send("finish-wait", self.client.finish_wait(serial, model), {"model": model})

        await self.watch([appliance], self.args.watch, act)
        return 0

    async def cmd_stop(self) -> int:
        appliance = await self.pick()
        serial, model = serial_of(appliance), model_of(appliance)
        reason = api.StopRecipeReason[self.args.reason.upper()]

        async def act() -> None:
            firmware = api.csj_firmware(self.states.get(serial, {}))
            await self.send(
                "stop-recipe",
                self.client.stop_recipe(serial, model, firmware=firmware, reason=reason),
                {"model": model, "firmware": firmware, "reason": reason.name},
            )

        await self.watch([appliance], self.args.watch, act)
        return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", default=str(STATE_DIR), help="where tokens are saved")
    parser.add_argument("--out", default=str(OUT_DIR), help="where capture files are written")
    parser.add_argument("--brand", choices=sorted(api.BRANDS), default="breville",
                        help="sage for the Sage app (UK and Europe); log in again after changing it")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="log in and save a session")
    sub.add_parser("appliances", help="list appliances on the account")

    watch = sub.add_parser("watch", help="print live websocket messages")
    watch.add_argument("--serial")
    watch.add_argument("--seconds", type=float, default=300, help="0 = until Ctrl-C")

    def temperature(cmd: argparse.ArgumentParser, required: bool) -> None:
        group = cmd.add_mutually_exclusive_group(required=required)
        group.add_argument("--temp", type=float, help="target °C")
        group.add_argument("--temp-f", type=float, help="target °F")

    start = sub.add_parser("start", help="start a new cook (like the app's manual cook)")
    start.add_argument("--serial")
    temperature(start, required=True)
    start.add_argument("--minutes", type=float,
                       help="cook time after the food goes in; omit to hold indefinitely")
    start.add_argument("--auto-start-timer", action="store_true",
                       help="start the timer when the bath is at temperature instead of waiting for food")
    start.add_argument("--watch", type=float, default=120, help="seconds to listen afterwards")
    start.add_argument("--confirm-water", action="store_true",
                       help="confirm the Joule is in a pot of water")

    set_temp = sub.add_parser("set-temp", help="change the temperature or timer of the running cook")
    set_temp.add_argument("--serial")
    temperature(set_temp, required=False)
    set_temp.add_argument("--minutes", type=float, help="new cook time (minutes)")
    set_temp.add_argument("--watch", type=float, default=60, help="seconds to listen afterwards")

    finish = sub.add_parser("finish-wait",
                            help="tell the Joule the food is in (starts the timer) or has been removed")
    finish.add_argument("--serial")
    finish.add_argument("--watch", type=float, default=30, help="seconds to listen afterwards")

    stop = sub.add_parser("stop", help="stop the running cook")
    stop.add_argument("--serial")
    stop.add_argument("--reason", choices=("cancel", "complete"), default="cancel")
    stop.add_argument("--watch", type=float, default=30, help="seconds to listen afterwards")
    args = parser.parse_args(argv)
    if args.command == "set-temp" and args.temp is None and args.temp_f is None and args.minutes is None:
        parser.error("set-temp needs --temp, --temp-f or --minutes")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return asyncio.run(Probe(args).run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
