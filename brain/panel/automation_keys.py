"""Home Assistant's two spellings of an automation, and which brAIn writes.

Home Assistant 2024.10 renamed an automation's top-level keys — `trigger:`
to `triggers:`, `condition:` to `conditions:`, `action:` to `actions:` —
and a trigger's `platform:` to `trigger:`, and kept the old spellings
working. Everything brAIn WRITES uses the new ones (`modern`): an
automation brAIn added to somebody's file in the old words reads, in the
editor, as something out of date. Everything brAIn READS takes both
(`shadow`, `checks/automations`), because a person's file is theirs and is
never respelled.

`legacy` is the other direction and has exactly one caller:
`proposals.key_for`, which hashes a proposal's config to know it is the
same proposal. Every key stored before this module existed was taken over
the old spelling, and a hash that moved with the spelling would re-offer
every proposal somebody had already declined. The identity of a change is
the change, not how its keys are spelled.

A leaf: it imports nothing of the panel's.
"""
from __future__ import annotations

# Old top-level key -> new.
TOP = (("trigger", "triggers"), ("condition", "conditions"),
       ("action", "actions"))


def _respell_one(item, old: str, new: str):
    if isinstance(item, dict) and old in item and new not in item:
        return {(new if k == old else k): v for k, v in item.items()}
    return item


def _respell_triggers(items, old: str, new: str):
    """Each trigger's kind key respelled; a single trigger written as a
    mapping stays a mapping."""
    if isinstance(items, list):
        return [_respell_one(i, old, new) for i in items]
    return _respell_one(items, old, new)


def modern(config):
    """The config in Home Assistant's current words. Pure; returns a new
    dict and leaves the one it was handed alone. A key already spelled
    both ways is left as it is rather than one of them dropped."""
    if not isinstance(config, dict):
        return config
    out = {}
    for key, value in config.items():
        new = dict(TOP).get(key)
        out[new if new and new not in config else key] = value
    if "triggers" in out:
        out["triggers"] = _respell_triggers(out["triggers"], "platform",
                                            "trigger")
    return out


def legacy(config):
    """The config in the pre-2024.10 words — for `proposals.key_for` only
    (see the module docstring)."""
    if not isinstance(config, dict):
        return config
    back = {new: old for old, new in TOP}
    out = {}
    for key, value in config.items():
        old = back.get(key)
        out[old if old and old not in config else key] = value
    if "trigger" in out:
        out["trigger"] = _respell_triggers(out["trigger"], "trigger",
                                           "platform")
    return out


def uses_legacy(config) -> bool:
    """Whether a config is spelled the old way anywhere brAIn would respell."""
    return isinstance(config, dict) and modern(config) != config


__all__ = ["TOP", "legacy", "modern", "uses_legacy"]
