"""What a model wrote about the house, in the words the house uses.

A model-written row — a Resident case, an insight card's finding, a chat's
advice — is told to name things the way the homeowner does, and it mostly
does. What it slips on is always the same few things, and each is a
sentence a person has to translate before they can read the card:

  * an **entity id** (`sensor.hall_motion`) where the house has a name for
    it ("Hall motion");
  * a **time in UTC** ("04:00–14:00 UTC", "2026-10-09T04:00:00Z") where
    every other surface in the panel speaks the house's local time;
  * the add-on's own **Supervisor slug** (`abcd1234_brain`), which is how
    brAIn appears in a log line and is "brAIn" everywhere a person reads;
  * **template code** (`{{ today_at('07:00') }}`), quoted out of a trigger
    or a condition, where a person wants the time or the plain word;
  * a device's **IP address** ("calls to 192.168.1.20 keep timing out"),
    which nobody in the house knows their camera or plug by — and its MAC;
  * Home Assistant's **internals**: a trace's step path
    ("action/0/choose/1/sequence/0"), a raw state token ("goes not_home",
    "went to “finish”"), a protocol name ("answers ARP"), "1 hours".

So this is the deterministic half of the rule the prompts state: it turns
what it can recognise and leaves everything else exactly as it was. An id
the house has no name for stays an id here — a made-up name is worse than
the id — and a time it cannot parse keeps its words; on screen `ids` then
says such an id as the kind of thing it is ("the voice service", #774). It is pure over what it
is handed (the names map, the zone, the clock), imports nothing of the
panel's, and never raises: a cleanup that failed returns the text it was
given. (`plain_words` is the other half of the same rule, for brAIn's
own machinery: what its producers and jobs are called.)
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Mapping

# An entity id in prose. The shape `server._ENTITY_IN_TEXT_RE` reads, with
# an optional backtick either side so `sensor.x` loses its code quotes too.
_ENTITY_RE = re.compile(r"`?\b([a-z_]+)\.([a-z0-9_]+)\b`?")
# The add-on's Supervisor slug: an 8-hex repository prefix (or `local`)
# and `_brain`, optionally with the `addon_` a container name carries.
_SLUG_RE = re.compile(r"\b(?:addon_)?(?:[0-9a-f]{8}|local)_brain\b")
# An ISO stamp that says it is UTC: a `Z`, `+00:00`, or the word after it.
_ISO_UTC_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2})[T ](\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?"
    r"(?:\s*(?:Z|\+00:?00)\b|Z|\+00:?00|\s+(?:UTC|GMT)\b)")
# A clock time, or a range of two, followed by UTC or GMT.
_CLOCK_UTC_RE = re.compile(
    r"\b(\d{1,2}):(\d{2})(?:\s*(–|—|-|to)\s*(\d{1,2}):(\d{2}))?"
    r"\s*\(?(?:UTC|GMT)\)?")


def _names_for(names: Mapping | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for eid, row in (names or {}).items():
        name = row.get("name") if isinstance(row, dict) else row
        name = str(name or "").strip()
        if name and name != eid:
            out[str(eid)] = name
    return out


def _local(day: dt.date, hour: int, minute: int,
           tz: dt.tzinfo | None) -> dt.datetime | None:
    if hour > 23 or minute > 59:
        return None
    moment = dt.datetime(day.year, day.month, day.day, hour, minute,
                         tzinfo=dt.timezone.utc)
    return moment.astimezone(tz) if tz is not None else moment


def _clock(moment: dt.datetime) -> str:
    return moment.strftime("%H:%M")


def _date_clock(moment: dt.datetime) -> str:
    return f"{moment.day} {moment.strftime('%b')} {_clock(moment)}"


def entities(text: str, names: Mapping | None) -> str:
    """Every id the names map knows, as its name; the rest left alone."""
    known = _names_for(names)
    if not known or not text:
        return text

    def swap(m: re.Match) -> str:
        eid = f"{m.group(1)}.{m.group(2)}"
        return known.get(eid, m.group(0))

    out = _ENTITY_RE.sub(swap, text)
    # "Hall motion (sensor.hall_motion)" became "Hall motion (Hall motion)".
    for name in set(known.values()):
        out = re.sub(re.escape(name) + r"\s*\(\s*" + re.escape(name)
                     + r"\s*\)", name, out)
    return out


def times(text: str, tz: dt.tzinfo | None,
          now: float | None = None) -> str:
    """UTC times as the house's local time, where they can be read."""
    if not text or ("UTC" not in text and "GMT" not in text
                    and not re.search(r"\d(?:Z|\+00:?00)\b", text)):
        return text
    today = (dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
             if now is not None else dt.datetime.now(dt.timezone.utc).date())

    def iso(m: re.Match) -> str:
        try:
            day = dt.date.fromisoformat(m.group(1))
        except ValueError:
            return m.group(0)
        moment = _local(day, int(m.group(2)), int(m.group(3)), tz)
        return _date_clock(moment) if moment else m.group(0)

    def clock(m: re.Match) -> str:
        first = _local(today, int(m.group(1)), int(m.group(2)), tz)
        if first is None:
            return m.group(0)
        if not m.group(3):
            return _clock(first)
        second = _local(today, int(m.group(4)), int(m.group(5)), tz)
        if second is None:
            return m.group(0)
        dash = "–" if m.group(3) in ("-", "—", "–") else f" {m.group(3)} "
        return f"{_clock(first)}{dash}{_clock(second)}"

    return _CLOCK_UTC_RE.sub(clock, _ISO_UTC_RE.sub(iso, text))


# Home Assistant template code: `{{ … }}` expressions and `{% … %}`
# statements, optionally inside backticks. A model quoting a trigger or a
# condition writes them verbatim, and a person reads Jinja.
_TEMPLATE_EXPR_RE = re.compile(r"`?\{\{.*?\}\}`?", re.S)
_TEMPLATE_STMT_RE = re.compile(r"`?\{%.*?%\}`?", re.S)
# A clock time quoted inside a template (`today_at('07:00')`).
_QUOTED_CLOCK_RE = re.compile(r"""['"](\d{1,2}:\d{2})(?::\d{2})?['"]""")


