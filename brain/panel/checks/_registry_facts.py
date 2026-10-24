"""Facts about registry rows that more than one check module reads.

A leaf: it imports nothing of the checks package, so `devices` and
`network` can both read it without importing each other.
"""

from __future__ import annotations

SELF_PLATFORMS = frozenset({"brain"})


ENTRY_NOT_LOADED = frozenset({
    "setup_error", "setup_retry", "migration_error", "not_loaded",
    "failed_unload",
})
# What a device's settings page carries. An unavailable firmware or "cloud
# connection" entity on a device that still answers is not the device
# having gone away.
SETTINGS_CATEGORIES = frozenset({"diagnostic", "config"})
# Integrations whose entities are features somebody switches on or off on
# the device itself. The companion app publishes a sensor per phone feature
# (kiosk mode, a camera, an activity reading) and one that is turned off in
# the app reads unavailable for ever while the phone goes on reporting
# everything else — a setting, not a fault. On a device that still answers
# such an entity says nothing; a phone that has gone quiet altogether is
# still reported as the device.
FEATURE_PLATFORMS = frozenset({"mobile_app"})


def is_node_status(entity_id: str, reg: dict) -> bool:
    """Whether this is the node status sensor Z-Wave JS publishes.

    Read off what the integration REGISTERED — its translation key
    `node_status`, or its unique id `<home id>.<node id>.node_status` —
    and never off the entity id alone. The entity id is derived from a
    name: it is in the house's own language, it is whatever somebody
    renamed it to, and a second device of the same name gets `_2` on the
    end. Reading the suffix missed a node the controller had declared
    dead for days, and its frozen 0% battery was filed in its place. The
    suffix stays as the answer for a registry row that carries neither
    field (an older Core), which is what this always did.
    """
    if not entity_id.startswith("sensor."):
        return False
    if reg.get("platform") != "zwave_js":
        return False
    if reg.get("translation_key") == "node_status":
        return True
    if str(reg.get("unique_id") or "").endswith(".node_status"):
        return True
    return entity_id.endswith("_node_status")


def entry_not_loaded(snap: dict, reg: dict) -> bool:
    entry_id = reg.get("config_entry_id")
    if not entry_id:
        return False
    for entry in snap.get("config_entries") or []:
        if isinstance(entry, dict) and entry.get("entry_id") == entry_id:
            return str(entry.get("state") or "") in ENTRY_NOT_LOADED
    return False
