"""The printers somebody added, with their access codes kept apart.

`/data/printers.json` holds what a printer IS (name, address, serial,
model) and `/data/secrets/printers.json` holds the one thing that lets
anybody drive it — the access code. Two files because config.yaml's
`backup_exclude` drops `secrets/**`: a Home Assistant backup is unencrypted
unless somebody opts in, then copied to cloud storage and support tickets,
and an access code in it is a printer with a hot end that anybody holding
the backup can start. Restoring a backup brings the printers back and asks
for their codes again, which is the right trade.
"""
from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path

import atomic_write

DATA = Path(os.environ.get("BAMBU_DATA", "/data"))
PRINTERS = DATA / "printers.json"
SECRETS = DATA / "secrets" / "printers.json"

SERIAL = re.compile(r"^[A-Z0-9]{8,20}$")
CODE = re.compile(r"^[A-Za-z0-9]{6,12}$")
HOSTNAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,62}\.)*[A-Za-z0-9-]{1,63}$")
MODELS = ("X1C", "X1E", "X1", "P1S", "P1P", "P2S", "A1", "A1 mini", "H2D", "H2S", "")


def _valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(HOSTNAME.match(host))


def clean(entry: dict) -> dict:
    """A printer as stored, or ValueError naming the field that is wrong."""
    name = str(entry.get("name") or "").strip()[:60]
    host = str(entry.get("host") or "").strip()
    serial = str(entry.get("serial") or "").strip().upper()
    model = str(entry.get("model") or "").strip()
    if not _valid_host(host):
        raise ValueError("Give the printer's IP address (its screen shows it under Network).")
    if not SERIAL.match(serial):
        raise ValueError("The serial number is letters and digits, as the printer's "
                         "screen shows it under Settings → Device.")
    if model not in MODELS:
        model = ""
    return {"id": serial.lower(), "name": name or f"Bambu {model or serial[-4:]}",
            "host": host, "serial": serial, "model": model}


def load() -> list[dict]:
    rows = atomic_write.read_json(PRINTERS, [])
    return [r for r in rows if isinstance(r, dict) and r.get("id")] if isinstance(rows, list) else []


def codes() -> dict:
    data = atomic_write.read_json(SECRETS, {})
    return data if isinstance(data, dict) else {}


def save(entry: dict, access_code: str | None) -> dict:
    printer = clean(entry)
    rows = [r for r in load() if r["id"] != printer["id"]]
    secrets = codes()
    if access_code is not None and str(access_code).strip():
        code = str(access_code).strip()
        if not CODE.match(code):
            raise ValueError("The access code is the 8 characters the printer shows "
                             "under Settings → LAN Only (or WLAN).")
        secrets[printer["id"]] = code
    if printer["id"] not in secrets:
        raise ValueError("The access code is required.")
    rows.append(printer)
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS.parent, 0o700)
    atomic_write.write_json(SECRETS, secrets, mode=0o600)
    atomic_write.write_json(PRINTERS, rows)
    return printer


def remove(printer_id: str) -> bool:
    rows = load()
    kept = [r for r in rows if r["id"] != printer_id]
    secrets = codes()
    secrets.pop(printer_id, None)
    atomic_write.write_json(PRINTERS, kept)
    if SECRETS.exists():
        atomic_write.write_json(SECRETS, secrets, mode=0o600)
    return len(kept) != len(rows)


def resolve(rows: list[dict], wanted: str | None) -> dict:
    """The printer a request means, by id, serial or name — or why not.

    Left out, it is the only printer there is. Two printers and no name is
    a question, not a guess: a print started on the wrong machine is
    filament and an hour gone.
    """
    if not rows:
        raise LookupError("No printer has been added yet. Add one on the panel's Printers tab.")
    text = str(wanted or "").strip().lower()
    if not text:
        if len(rows) == 1:
            return rows[0]
        raise LookupError("Which printer? " + ", ".join(r["name"] for r in rows) + ".")
    for row in rows:
        if text in (row["id"], row["serial"].lower(), row["name"].lower()):
            return row
    partial = [r for r in rows if text in r["name"].lower()]
    if len(partial) == 1:
        return partial[0]
    raise LookupError(f"No printer called {wanted!r}. Printers: "
                      + ", ".join(r["name"] for r in rows) + ".")