def templates(text: str) -> str:
    """Template code as plain words: an expression that only names a clock
    time is that time, any other expression is "a template", and a
    statement (`{% if … %}`) is dropped. Text with no template is returned
    exactly as it was."""
    if not text or ("{{" not in text and "{%" not in text):
        return text

    def expr(m: re.Match) -> str:
        clocks = _QUOTED_CLOCK_RE.findall(m.group(0))
        return clocks[0] if len(clocks) == 1 else "a template"

    out = _TEMPLATE_EXPR_RE.sub(expr, text)
    out = _TEMPLATE_STMT_RE.sub("", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return re.sub(r"\s+([.,;:])", r"\1", out).strip()


# A hole where a value belongs: what a step somebody is meant to carry out
# must never hold (#446). "a template" is the store's own words for template
# code (`templates`), right in prose about a trigger ("its trigger is a
# template") and a hole only when it stands where a value goes — quoted, or
# after a colon or an equals sign. Likewise an ellipsis standing for a value.
_PLACEHOLDER_RE = re.compile(
    r"[\"'“‘]\s*a (?:template|value|number|time|name|entity)\s*[\"'”’]"
    r"|[:=]\s*a (?:template|value)\b"
    r"|\b(?:to|with|use|enter|add|put|type)\s+a template\b"
    r"|<[A-Za-z][A-Za-z _-]{1,30}>"
    r"|\bYOUR_\w+"
    r"|\byour[_-](?:entity|device|sensor|value)\w*"
    r"|\bTODO\b|\bTBD\b|\bFIXME\b"
    r"|\b[xX]{3,}\b"
    r"|[:=]\s*(?:…|\.\.\.)"
    r"|[\"'“‘(\[]\s*(?:…|\.\.\.)\s*[\"'”’)\]]"
    r"|\{\{|\{%")


def placeholder(text: str) -> str:
    """The first placeholder ``text`` holds, or "" — a sentence holding one
    is not a step anybody can carry out."""
    m = _PLACEHOLDER_RE.search(str(text or ""))
    return m.group(0) if m else ""


# A step that hands the household a choice or a lookup brAIn could have
# settled itself (#536): "either … or …", "if not, …", "also confirm …",
# "if asked". A what-to-do is ONE step, already chosen from what brAIn read.
# Only an unresolved fork: "either way" has settled it, and "check whether
# the filter is clogged" or "re-pair it if needed" is a step in the world
# that only a person can take, so the floor leaves those to the prompts.
_FORK_RE = re.compile(
    r"\beither\b(?!\s+way\b)[^.;:!?]{2,}?\bor\b"
    r"|\bif\s+(?:not|so|it\s+(?:does|is|did|was)n'?t|that\s+"
    r"(?:does|did)n'?t(?:\s+work)?|that\s+fails)\s*,"
    r"|\balso\s+(?:confirm|verify|make\s+sure|ensure)\b"
    r"|\bif\s+(?:asked|requested|you\s+(?:want|prefer|like|wish))\b"
    r"|\bwhichever\b", re.I)


def fork(text: str) -> str:
    """The first unresolved fork ``text`` hands a person, or "" — a step
    that leaves the choice to somebody is not a step they can carry out."""
    m = _FORK_RE.search(str(text or ""))
    return m.group(0) if m else ""


# An IPv4 address, optionally with a port, not inside a longer run of dots
# and digits (a version number like 2026.10.1 is three parts and never
# matches; four parts each 0-255 is an address).
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4 = (r"(?<![\d.])" + _OCTET + r"(?:\." + _OCTET + r"){3}"
         r"(?::\d{1,5})?(?![\d]|\.\d)")
# "(192.168.1.20)" and "at/on 192.168.1.20" say nothing the sentence needs:
# the thing is already named ("the gateway at 10.0.0.5" is the gateway).
_IPV4_ASIDE_RE = re.compile(
    r"\s*\(\s*(?:IP(?:\s+address)?:?\s*)?" + _IPV4 + r"\s*\)", re.I)
_IPV4_AT_RE = re.compile(
    r"\s+(?:at|on)\s+(?:the\s+)?(?:IP(?:\s+address)?\s+)?" + _IPV4, re.I)
# Anything left is the address standing in for the thing: "its address".
_IPV4_RE = re.compile(r"(?:\b(?:the\s+)?IP(?:\s+address)?\s+)?" + _IPV4,
                      re.I)


def addresses(text: str) -> str:
    """IPv4 addresses out of a sentence a person reads: an aside or an
    "at <address>" is dropped (the thing is already named), and any other
    is "its address". Text with none is returned exactly as it was."""
    if not text or not re.search(_IPV4, text):
        return text
    out = _IPV4_ASIDE_RE.sub("", text)
    out = _IPV4_AT_RE.sub("", out)
    out = _IPV4_RE.sub("its address", out)
    return re.sub(r"[ \t]{2,}", " ", out)


# A MAC address: an aside "(aa:bb:…)" is dropped, an "at <mac>" too, and
# any other is "its hardware address" — nobody knows a hub by it.
_MAC = r"(?<![\w:])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![\w:])"
_MAC_ASIDE_RE = re.compile(r"\s*\(\s*(?:MAC:?\s*)?" + _MAC + r"\s*\)", re.I)
_MAC_AT_RE = re.compile(r"\s+(?:at|on)\s+" + _MAC)
_MAC_RE = re.compile(r"(?:\bMAC(?:\s+address)?\s+)?" + _MAC, re.I)
# A trace's step path ("action/0/choose/1/sequence/0"): the step by its
# key in the config, which a person never sees.
_TRACE_PATH = (r"(?:actions?|sequence|choose|then|else|default|conditions?|"
               r"triggers?|parallel|repeat)/\d+(?:/[a-z_]+(?:/\d+)?)*")
_TRACE_AT_RE = re.compile(r"\bat (?:the )?step " + _TRACE_PATH)
_TRACE_RE = re.compile(r"\b(?:step )?" + _TRACE_PATH)
# A state token where Home Assistant's frontend shows a word, and the one
# protocol a log line about a device going missing always names.
_RAW_STATES = {"not_home": "away", "heat_cool": "heat/cool",
               "fan_only": "fan only", "armed_away": "armed away",
               "armed_home": "armed home", "armed_night": "armed night",
               "armed_vacation": "armed vacation",
               "below_horizon": "below the horizon",
               "above_horizon": "above the horizon"}
_RAW_STATE_RE = re.compile(r"`?\b(" + "|".join(_RAW_STATES) + r")\b`?")
_QUOTED_FINISH_RE = re.compile(r"([“\"'])finish([”\"'])")
_PROTOCOL_RE = re.compile(r"\bARP(?: (?:requests?|replies|lookups?|probes?))?\b")
_ONE_PLURAL_RE = re.compile(r"\b1 (hour|minute|day|second|week)s\b")


def internals(text: str) -> str:
    """Home Assistant's internals as the words a person reads: a MAC out,
    a trace step path as "one of its steps", a raw state token as the
    frontend's word, ARP as "network lookups", and "1 hours" as "1 hour".
    Text with none is returned exactly as it was."""
    if not text:
        return text
    out = _MAC_ASIDE_RE.sub("", text)
    out = _MAC_AT_RE.sub("", out)
    out = _MAC_RE.sub("its hardware address", out)
    out = _TRACE_AT_RE.sub("at one of its steps", out)
    out = _TRACE_RE.sub("one of its steps", out)
    out = _RAW_STATE_RE.sub(lambda m: _RAW_STATES[m.group(1)], out)
    out = _QUOTED_FINISH_RE.sub(r"\1finished\2", out)
    out = _PROTOCOL_RE.sub("network lookups", out)
    out = _ONE_PLURAL_RE.sub(r"1 \1", out)
    return out if out != text else text


def slug(text: str) -> str:
    """The add-on's Supervisor slug as the name people know it by."""
    return _SLUG_RE.sub("brAIn", text) if text else text


def plain(text: str, names: Mapping | None = None,
          tz: dt.tzinfo | None = None, now: float | None = None) -> str:
    """`text` with the slips turned into the house's own words."""
    if not isinstance(text, str) or not text:
        return text
    try:
        return entities(slug(times(addresses(internals(templates(text))),
                                   tz, now)), names)
    except Exception:  # noqa: BLE001 — a cleanup must never cost the row
        return text


# ---------------------------------------------------------------------------
# A log line, said rather than quoted
# ---------------------------------------------------------------------------
#
# A finding made of log lines used to paste the line — `Error fetching data:
# 503, message='Service Unavailable', url=URL('…')` — and then say its
# count again in other words. The line is somebody else's text, written
# for the integration's developer: a status code, a JSON fragment and a
# URL say nothing to the person the card is for. What they need is what
# the error MEANS, which is one of a handful of things, first match wins.

_LOG_MEANINGS = (
    (re.compile(r"rate.?limit|too many requests|\b429\b|throttl", re.I),
     "the service it talks to is turning requests away because it is "
     + "being asked too often"),
    (re.compile(r"unauthori[sz]ed|forbidden|access denied|permission denied"
                r"|invalid (?:auth|credentials?|token|api.?key|password)"
                r"|(?:authentication|login|sign.?in) (?:failed|refused|error)"
                r"|\b40[13]\b", re.I),
     "its sign-in with the device or service is being refused"),
    (re.compile(r"timed? ?out|timeout|did not respond|not responding|no response",
                re.I),
     "a device or service it talks to did not answer in time"),
    (re.compile(r"connection (?:refused|reset|aborted|error|failed|lost)"
                r"|cannot connect|can't connect|could not connect|unable to connect"
                r"|failed to connect|unreachable|no route to host|host is down"
                r"|name or service not known|disconnected|connect(?:or)?error",
                re.I),
     "it could not reach the device or service it talks to"),
    (re.compile(r"\b5\d\d\b|internal server error|bad gateway"
                r"|service unavailable|server error", re.I),
     "the service it talks to had a fault on its own side"),
    (re.compile(r"missing or not currently available|not currently available"
                r"|\bunavailable\b", re.I),
     "something it tried to use is unavailable"),
    (re.compile(r"\b404\b|not found|no such", re.I),
     "it asked for something that is no longer there"),
    (re.compile(r"json|decod|pars(?:e|ing)|unexpected (?:response|data|value)"
                r"|invalid (?:response|data|value)|[{}]", re.I),
     "it got an answer it could not make sense of"),
)
_LOG_MEANING_ELSE = "it logged an error"


def log_meaning(message: str) -> str:
    """What a logged error means, in plain words, never quoting it."""
    return known_log_meaning(message) or _LOG_MEANING_ELSE


def known_log_meaning(message: str) -> str:
    """What a logged error means when its line says so, or "".

    A finding prints only this: an error none of `_LOG_MEANINGS` reads is
    one whose meaning brAIn does not know, and "something it was doing
    failed" under it was a sentence that said nothing while sounding like
    a reading (#725). The sentence then ends at what IS known — who
    logged it, how often, when."""
    text = str(message or "")
    for pattern, meaning in _LOG_MEANINGS:
        if pattern.search(text):
            return meaning
    return ""


# What marks a sentence as pasting a log rather than saying something: a
# quoted span, code quotes, an HTTP status said as one, a JSON or key=value
# fragment, a URL, an exception's class name, a traceback.
_RAW_LOG_RE = re.compile(
    r"[“”`]|\"[^\"]{3,}\"|'[^'\s][^']{6,}'"
    r"|\b(?:HTTP|status(?: code)?|error|code|response)[\s:=]*[1-5]\d\d\b"
    r"|\b[1-5]\d\d\b(?=\s*[,:)]|\s+(?:error|response|status|Not Found"
    r"|Unauthori[sz]ed|Forbidden|Internal|Bad Gateway|Service Unavailable"
    r"|Too Many))"
    r"|[{}\[\]]|\b\w+='|\w+=URL|https?://"
    r"|\b[A-Z][A-Za-z]+(?:Error|Exception)\b|Traceback", re.I)
_LOG_SENTENCES = re.compile(r"(?<=[.!?])\s+")


def without_log_text(text: str) -> str:
    """``text`` less every sentence that pastes a log line, a status code
    or JSON instead of saying what it means."""
    if not text:
        return text
    kept = [s for s in _LOG_SENTENCES.split(str(text))
            if s and not _RAW_LOG_RE.search(s)]
    return " ".join(kept).strip()


_COUNT_WORDS = ("zero", "once", "twice", "three", "four", "five", "six",
                "seven", "eight", "nine", "ten", "eleven", "twelve")


def says_count(text: str, count: int) -> bool:
    """Whether ``text`` already states ``count`` — as a number, or for a
    small one in words — so a sentence after it does not say it again."""
    low = str(text or "").lower()
    if re.search(rf"(?<![\d.,]){int(count)}(?![\d.,]\d)", low):
        return True
    if 0 <= count < len(_COUNT_WORDS):
        return re.search(rf"\b{_COUNT_WORDS[count]}\b", low) is not None
    return False


# ---------------------------------------------------------------------------
# brAIn about itself: one narrator, one stored answer, no developer text
# ---------------------------------------------------------------------------
#
# A house's findings said "My spoken voice changed from voice A to voice B"
# beside one saying the household chose voice C and a card saying B was
# already the voice — each a model's memory — and one told the owner to edit
# "line 27 of chat_identity.md" and call `note_personality_change`, in the
# first person beside rows saying "brAIn". `self_said` is the one pass:
# "I"/"my" and the household's name for brAIn become "brAIn" (a surface that
# speaks the name turns it back, `personality.speak`, so it is one name and
# never two); a sentence about brAIn's voice or name is the stored answer or
# nothing; and with ``dev`` a sentence holding a file path, a tool name, an
# id or a model id goes, because it is brAIn's own housekeeping in words
# only its developer reads.

_QUOTE_SPAN = re.compile(r"“[^”]*”|\"[^\"]*\"")
_I_CONTRACTIONS = (
    (re.compile(r"\bI['’]m\b"), "brAIn is"), (re.compile(r"\bI am\b"), "brAIn is"),
    (re.compile(r"\bI['’]ve\b"), "brAIn has"),
    (re.compile(r"\bI['’]ll\b"), "brAIn will"),
    (re.compile(r"\bI['’]d\b"), "brAIn would"),
    (re.compile(r"\bI (?:don['’]t|do not)\b"), "brAIn does not"),
    (re.compile(r"\bI (?:didn['’]t|did not)\b"), "brAIn did not"),
)
_KEEP_VERBS = frozenset(
    "can could will would should may might must shall did was had need "
    "cannot".split())
_IRREGULAR = {"have": "has", "do": "does", "go": "goes", "am": "is",
              "be": "is", "were": "was"}
_ADVERB = r"(?:(?:also|still|just|now|only|never|always|already|often|" \
          r"usually|then|first|really|once)\s+)?"
_I_VERB = re.compile(r"\bI\s+(" + _ADVERB + r")([a-z]+)\b")
_MY = re.compile(r"\b[Mm]y\b")
_MINE = re.compile(r"\bmine\b")
_MYSELF = re.compile(r"\bmyself\b")
_ME = re.compile(r"(?<![\w-])me\b")

# A sentence that states which voice brAIn speaks with, or what it is
# called, rather than something about the house.
_VOICE_SENTENCE = re.compile(
    r"(?:\b(?:brAIn['’]s|my|its|the assistant['’]s)\s+(?:\w+\s+)?voice\b"
    r"|\bvoice\b[^.!?]*\b(?:use[sd]?|using|changed|switched|is now|set to|"
    r"chose|chosen|picked|now|already)\b"
    r"|\b(?:use[sd]?|using|now)\b[^.!?]*\bvoice\b"
    r"|\b(?:speaks?|spoke|announces?|talks?)\s+(?:now\s+)?(?:with|in|using)"
    r"\s+(?:the\s+)?[A-Z]\w*)", re.I)
# ...and only one about brAIn: "the Voice PE satellite uses Piper" is the
# house's.
_ABOUT_BRAIN = re.compile(r"\bbrAIn\b|\bassistant\b|\bannounc", re.I)
_NAME_SENTENCE = re.compile(
    r"\b(?:brAIn|the assistant|it)\s+(?:is|was)\s+(?:now\s+)?(?:called|"
    r"named)\b|\b(?:brAIn['’]s|my|its)\s+name\s+(?:is|was|changed)\b"
    r"|\b(?:calls?|named|renamed)\s+(?:brAIn|the assistant|me)\b", re.I)

# What only a developer reads: a file path or name, a line number, a tool
# or function name, an entity id, a model id, code in backticks.
_DEV_TOKEN = re.compile(
    r"`[^`]+`"
    r"|(?<![\w/])(?:/config|/data|/opt|/usr)/\S*"
    r"|\b[\w.-]+\.(?:md|json|ya?ml|py|sh|js|txt|log|toml)\b"
    r"|\bline\s+\d+\b"
    r"|\bmcp__\w+"
    r"|\b(?:claude|gpt|gemini)-[\w.-]+"
    r"|\b(?:opus|sonnet|haiku)[\s-]?\d[\w.-]*"
    r"|(?<![\w.])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w.])"
    r"|\b[a-z_]+\.[a-z0-9_]+\b", re.I)


# The same assistant under other names a model reaches for: "the
# companion", "the in-game companion", "the brAIn engine". One assistant,
# one name (the companion APP is the phone's, and stays).
_THE_COMPANION = re.compile(r"\bthe\s+companion\b(?!\s+app\b)", re.I)


# brAIn's own parts named in a sentence a person reads (#832), each an
# exact phrase that names brAIn: "the in-game brAIn companion", "a brAIn
# chat/terminal session", "a quick run of brAIn". A phrase without brAIn
# in it is left alone: "the dishwasher finished a quick run" and "an SSH
# terminal session" are the house's own words.
_IN_GAME = re.compile(
    r"\b(?:the\s+|an?\s+)?(?:in-game|minecraft)\s+(?:brAIn\s+)?companion\b",
    re.I)
_BRAIN_COMPANION = re.compile(r"\b(?:the\s+)?brAIn\s+companion\b|"
                              r"\bbrAIn\s+engine\b", re.I)
_BRAIN_CHAT_SESSION = re.compile(
    r"(?P<art>\b(?:an?|the|each|every|one|any|this|that|another)\s+)?"
    r"\bbrAIn(?:['\u2019]s)?\s+(?:chat|terminal)"
    r"(?:\s*(?:/|\bor\b|\band\b)\s*(?:chat|terminal))?[\s-]+session(?P<pl>s?)\b",
    re.I)
_BRAIN_QUICK_RUN = re.compile(
    r"(?P<ask>\bask\s+in\s+)?(?:\b(?:an?|the|one|each|every)\s+)?"
    r"\bquick[\s-]+runs?\s+(?:of|by|from|with)\s+brAIn\b"
    r"|\bbrAIn(?:['\u2019]s)?\s+quick[\s-]+runs?\b(?!\s+(?:of|on|for)\b)",
    re.I)


def one_name(text: str) -> str:
    """``text`` with the assistant's other names turned to "brAIn" (#832):
    "the companion", "the in-game companion" (brAIn in the game), "the
    brAIn engine"; a brAIn chat or terminal session is a conversation with
    brAIn in Ask, and a quick run of brAIn is simply brAIn. Only these
    exact phrases change; nothing that is not brAIn is renamed."""
    if not isinstance(text, str) or not text:
        return text
    out = _IN_GAME.sub("brAIn in the game", text)
    out = _THE_COMPANION.sub("brAIn", out)
    out = _BRAIN_COMPANION.sub("brAIn", out)

    def session(m: re.Match) -> str:
        art = m.group("art") or ""
        if art.strip().lower() == "an":
            art = art[0] + " "
        said = f"conversation{m.group('pl')} with brAIn in Ask"
        return art + said if art else _cap_at_start(m.string, m.start(), said)

    def quick(m: re.Match) -> str:
        ask = m.group("ask")
        return f"{ask.split()[0]} brAIn" if ask else "brAIn"

    out = _BRAIN_CHAT_SESSION.sub(session, out)
    return _BRAIN_QUICK_RUN.sub(quick, out)


def _third_person(sentence: str) -> str:
    out = one_name(sentence)
    for pattern, repl in _I_CONTRACTIONS:
        out = pattern.sub(repl, out)

    def verb(m: re.Match) -> str:
        adverb, word = m.group(1), m.group(2)
        low = word.lower()
        if low in _IRREGULAR:
            word = _IRREGULAR[low]
        elif low in _KEEP_VERBS or low.endswith("ed"):
            pass
        elif re.search(r"(?:s|sh|ch|x|z|o)$", low):
            word += "es"
        elif re.search(r"[^aeiou]y$", low):
            word = word[:-1] + "ies"
        else:
            word += "s"
        return f"brAIn {adverb}{word}"

    out = _I_VERB.sub(verb, out)
    out = re.sub(r"\bI\b", "brAIn", out)
    out = _MYSELF.sub("itself", out)
    out = _MY.sub("brAIn's", out)
    out = _MINE.sub("brAIn's", out)
    out = _ME.sub("brAIn", out)
    return out


def _outside_quotes(text: str, fn) -> str:
    """``fn`` over ``text`` less what it quotes: a person's own words are
    theirs."""
    out, last = [], 0
    for m in _QUOTE_SPAN.finditer(text):
        out.append(fn(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(fn(text[last:]))
    return "".join(out)


def _strip_dev(sentence: str) -> str:
    out = _DEV_TOKEN.sub(" ", sentence)
    out = re.sub(r"\b(?:of|in|to|call|and|the|with|on)\s+(?=[\s,;.]|$)", "", out)
    out = re.sub(r"\s+([,;.!?])", r"\1", re.sub(r"\s{2,}", " ", out))
    return re.sub(r"^[\s,;]+|[\s,;]+$", "", out).strip()


def self_said(text: str, name: str = "brAIn", voice: str = "",
              dev: bool = False, keep: bool = False) -> str:
    """``text`` written by a model, with brAIn as its one narrator.

    ``name`` is the assistant's stored name (`personality.assistant_name`)
    and ``voice`` its stored voice (`personality.identity`), "" when none
    is stored. With ``dev``, sentences holding developer text go; with
    ``keep`` (a row's `text`, its key) a sentence is never dropped, only
    cleaned, so the row keeps a sentence."""
    if not isinstance(text, str) or not text.strip():
        return text
    out = text
    if name and name != "brAIn":
        out = re.sub(r"(?<![\w])" + re.escape(name) + r"(?![\w])", "brAIn", out)
    out = _outside_quotes(out, _third_person)
    sentences = [s for s in _LOG_SENTENCES.split(out) if s.strip()]
    kept: list[str] = []
    said_identity = False
    for sentence in sentences:
        if _ABOUT_BRAIN.search(sentence) and (
                _VOICE_SENTENCE.search(sentence)
                or _NAME_SENTENCE.search(sentence)):
            if voice and _VOICE_SENTENCE.search(sentence):
                if not said_identity:
                    kept.append(f"brAIn's spoken voice is {voice}.")
                    said_identity = True
                continue
            # A name claim says nothing the surfaces do not: each speaks the
            # stored name (`personality.speak`) wherever the prose says brAIn.
            if keep and not kept and sentence is sentences[-1]:
                kept.append(sentence)
            continue
        if dev and _DEV_TOKEN.search(sentence):
            if keep:
                cleaned = _strip_dev(sentence)
                if cleaned:
                    kept.append(cleaned)
            continue
        kept.append(sentence)
    if keep and not kept:
        return out
    return " ".join(kept).strip()


# brAIn's upkeep: it speaking of itself, or of its own instructions,
# personality, voice or tooling. Merely naming brAIn ("the house book brAIn
# writes") is not: a house row keeps its ids for the names map.
_SELF_RE = re.compile(
    r"\b(?:I|I['’]m|I['’]ve|My|my|me|myself)\b|\bpersonality\b|"
    r"\binstructions?\b|\bwake word\b|\bvoice\b|\bmcp__|\bclaude-|"
    r"\b[\w-]+\.md\b")


def about_self(*texts) -> bool:
    """Whether a row's words are about brAIn itself."""
    return any(_SELF_RE.search(str(t or "")) for t in texts)


# ---------------------------------------------------------------------------
# "What to do" from what brAIn read
# ---------------------------------------------------------------------------
#
# Fixes told the owner to "check that it is switched on" about a plug brAIn
# reads, to "restart the router or DNS server" over one device failing while
# its siblings answered, and to "stop the pump now" on one reading. A fix
# never asks somebody to look at what brAIn can read, never blames the
# network when the rest of the integration answers, and is urgent only when
# two readings agree.

_SELF_CHECK = re.compile(
    r"\b(?:check|make sure|confirm|verify|see)\b(?:\s+(?:that|whether|if))?"
    r"[^.!?]{0,60}?\b(?:switched on|turned on|plugged in|powered(?: on)?|"
    r"has power|still has power|reachable|online|connected|on the network|"
    r"available)\b"
    r"|\bcheck (?:its|the|that)?\s*(?:state|status|logs?|traces?|history|"
    r"settings)\b"
    r"|\b(?:check|look at|read) (?:the )?(?:errors?|logs?)\b"
    r"|\bSettings\s*>\s*System\s*>\s*Logs\b"
    r"|\bwatch (?:whether|if) it (?:continues|happens again)\b", re.I)
_NETWORK_BLAME = re.compile(
    r"\b(?:router|dns|modem|internet|isp|access point|wi-?fi network|"
    r"network switch)\b", re.I)
_URGENT = re.compile(
    r",?\s*\b(?:right away|immediately|at once|urgently|"
    r"as soon as possible|asap|right now|without delay|"
    r"before it['’]?s too late)\b|,?\s+now(?=\s*[.!,;]|\s*$)", re.I)


def _drop_sentences(text: str, pattern) -> str:
    if not text:
        return text
    kept = [s for s in _LOG_SENTENCES.split(str(text))
            if s and not pattern.search(s)]
    return " ".join(kept).strip()


def without_self_checks(text: str) -> str:
    """``text`` less every sentence asking somebody to check what brAIn
    reads itself: a power state, a connection, a log, a setting."""
    return _drop_sentences(text, _SELF_CHECK)


def without_network_blame(text: str) -> str:
    """``text`` less every sentence sending somebody to the router, DNS or
    the internet — for a fault whose integration's other devices answer."""
    return _drop_sentences(text, _NETWORK_BLAME)


def _reading(value) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(m.group(0)) if m else None


def readings_agree(evidence) -> bool:
    """Whether a row's evidence holds two readings that agree: the last two
    of one entity, numbers within a tenth of each other (or a degree), or
    the same words."""
    rows = [e for e in evidence or [] if isinstance(e, dict)
            and str(e.get("value") or "").strip()]
    by_entity: dict[str, list] = {}
    for e in rows:
        by_entity.setdefault(str(e.get("entity") or ""), []).append(e)
    for seen in by_entity.values():
        if len(seen) < 2:
            continue
        a, b = seen[-2], seen[-1]
        x, y = _reading(a.get("value")), _reading(b.get("value"))
        if x is not None and y is not None:
            if (x >= 0) == (y >= 0) and abs(x - y) <= max(
                    1.0, 0.1 * max(abs(x), abs(y))):
                return True
        elif str(a.get("value")).strip().lower() == \
                str(b.get("value")).strip().lower():
            return True
    return False


def calm(text: str, readings_agree: bool) -> str:
    """``text`` with its urgency taken off unless two readings agree."""
    if readings_agree or not text or not _URGENT.search(text):
        return text
    out = _URGENT.sub("", text)
    out = re.sub(r"\s+([,.;!?])", r"\1", out).replace("!", ".")
    return re.sub(r"\s{2,}", " ", out).strip()


# ---------------------------------------------------------------------------
# The household is "you" (#562)
# ---------------------------------------------------------------------------
#
# One house's look conclusions said "The homeowner said…" and "The owner
# wants…" beside cards saying "You've marked…", and a finding called the
# dashboard "Morph": three narrators' habits on one screen. The prompts say
# both (`prompt_kit.ADDRESS`); this is the floor under a model's row for the
# first — "Morph" stays the prompts' job, because brAIn's own questions about
# Morph's code name it on purpose (`tests/test_morph_suggestion_yes.py`). It only
# rewrites what cannot mean anybody else: "the homeowner" anywhere, and "the
# owner" / "the user" as the subject opening a sentence with a verb after it
# ("The owner wants…", "The user marked…"), and their possessive ("the
# owner's" → "your", never "the owner's manual"). "The owner of the car next
# door" and "a previous owner left it" are somebody else, and stay.

_PRESENT = {
    "is": "are", "was": "were", "has": "have", "does": "do",
    "isn't": "aren't", "wasn't": "weren't", "hasn't": "haven't",
    "doesn't": "don't", "isn’t": "aren’t", "wasn’t": "weren’t",
    "hasn’t": "haven’t", "doesn’t": "don’t",
}
_S_VERBS = frozenset(
    "says wants asks prefers likes uses keeps needs goes tries knows thinks "
    "expects plans works leaves sleeps travels marks notes mentions confirms "
    "dismisses ignores replies answers chooses sets puts turns runs reads "
    "sees watches wishes feels considers agrees disagrees means opens "
    "closes starts stops lets gets".split())
_PAST = frozenset(
    "said told chose put set wrote thought felt meant knew saw ran got let "
    "left kept made gave took".split())
_YOU_ADVERB = (r"(?:(?:also|already|previously|just|still|often|usually|"
               r"always|never|recently|explicitly|once)\s+)?")
_HOMEOWNER = r"home[\s-]?owner"
_OWNER_POSSESSIVE = re.compile(
    r"\b([Tt])he\s+(?:" + _HOMEOWNER + r"|owner|user)['’]s\b"
    r"(?!\s+(?:manual|guide|handbook|instructions)\b)")
_HOMEOWNER_SUBJECT = re.compile(
    r"\b([Tt])he\s+" + _HOMEOWNER + r"s?\b(\s+" + _YOU_ADVERB + r")?([\w'’]+)?")
_OWNER_SUBJECT = re.compile(
    r"(^|(?<=[.!?]\s)|(?<=[.!?]\s\s)|(?<=[\"“(]))The\s+(?:owner|user)\b"
    r"(\s+" + _YOU_ADVERB + r")([\w'’]+)")


def _as_you(verb: str) -> str | None:
    """``verb`` with "you" as its subject, or None when it is not a verb
    this floor knows."""
    low = verb.lower()
    if low in _PRESENT:
        return _PRESENT[low]
    if low in _S_VERBS:
        if low.endswith("ies"):
            return verb[:-3] + "y"
        if re.search(r"(?:ss|sh|ch|x|z|o)es$", low):
            return verb[:-2]
        return verb[:-1]
    if low in _PAST or (low.endswith("ed") and len(low) > 3):
        return verb
    return None


def _cap(word: str, upper: bool) -> str:
    return word[:1].upper() + word[1:] if upper else word


def _household(text: str) -> str:
    out = _OWNER_POSSESSIVE.sub(lambda m: _cap("your", m.group(1) == "T"), text)

    def homeowner(m: re.Match) -> str:
        # Only as the subject of a verb this floor knows: "tell the
        # homeowner" is an object, and "tell you" is not always a sentence.
        adverb, word = m.group(2) or "", m.group(3) or ""
        verb = _as_you(word) if word else None
        if verb is None:
            return m.group(0)
        return _cap("you", m.group(1) == "T") + adverb + verb

    out = _HOMEOWNER_SUBJECT.sub(homeowner, out)

    def owner(m: re.Match) -> str:
        verb = _as_you(m.group(3))
        if verb is None:
            return m.group(0)
        return m.group(1) + "You" + m.group(2) + verb

    out = _OWNER_SUBJECT.sub(owner, out)

    return out


def household(text: str) -> str:
    """``text`` (a model's, for a person) addressing the household as "you".
    Quoted words are left alone,
    and text with nothing to change comes back exactly as it was."""
    if not isinstance(text, str) or not text:
        return text
    try:
        out = _outside_quotes(text, _household)
    except Exception:  # noqa: BLE001 — a cleanup must never cost the row
        return text
    return out if out != text else text


# ---------------------------------------------------------------------------
# Technical details: kept, but not in the sentence (#563)
# ---------------------------------------------------------------------------
#
# Findings about brAIn's own files showed the owner
# "/config/.brain/instructions/chat_identity.md line 27", a tool name
# ("note_personality_change"), a hex error code ("0x0c") and a firmware
# build string. Each is true and worth keeping for whoever reads the
# Details, and none is a word a household reads. `technical` takes them
# out of the sentence (a path or file becomes "a configuration file", a
# hex code "an error code", a tool "one of brAIn's tools", a build string
# its version) and hands them back, so the row keeps them in `technical`.
# A version number ("firmware 1.2 is fine", 2026.10.1) and a clock time
# ("at 0:30") are a household's words and are never touched.

_PATH = (r"(?<![\w/.])/(?:config|data|opt|usr|etc|var|share|ssl|addons?|"
         r"media|tmp|homeassistant)(?:/[\w.\-]+)+/?")
_FILE = (r"(?<![\w/.])[\w-]+(?:\.[\w-]+)*\.(?:md|json|ya?ml|py|sh|txt|log|"
         r"toml|db|conf|jsonl)\b")
_LINE = r"(?:\s+(?:at\s+|on\s+)?line\s+\d+|:\d+\b)?"
_FILE_RE = re.compile(
    r"(?:\b(?:at\s+|on\s+)?line\s+\d+\s+(?:of|in)\s+)?(?:" + _PATH + "|" + _FILE
    + r")" + _LINE, re.I)
_HEX_RE = re.compile(
    r"\s*\(\s*0x[0-9a-f]{1,16}\s*\)"
    r"|\b(?:(?:an?\s+)?(?:error|fault|status|result)\s+)?(?:code\s+)?"
    r"0x[0-9a-f]{1,16}\b", re.I)
# A pre-release marker ("-rc3") is kept as words: "2.4.1-rc3_build77" is a
# test build OF 2.4.1, and saying "2.4.1" would name a release the device
# is not on.
_BUILD_RE = re.compile(
    r"\b(v?\d+(?:\.\d+){1,3})(?P<pre>-?(?:rc|beta|alpha)\d*)?[-+_]"
    r"(?:build[.\-]?\d+[\w.]*|g?[0-9a-f]{7,}|"
    r"\d{6,}|[a-z]+\d*\.[0-9a-f]{6,})\b", re.I)
# A build string with no version in front of it ("build 24C101", #774): the
# word, then a token of four or more that holds a digit. "build 3 shelves"
# is a sentence, not a build.
_BARE_BUILD_RE = re.compile(
    r"\s*\(\s*(?:firmware\s+)?build\s+(?=[\w.\-]*\d)[A-Za-z0-9][\w.\-]{3,}\s*\)"
    r"|\b(firmware\s+)?build\s+(?=[\w.\-]*\d)[A-Za-z0-9][\w.\-]{2,}[A-Za-z0-9]",
    re.I)
# A signal strength in dBm ("-84 dBm"): a number a radio engineer reads and
# a household cannot weigh (#855). `dbm_words` says it in words IN PLACE;
# a sentence is never dropped for holding one.
_DBM_NUM = r"(?P<n>[-\u2212\u2013]?\d+(?:\.\d+)?)\s*dBm\b"
_DBM_RE = re.compile(r"[-\u2212\u2013]?\d+(?:\.\d+)?\s*dBm\b", re.I)
_MCP_RE = re.compile(r"`?\bmcp__\w+`?")
# A snake_case word with no dot: an event, a service call or a setting's key
# (`bruh_minecraft_moment`), which is what the code calls a thing and never
# what the house does (#618). It is said by the house's name for it when an
# entity's object id is that word, and otherwise as its own words ("bruh
# minecraft moment") — never as "an internal name", which broke the
# sentence and left nobody able to tell which thing was meant (#791). In
# brackets it is an aside, and goes. A dotted id (`sensor.hall_motion`) is
# an entity and is `ids`' to name.
_SNAKE_RE = re.compile(r"`?(?<![\w.])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w]|\.\w)`?")
_SNAKE_ASIDE_RE = re.compile(
    r"\s*\(\s*`?([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`?\s*\)")
_TOOL_NAMES: frozenset | None = None
_TOOL_FILES = ("/opt/ha-mcp-server/ha_mcp_server.py",)


def tool_names() -> frozenset:
    """The MCP server's tool names, read once off its own source (the image
    ships it at /opt/ha-mcp-server, a checkout beside this panel): one list,
    never a copy that drifts from the server's. Only snake_case names: a
    one-word tool ("recall", "habits") is also an everyday word."""
    global _TOOL_NAMES
    if _TOOL_NAMES is None:
        here = __import__("pathlib").Path(__file__).resolve().parent
        names: set[str] = set()
        for path in (*_TOOL_FILES,
                     str(here.parent / "ha-mcp-server" / "ha_mcp_server.py")):
            try:
                with open(path, encoding="utf-8") as fh:
                    source = fh.read()
            except OSError:
                continue
            names |= set(re.findall(r'^\s+"name":\s*"([a-z][a-z0-9]*(?:_[a-z0-9]+)+)"',
                                    source, re.M))
            if names:
                break
        _TOOL_NAMES = frozenset(names)
    return _TOOL_NAMES


def _tool_re():
    names = tool_names()
    if not names:
        return None
    return re.compile(r"`?(?<![\w.])(?:" + "|".join(
        sorted(map(re.escape, names), key=len, reverse=True))
        + r")(?!\w|\.\w)`?")


_LINE_NO_RE = re.compile(r"\bline\s+\d+\b", re.I)


def developer_sentence(sentence: str) -> bool:
    """Whether a sentence holds what only a developer acts on: a file path
    or name, a line number, one of brAIn's tool names."""
    text = str(sentence or "")
    if not text:
        return False
    if _FILE_RE.search(text) or _LINE_NO_RE.search(text) \
            or _MCP_RE.search(text):
        return True
    tools = _tool_re()
    return bool(tools is not None and tools.search(text))


def household_step(text: str, *, own_checks: bool = True) -> str:
    """``text`` as a step the household carries out (#736): less every
    sentence holding a path, a line number or a tool name (brAIn's own
    upkeep is brAIn's), every "nothing is needed" (a result, not a step),
    and — with ``own_checks`` — every sentence asking somebody to check
    what brAIn reads itself. "" when nothing of it is left."""
    if not isinstance(text, str) or not text.strip():
        return ""
    import triage  # noqa: PLC0415 — the one NOTHING_RE, read lazily
    kept = []
    for sentence in _LOG_SENTENCES.split(text.strip()):
        if not sentence.strip():
            continue
        if developer_sentence(sentence) or triage.NOTHING_RE.search(sentence):
            continue
        if own_checks and _SELF_CHECK.search(sentence):
            continue
        kept.append(sentence.strip())
    return " ".join(kept).strip()


def without_files(text: str) -> str:
    """``text`` with every file path, file name and line number in it said
    as "a configuration file" — and nothing else of `technical`'s touched,
    for a sentence whose other words are a person's to read."""
    if not isinstance(text, str) or not text:
        return text
    out = _FILE_RE.sub("a configuration file", text)
    out = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", out))
    return out.strip()


def _object_ids(names: Mapping | None) -> dict[str, str]:
    """``{object id: name}`` for every object id one entity alone has."""
    out: dict[str, str] = {}
    twice: set[str] = set()
    for eid, name in _names_for(names).items():
        obj = eid.split(".", 1)[-1]
        if obj in out:
            twice.add(obj)
        out[obj] = name
    return {k: v for k, v in out.items() if k not in twice}


def code_words(token: str, names: Mapping | None = None) -> str:
    """A snake_case code name as a person reads it: the house's name for
    the entity whose object id it is, or its own words."""
    token = str(token or "").strip().strip("`").strip()
    return _object_ids(names).get(token) or token.replace("_", " ")


def technical(text: str, files: bool = True,
              names: Mapping | None = None) -> tuple[str, list[str]]:
    """``(text, found)``: ``text`` with the strings only a developer reads
    taken out of the sentence, and those strings. Text with none comes back
    exactly as it was, with an empty list. ``files=False`` leaves a file's
    NAME (a look's conclusion, whose file names are held on screen by
    `tests/test_open_row_look_reason.py`) and still takes out a path and a
    line number (#774). A code name is said in words (`code_words`)."""
    if not isinstance(text, str) or not text:
        return text, []
    found: list[str] = []

    def keep(token: str) -> None:
        token = token.strip().strip("`").strip()
        if token and token not in found:
            found.append(token)

    def swap(words: str):
        def sub(m: re.Match) -> str:
            keep(m.group(0))
            lead = m.group(0)[:len(m.group(0)) - len(m.group(0).lstrip())]
            return lead + words if words else ""
        return sub

    def build(m: re.Match) -> str:
        keep(m.group(0))
        if m.group("pre"):
            return f"{m.group(1)} (a test build)"
        return m.group(1)

    def bare_build(m: re.Match) -> str:
        keep(m.group(0).strip(" ()"))
        whole = m.group(0)
        if whole.strip().startswith("("):
            return ""
        lead = whole[:len(whole) - len(whole.lstrip())]
        return lead + ("its current firmware" if m.group(1) else
                       "its current build")

    def hexcode(m: re.Match) -> str:
        whole = m.group(0)
        keep(re.search(r"0x[0-9a-f]+", whole, re.I).group(0))
        if whole.strip().startswith("("):
            return ""
        lead = whole[:len(whole) - len(whole.lstrip())]
        return lead + "an error code"

    def aside(m: re.Match) -> str:
        keep(m.group(1))
        return ""

    def code(m: re.Match) -> str:
        keep(m.group(0))
        return code_words(m.group(0), names)

    try:
        out = _BUILD_RE.sub(build, text)
        out = _BARE_BUILD_RE.sub(bare_build, out)
        out = dbm_words(out, keep)
        out = _HEX_RE.sub(hexcode, out)
        out = _MCP_RE.sub(swap("one of brAIn's tools"), out)
        tools = _tool_re()
        if tools is not None:
            out = tools.sub(swap("one of brAIn's tools"), out)
        if files:
            out = _FILE_RE.sub(swap("a configuration file"), out)
        else:
            out = _PATH_RE.sub(swap("a configuration file"), out)
            out = _LINE_AT_RE.sub(swap(""), out)
        out = _SNAKE_ASIDE_RE.sub(aside, out)
        out = _SNAKE_RE.sub(code, out)
    except Exception:  # noqa: BLE001 — a cleanup must never cost the row
        return text, []
    if not found:
        return text, []
    out = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", out))
    out = re.sub(r"\(\s*\)", "", out).strip()
    # "Code 0xFF failed" became "an error code failed": a sentence that
    # began with a capital still does.
    if text[:1].isupper() and out[:1].islower():
        out = out[0].upper() + out[1:]
    return out, found


# A path (never a bare file name) and a line number on their own, for the
# look's conclusion, which keeps file names.
_PATH_RE = re.compile(
    r"(?:\b(?:at\s+|on\s+)?line\s+\d+\s+(?:of|in)\s+)?" + _PATH + _LINE, re.I)
_LINE_AT_RE = re.compile(r"\s*,?\s*\b(?:at\s+|on\s+)?line\s+\d+\b", re.I)


# ---------------------------------------------------------------------------
# Ids in words, the lint, and the display pass (#774, #791)
# ---------------------------------------------------------------------------
#
# A house's findings quoted `tts.google_en_com` and `sensor.…` ids the names
# map had no name for — `entities` leaves those on purpose, because a
# made-up name is worse than the id — and a service id (`tts.speak`) is in
# no names map at all. What the household can read is what the thing IS:
# "the voice service", "the sensor". So `ids` says a known id by its name
# and any other by its kind, in the sentence's grammar ("The sensor.x
# sensor" is "The sensor"; an id in brackets is an aside and goes).
# `lint` names every fragment a household should not meet, and
# `said_plainly` is the display pass: the rewrites, then any sentence the
# lint still flags is dropped.

_ID_NOUNS = {
    "air_quality": "air quality sensor", "alarm_control_panel": "alarm panel",
    "assist_satellite": "voice satellite", "automation": "automation",
    "binary_sensor": "sensor", "button": "button", "calendar": "calendar",
    "camera": "camera", "climate": "thermostat", "conversation": "assistant",
    "counter": "counter", "cover": "cover", "date": "date setting",
    "datetime": "date setting", "device_tracker": "tracker", "event": "event",
    "fan": "fan", "geo_location": "location", "group": "group",
    "humidifier": "humidifier", "image": "image", "input_boolean": "helper",
    "input_button": "helper", "input_datetime": "helper",
    "input_number": "helper", "input_select": "helper", "input_text": "helper",
    "lawn_mower": "lawn mower", "light": "light", "lock": "lock",
    "media_player": "speaker", "number": "setting", "person": "person",
    "plant": "plant", "remote": "remote", "scene": "scene",
    "schedule": "schedule", "script": "script", "select": "setting",
    "sensor": "sensor", "siren": "siren", "stt": "speech service",
    "sun": "sun", "switch": "switch", "tag": "tag", "text": "text setting",
    "time": "time setting", "timer": "timer", "todo": "list",
    "tts": "voice service", "update": "update", "vacuum": "vacuum",
    "valve": "valve", "wake_word": "wake word service",
    "water_heater": "water heater", "weather": "weather service",
    "zone": "zone", "notify": "notification service",
    "persistent_notification": "notification",
    "homeassistant": "Home Assistant action",
}
_ID_RE = re.compile(
    r"`?(?<![\w./])([a-z][a-z_]*)\.([a-z0-9][a-z0-9_]*)(?![\w]|\.\w)`?")
_NOT_AN_ID = frozenset({"md", "json", "yaml", "yml", "py", "sh", "txt", "log",
                        "toml", "db", "conf", "jsonl", "js", "css", "html"})
_DETERMINER_RE = re.compile(
    r"\b(?:the|a|an|this|that|its|your|their|our|his|her)\s+$", re.I)
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?]\s+)\s*$")


def _an_id(m: re.Match) -> bool:
    return m.group(1) in _ID_NOUNS and m.group(2) not in _NOT_AN_ID


def ids(text: str, names: Mapping | None = None) -> tuple[str, list[str]]:
    """``(text, found)``: every entity or service id in ``text`` said by the
    house's name for it, or as the kind of thing it is, and the ids. Text
    with none comes back exactly as it was."""
    if not isinstance(text, str) or not text:
        return text, []
    known = _names_for(names)
    found: list[str] = []
    out = ""
    pos = 0
    try:
        for m in _ID_RE.finditer(text):
            if m.start() < pos or not _an_id(m):
                continue
            eid = f"{m.group(1)}.{m.group(2)}"
            if eid not in found:
                found.append(eid)
            before = out + text[pos:m.start()]
            after_at = m.end()
            if eid in known:
                said = known[eid]
            elif re.search(r"\(\s*$", before) and re.match(r"\s*\)",
                                                          text[after_at:]):
                # An aside: "The hall speaker (media_player.den_echo)".
                before = re.sub(r"\s*\(\s*$", "", before)
                after_at += re.match(r"\s*\)", text[after_at:]).end()
                said = ""
            else:
                noun = _ID_NOUNS[m.group(1)]
                tail = noun.split()[-1]
                again = re.match(r"\s+" + re.escape(tail) + r"\b",
                                 text[after_at:], re.I)
                if again:
                    after_at += again.end()
                if re.search(r"\b" + re.escape(tail) + r"\s+$", before, re.I):
                    # "Leak sensor sensor.kitchen_leak shows wet": the
                    # sentence already said what it is.
                    said = ""
                elif _DETERMINER_RE.search(before):
                    said = noun
                else:
                    said = "the " + noun
                    if _SENTENCE_START_RE.search(before):
                        said = said[0].upper() + said[1:]
            out = before + said
            pos = after_at
        if not found:
            return text, []
        out += text[pos:]
        for name in set(known.values()):
            out = re.sub(re.escape(name) + r"\s*\(\s*" + re.escape(name)
                         + r"\s*\)", name, out)
        out = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", out))
    except Exception:  # noqa: BLE001 — a cleanup must never cost the row
        return text, []
    return out.strip(), found


# What the step above wrote until #791, and real stores still hold.
_LEGACY_CODE_NAME = "an internal name"
_LEGACY_RE = re.compile(r"\ban internal name\b", re.I)
_LEGACY_AFTER_ARTICLE_RE = re.compile(
    r"\b((?:the|a|an|this|that|its|your)\s+)an internal name\s+(?=[a-z])",
    re.I)


def lint(text: str, files: bool = True, figures: bool = True) -> list[str]:
    """Every fragment of ``text`` a household should not meet in a
    finding: a path (and with ``files`` a file name), a line number, an
    entity or service id, a hex code, a build string, one of brAIn's tool
    names, a code name, and the old "an internal name"."""
    text = str(text or "")
    if not text:
        return []
    out: list[str] = []
    for pattern in ((_FILE_RE if files else _PATH_RE), _LINE_NO_RE, _HEX_RE,
                    _BUILD_RE, _BARE_BUILD_RE,
                    *((_DBM_RE,) if figures else ()),
                    _MCP_RE, _SNAKE_RE, _LEGACY_RE):
        out += [m.group(0).strip() for m in pattern.finditer(text)]
    out += [m.group(0).strip("`") for m in _ID_RE.finditer(text) if _an_id(m)]
    tools = _tool_re()
    if tools is not None:
        out += [m.group(0) for m in tools.finditer(text)]
    seen: list[str] = []
    for frag in out:
        if frag and frag not in seen:
            seen.append(frag)
    return seen


# Signal diagnostics ("the Wi-Fi signal is weak", "link quality 40") in a
# finding whose headline is about something else answer a question nobody
# asked and bury the one that was (#829).
_SIGNAL_SENTENCE_RE = re.compile(
    r"\b(?:signal[\s-]+(?:strength|quality|is|was|dropped|fell|has|had)"
    r"|(?:wi-?fi|radio|weak|poor|fair|good|strong)\s+signal|rssi|lqi"
    r"|link[\s-]+quality)\b|\d\s*dBm\b",
    re.I)
# A headline about the connection names it with a noun ("weak" alone is
# the battery's as often as the signal's).
_SIGNAL_HEADLINE_RE = re.compile(
    r"\b(?:signal|wi-?fi|rssi|lqi|dBm|link[\s-]+quality|zigbee|z-?wave|"
    r"connection|connect(?:s|ed|ing|ivity)?|disconnect\w*|mesh|reception|"
    r"offline|unreachable|unavailable|dropouts?)\b", re.I)


_ACTION_RE = re.compile(
    r"\b(?:replace|change|swap|charge|unlock|lock|shut|turn|switch|close|"
    r"open|call|restart|reboot|move|unplug|plug|press|hold|remove|insert|"
    r"reset|pair|re-?pair|fix|stop|start|check|ask|tell|contact|wake)\b|,\s*so\b",
    re.I)


def on_topic(text: str, headline: str) -> str:
    """A DETAIL less every signal-diagnostic sentence that holds no step,
    when ``headline`` is not about connectivity — never all of it, and
    never a sentence with an action in it ("signal is weak, so unlock the
    door by hand")."""
    if (not isinstance(text, str) or not text
            or _SIGNAL_HEADLINE_RE.search(str(headline or ""))
            or not _SIGNAL_SENTENCE_RE.search(text)):
        return text
    kept = [s for s in _LOG_SENTENCES.split(text)
            if s.strip() and (not _SIGNAL_SENTENCE_RE.search(s)
                              or _ACTION_RE.search(s))]
    return " ".join(kept).strip() or text


def _signal_word(value: float) -> str:
    """-75 dBm or lower is weak, to -67 fair, above that good."""
    return "weak" if value <= -75 else "fair" if value <= -67 else "good"


def _dbm_value(m: re.Match) -> float:
    return float(m.group("n").replace("\u2212", "-").replace("\u2013", "-"))


def _cap_at_start(text: str, at: int, words: str) -> str:
    """``words`` capitalised when they begin a sentence of ``text``."""
    before = text[:at].rstrip()
    return (words[:1].upper() + words[1:]
            if not before or before[-1] in ".!?" else words)


# The shapes a figure is said in, each replaced where it stands.
_DBM_ASIDE_RE = re.compile(r"\s*\([^()]*?" + _DBM_NUM + r"[^()]*\)", re.I)
_DBM_SIGNAL_OF_RE = re.compile(
    r"\b(?P<art>an?|the|its|their)\s+(?:signal|RSSI)(?:\s+strength)?\s+"
    r"(?:of|at)\s+(?:about\s+|around\s+)?" + _DBM_NUM, re.I)
_DBM_READS_RE = re.compile(
    r"(?P<subj>\b[\w'\u2019-]+)\s+(?P<verb>reads?|is|was|shows?|showed|"
    r"measured|measures|averages?|averaged|sits\s+at|sat\s+at)\s+"
    r"(?:at\s+|about\s+|around\s+)?" + _DBM_NUM, re.I)
_DBM_FELL_RE = re.compile(
    r"\b(?P<verb>dropped|drops|fell|falls|went|goes|is\s+down|was\s+down)"
    r"\s+(?:below|under|to|down\s+to)\s+" + _DBM_NUM, re.I)
_DBM_PREP_RE = re.compile(
    r"(?P<prep>\b(?:at|with|around|about|near|below|under|on)\s+)"
    r"(?:(?:about|around|roughly)\s+)?" + _DBM_NUM, re.I)
_DBM_SUBJECT_RE = re.compile(
    r"(?:^|(?<=[;:,.!?]))\s*" + _DBM_NUM
    + r"\s+(?P<verb>is|was)\b", re.I)
_DBM_LABEL_RE = re.compile(
    r"\b(?:RSSI|signal(?:\s+strength)?|reception)\s*[:=]?\s*" + _DBM_NUM,
    re.I)
_SIGNAL_SAID_RE = re.compile(
    r"\b(?:weak|poor|low|fair|good|strong|signal|reception)\b", re.I)


def dbm_words(text: str, found=None) -> str:
    """``text`` with each signal figure said in words where it stands
    (#855): "The plug reads -84 dBm" is "The plug has a weak signal", "At
    -84 dBm the lock cannot be reached" is "With a weak signal the lock
    cannot be reached", "signal dropped below -80 dBm" is "signal dropped
    to a weak level", "Signal is weak at -84 dBm" loses the figure, and an
    aside "(-84 dBm)" goes. Nothing else in the sentence changes, no
    sentence is dropped, and a figure in a shape not listed stays as it
    was: a step is never cut to say it plainly. ``found`` (a callable)
    is handed each figure taken out."""
    if not isinstance(text, str) or not _DBM_RE.search(text):
        return text

    def took(m: re.Match) -> float:
        if found is not None:
            found(m.group(0).strip(" ()"))
        return _dbm_value(m)

    def aside(m):
        took(m)
        return ""

    def signal_of(m):
        word = _signal_word(took(m))
        return f"{m.group('art')} {word} signal"

    def reads(m):
        word = _signal_word(took(m))
        subj, verb = m.group("subj"), m.group("verb").lower()
        past = verb.startswith(("was", "showed", "measured", "averaged",
                                "sat"))
        if subj.lower() in ("signal", "rssi", "strength", "reception"):
            subj = "signal" if subj.lower() == "rssi" else subj
            return f"{subj} {'was' if past else 'is'} {word}"
        return f"{subj} {'had' if past else 'has'} a {word} signal"

    def fell(m):
        word = _signal_word(took(m) - 1)
        said = m.string[max(0, m.start() - 40):m.start()]
        what = "level" if re.search(r"\bsignal\b", said, re.I) else "signal"
        verb = re.sub(r"\s+down$", " down", m.group("verb"))
        return f"{verb} to a {word} {what}"

    def prep(m):
        word = _signal_word(took(m))
        if m.string[:m.start()].strip():
            # Mid-sentence the figure is an aside, and goes: "weak at -84
            # dBm" already says it, and "replace the battery with a weak
            # signal" would say something else.
            return ""
        # Leading the sentence it is the condition: "At -84 dBm the lock
        # cannot be reached" is "With a weak signal the lock…".
        return _cap_at_start(m.string, m.start(), f"with a {word} signal")

    def subject(m):
        took(m)
        lead = m.group(0)[:len(m.group(0)) - len(m.group(0).lstrip())]
        return lead + _cap_at_start(m.string, m.start() + len(lead),
                                    f"the signal {m.group('verb')}")

    def label(m):
        word = _signal_word(took(m))
        if re.match(r"\s*(?:[.!?]|$)", m.string[m.end():]):
            # "RSSI -84 dBm." is a whole sentence, and says one.
            return _cap_at_start(m.string, m.start(),
                                 f"the signal is {word}")
        return _cap_at_start(m.string, m.start(), f"a {word} signal")

    def one(sentence: str) -> str:
        if not _DBM_RE.search(sentence):
            return sentence
        out = _DBM_ASIDE_RE.sub(aside, sentence)
        out = _DBM_SIGNAL_OF_RE.sub(signal_of, out)
        out = _DBM_READS_RE.sub(reads, out)
        out = _DBM_FELL_RE.sub(fell, out)
        out = _DBM_SUBJECT_RE.sub(subject, out)
        out = _DBM_PREP_RE.sub(prep, out)
        out = _DBM_LABEL_RE.sub(label, out)
        # All of a sentence's figures in words, or none of them: "fair and
        # -85 dBm" is neither.
        return sentence if _DBM_RE.search(out) else out

    try:
        # Split keeping each gap as it was (a newline stays one).
        parts = re.split(r"((?<=[.!?])\s+)", text)
        out = "".join(p if i % 2 else one(p) for i, p in enumerate(parts))
    except (ValueError, re.error):
        return text
    if out == text:
        return text
    return re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", out))


def said_plainly(text: str, names: Mapping | None = None, files: bool = True,
                 known: list | tuple = ()) -> str:
    """``text`` as a surface shows it (#774, #791): developer strings out
    (`technical`), ids by name or kind (`ids`), the old "an internal name"
    repaired — after an article it simply goes ("the event"), and elsewhere
    it is the one code name the row kept in ``known`` (its Technical
    line), said in words — and then any sentence `lint` still flags is
    dropped. Text the lint finds nothing in comes back as it was."""
    if not isinstance(text, str) or not text or not lint(text, files):
        return text
    out = technical(text, files, names)[0]
    out = ids(out, names)[0]
    if _LEGACY_RE.search(out):
        out = _LEGACY_AFTER_ARTICLE_RE.sub(r"\1", out)
        codes = [t for t in known or () if isinstance(t, str)
                 and _SNAKE_RE.fullmatch(t.strip())]
        if len(codes) == 1:
            out = _LEGACY_RE.sub(code_words(codes[0], names), out)
    # A signal figure `dbm_words` could not say in words stays: a sentence
    # is never dropped for one (it may hold the step).
    if not lint(out, files, figures=False):
        return out
    kept = [s for s in _LOG_SENTENCES.split(out)
            if s.strip() and not lint(s, files, figures=False)]
    return " ".join(kept).strip()


# brAIn's own setup — its instructions, personality, identity, voice — as
# the SUBJECT of a row, narrower than `about_self`: "the voice satellite in
# the den" is the house's, "brAIn's spoken voice" and "its instructions
# file" are brAIn's. A row about it beside an open question about it asks
# the household the same thing twice (`findings_store.add_many`).
_OWN_SETUP_RE = re.compile(
    r"\b(?:brAIn['’]s|[Mm]y|its own)\s+(?:own\s+)?(?:\w+\s+)?(?:instructions?|"
    r"personality|identity|wake word|spoken voice|voice)\b"
    r"|\b(?:brAIn|the assistant)\s+(?:is\s+)?(?:called|named)\b"
    r"|\binstructions?\s+(?:file|override)s?\b"
    r"|\bpersonality\b|\bchat_identity\b|\bnote_personality_change\b")


def about_own_setup(*texts) -> bool:
    """Whether a row's words are about brAIn's own setup."""
    return any(_OWN_SETUP_RE.search(str(t or "")) for t in texts)
