"""House rules: a person's own standing limits, compiled into the gate.

"Never turn the heating above 23." "Don't touch the garage after 22:00."
Sentences like these are what a household would tell a sitter, and until
now the only place to say one was a chat turn that the next conversation
forgot. A rule here is written once in words (`settings_store.house_rules`),
compiled once into a small matcher by a cheap run (`compile_prompt`,
`RULE_SCHEMA`), validated in code (`clean_compiled`), and from then on the
action gate checks every proposed call against it without a model.

Three rules about rules.

**They only ever tighten** (`tighten`). A matching rule can turn the gate's
allow into ask or deny, and an ask into deny; nothing here can turn a deny
or an ask into an allow, and a rule that compiled into something this
module cannot read is no rule at all rather than a loose one. The floors
underneath — the protected list, the voice exposure gate, the tripwire —
are untouched, because this runs after them.

**The matcher is code, the words are the person's.** The compile run turns
a sentence into domains, entities, areas, services, a time window and a
value ceiling; the gate then matches the consequence set against those, so
a page the assistant read cannot argue a rule away — it never reaches the
matcher. The run that compiles is shown the rule and nothing else.

**What a rule could not be compiled into is said**, per rule, with the
reason (`compiled` is None and `error` names it), because a rule a person
believes is guarding the garage and is not is worse than no rule.

Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import atomic_write

FILE = Path(os.environ.get("BRAIN_HOUSE_RULES_FILE", "/data/house_rules.json"))
MAX_RULES = 10
MAX_RULE_CHARS = 200
VERDICTS = ("ask", "deny")
# The values a ceiling may be about: the data keys a service call carries
# that a person thinks of as "how much".
CEILING_KEYS = frozenset({"temperature", "target_temp_high", "brightness",
                          "brightness_pct", "volume_level", "percentage",
                          "position", "humidity"})
_NAME = re.compile(r"^[a-z0-9_]+$")
_ENTITY = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z0-9_]+$")
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "understood": {"type": "boolean"},
        "domains": {"type": "array", "items": {"type": "string"}},
        "entities": {"type": "array", "items": {"type": "string"}},
        "areas": {"type": "array", "items": {"type": "string"}},
        "services": {"type": "array", "items": {"type": "string"}},
        "after": {"type": "string"},
        "before": {"type": "string"},
        "ceiling_key": {"type": "string"},
        "ceiling": {"type": "number"},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "why": {"type": "string"},
    },
    "required": ["understood", "verdict"],
    "additionalProperties": False,
}

COMPILE_SYSTEM = """You turn one household rule, written in plain words, into a matcher a smart-home gate checks every action against. You are shown the rule and nothing else.

Fill in only what the rule says:
- "domains": Home Assistant domains it is about (light, climate, cover, lock, switch, media_player, fan, …).
- "entities": entity ids, only if the rule names one exactly.
- "areas": room names the rule mentions, lower case, as a person says them ("garage", "kids room").
- "services": service names if the rule is about one action ("open_cover", "turn_on", "set_temperature"); leave empty for "don't touch".
- "after" / "before": a time window in 24-hour HH:MM when the rule applies ("after 22:00" → after "22:00", before "06:00" unless it says otherwise).
- "ceiling_key" / "ceiling": a value the rule caps ("never above 23" → ceiling_key "temperature", ceiling 23).
- "verdict": "deny" when the rule says never / don't; "ask" when it says check with me / ask first.
- "understood": false if the rule cannot be expressed this way. Never guess.
- "why": one short sentence restating the rule.

Reply with ONE JSON object and nothing else."""


def digest(rules: list[str]) -> str:
    return hashlib.sha256(json.dumps(rules).encode()).hexdigest()[:16]


def clean_rules(value) -> list[str]:
    """The rule sentences, trimmed and capped, or a ValueError."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("house_rules must be a list of sentences")
    out: list[str] = []
    for item in value:
        text = " ".join(str(item or "").split())[:MAX_RULE_CHARS]
        if text and text not in out:
            out.append(text)
    if len(out) > MAX_RULES:
        raise ValueError(f"at most {MAX_RULES} house rules")
    return out


def compile_prompt(rule: str) -> str:
    return f"THE RULE:\n{json.dumps(rule)}"


