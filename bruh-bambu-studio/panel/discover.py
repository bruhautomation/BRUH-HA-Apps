"""Find the Bambu Lab printers on the local network.

Printers announce themselves over SSDP broadcast, which never reaches an
add-on on Home Assistant's internal network, and moving to the host network
would make the panel's port a real host port somebody else may own. What
does reach the LAN from here is an outbound TCP connection, and a Bambu
printer has a signature on one: its MQTT port (8883) answers TLS with a
certificate issued by Bambu Lab's own device CA ("BBL …") whose common name
is the printer's serial number. So a scan is: the LAN subnets Home Assistant
is on (the Supervisor's /network/info), a connect to 8883 on each address,
and the certificate read off the ones that answer. Nothing is sent to a
printer but a TLS handshake, and no access code is needed to find one —
only to talk to it.

The model is the serial's prefix, from the table below; a prefix this does
not know leaves the model for the person to pick.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PORT = 8883
CONNECT_S = 0.6
HANDSHAKE_S = 3.0
WORKERS = 64
# A /22 is 1022 addresses, a few seconds; anything wider is narrowed to the
# /24 Home Assistant itself is in, because a /16 is minutes of connects.
WIDEST = 22
SUPERVISOR = "http://supervisor"
SERIAL = re.compile(r"^[0-9A-Z]{8,20}$")
# Home Assistant's own internal network: never where a printer is.
HASSIO = ipaddress.ip_network("172.30.32.0/23")

MODEL_BY_PREFIX = {
    "00M": "X1C", "00W": "X1", "03W": "X1E", "01P": "P1S", "01S": "P1P",
    "030": "A1 mini", "039": "A1", "094": "H2D",
}

_CN = b"\x06\x03\x55\x04\x03"  # OID 2.5.4.3, commonName
_STRING_TAGS = {0x0C, 0x13, 0x14, 0x16, 0x1E}


def common_names(der: bytes) -> list[str]:
    """Every commonName in a DER certificate, in order: issuer's, then subject's.

    A full ASN.1 parser would be a dependency for two strings; a CN is the
    OID followed by one string, and in a certificate the issuer's comes
    before the subject's.
    """
    out = []
    at = der.find(_CN)
    while at != -1:
        i = at + len(_CN)
        if i + 2 <= len(der) and der[i] in _STRING_TAGS and der[i + 1] < 0x80:
            raw = der[i + 2:i + 2 + der[i + 1]]
            out.append(raw.decode("utf-16-be" if der[i] == 0x1E else "utf-8", "replace"))
        at = der.find(_CN, at + 1)
    return out


def model_for(serial: str) -> str:
    return MODEL_BY_PREFIX.get(str(serial or "")[:3].upper(), "")


def lan_networks() -> list[ipaddress.IPv4Network]:
    """The IPv4 networks Home Assistant's connected interfaces are on."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return []
    request = urllib.request.Request(f"{SUPERVISOR}/network/info",
                                     headers={"Authorization": f"Bearer {token}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            data = json.loads(response.read()).get("data") or {}
    except (OSError, ValueError):
        return []
    nets = []
    for iface in data.get("interfaces") or []:
        if not iface.get("enabled", True) or iface.get("connected") is False:
            continue
        for address in ((iface.get("ipv4") or {}).get("address") or []):
            net = narrowed(address)
            if net is not None and net not in nets:
                nets.append(net)
    return nets


def narrowed(address: str) -> ipaddress.IPv4Network | None:
    """A host's network as a scan can cover it, or None for one never to scan."""
    try:
        iface = ipaddress.ip_interface(str(address).strip())
    except ValueError:
        return None
    if iface.version != 4:
        return None
    net = iface.network
    if net.prefixlen < WIDEST:
        net = ipaddress.ip_interface(f"{iface.ip}/24").network
    if (iface.ip.is_loopback or iface.ip.is_link_local or net.overlaps(HASSIO)
            or net.prefixlen > 30):
        return None
    return net


def probe(host: str) -> dict | None:
    """A printer at `host`, read off its MQTT certificate, or None."""
    try:
        sock = socket.create_connection((host, PORT), timeout=CONNECT_S)
    except OSError:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        sock.settimeout(HANDSHAKE_S)
        with context.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True) or b""
    except (OSError, ssl.SSLError):
        return None
    finally:
        sock.close()
    names = common_names(der)
    if len(names) < 2:
        return None
    issuer, subject = names[0], names[-1].strip().upper()
    if not issuer.upper().startswith("BBL") or not SERIAL.match(subject):
        return None
    return {"host": host, "serial": subject, "model": model_for(subject)}


def scan(networks: list, progress=None) -> list[dict]:
    """Every printer on these networks, sorted by address."""
    hosts = []
    for net in networks:
        hosts += [str(h) for h in net.hosts()]
    hosts = list(dict.fromkeys(hosts))
    found, done = [], 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for result in pool.map(probe, hosts):
            done += 1
            if result:
                found.append(result)
            if progress and done % 32 == 0:
                progress(done, len(hosts))
    return sorted(found, key=lambda r: ipaddress.ip_address(r["host"]))