def clean_compiled(raw) -> tuple[dict | None, str]:
    """`(matcher, "")` or `(None, why)` — read in code, never trusted."""
    if not isinstance(raw, dict):
        return None, "the compile run's answer could not be read"
    if raw.get("understood") is not True:
        return None, "brAIn could not turn this rule into something it can check"
    verdict = str(raw.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        return None, "the rule did not say whether to ask or refuse"

    def names(key, pattern):
        out = []
        for item in raw.get(key) or []:
            value = str(item or "").strip().lower()
            if not pattern.match(value):
                return None
            out.append(value)
        return out

    domains = names("domains", _NAME)
    entities = names("entities", _ENTITY)
    services = names("services", _NAME)
    if domains is None or entities is None or services is None:
        return None, "the rule named something that is not a domain, entity or service"
    areas = [" ".join(str(a or "").lower().split())[:60]
             for a in raw.get("areas") or [] if str(a or "").strip()]
    if not (domains or entities or areas):
        return None, "the rule does not say what it is about"
    after = str(raw.get("after") or "").strip()
    before = str(raw.get("before") or "").strip()
    for t in (after, before):
        if t and not _TIME.match(t):
            return None, f"{t!r} is not a time"
    out = {"domains": domains, "entities": entities, "areas": areas,
           "services": services, "after": after, "before": before,
           "verdict": verdict,
           "why": " ".join(str(raw.get("why") or "").split())[:200]}
    key = str(raw.get("ceiling_key") or "").strip().lower()
    if key:
        if key not in CEILING_KEYS or not isinstance(raw.get("ceiling"),
                                                     (int, float)):
            return None, "the rule caps a value brAIn cannot check"
        out["ceiling_key"] = key
        out["ceiling"] = float(raw["ceiling"])
    return out, ""


def load() -> dict:
    """`{"digest", "rules": [{text, compiled, error}], "error"}`. Never raises."""
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"digest": "", "rules": [], "error": ""}
    except (OSError, ValueError) as exc:
        return {"digest": "", "rules": [], "error": f"unreadable: {exc}"}
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        return {"digest": "", "rules": [], "error": "not a rules file"}
    rules = []
    for row in data["rules"]:
        if not isinstance(row, dict):
            continue
        matcher, why = clean_compiled({**(row.get("compiled") or {}),
                                       "understood": True}) \
            if isinstance(row.get("compiled"), dict) else (None,
                                                           row.get("error") or "")
        rules.append({"text": str(row.get("text") or "")[:MAX_RULE_CHARS],
                      "compiled": matcher, "error": str(why or "")[:200]})
    return {"digest": str(data.get("digest") or ""), "rules": rules,
            "error": ""}


def save(rows: list[dict], texts: list[str]) -> None:
    if not FILE.parent.is_dir():
        raise OSError(f"{FILE.parent} does not exist")
    atomic_write.write_text(FILE, json.dumps(
        {"digest": digest(texts), "rules": rows, "at": int(time.time())},
        indent=1))


def _in_window(rule: dict, minute: int) -> bool:
    after, before = rule.get("after"), rule.get("before")
    if not after and not before:
        return True
    def mins(t):
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    a = mins(after) if after else 0
    b = mins(before) if before else 24 * 60
    if a <= b:
        return a <= minute < b
    return minute >= a or minute < b       # wraps midnight (22:00–06:00)


def _over_ceiling(rule: dict, calls: list[dict]) -> bool:
    key = rule.get("ceiling_key")
    for call in calls:
        value = (call.get("data") or {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and value > rule["ceiling"]:
            return True
    return False


def check(cons: dict, rules: list[dict], minute: int) -> tuple[str, str] | None:
    """The strictest rule this call breaks, as `(verdict, why)`, or None.

    `minute` is the house's local minute of the day."""
    worst: tuple[str, str] | None = None
    ents = cons.get("entities") or []
    calls = cons.get("calls") or []
    for row in rules:
        rule = row.get("compiled") if isinstance(row, dict) else None
        if not rule:
            continue
        hit = [e for e in ents
               if (not rule["entities"] or e["entity_id"] in rule["entities"])
               and (not rule["domains"] or e["domain"] in rule["domains"])
               and (not rule["areas"] or str(e.get("area") or "").lower()
                    in rule["areas"])]
        if not hit:
            continue
        if rule["services"] and not any(c.get("service") in rule["services"]
                                        for c in calls):
            continue
        if not _in_window(rule, minute):
            continue
        if rule.get("ceiling_key") and not _over_ceiling(rule, calls):
            continue
        why = f"your house rule: “{row.get('text')}”"
        if worst is None or (rule["verdict"] == "deny" and worst[0] != "deny"):
            worst = (rule["verdict"], why)
    return worst


_ORDER = {"allow": 0, "ask": 1, "deny": 2}


def tighten(verdict: str, rule: tuple[str, str] | None) -> tuple[str, bool]:
    """`(verdict, changed)` — the stricter of the two. Never looser."""
    if not rule:
        return verdict, False
    if _ORDER.get(rule[0], 0) > _ORDER.get(verdict, 2):
        return rule[0], True
    return verdict, False


__all__ = ["COMPILE_SYSTEM", "FILE", "MAX_RULES", "RULE_SCHEMA", "VERDICTS",
           "check", "clean_compiled", "clean_rules", "compile_prompt",
           "digest", "load", "save", "tighten"]
