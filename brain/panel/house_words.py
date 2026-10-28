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
the house has no name for stays an id — a made-up name is worse than the
id — and a time it cannot parse keeps its words. It is pure over what it
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
_LOG_MEANING_ELSE = "something it was doing failed"


def log_meaning(message: str) -> str:
    """What a logged error means, in plain words, never quoting it."""
    text = str(message or "")
    for pattern, meaning in _LOG_MEANINGS:
        if pattern.search(text):
            return meaning
    return _LOG_MEANING_ELSE


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


def _third_person(sentence: str) -> str:
    out = sentence
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


_SELF_RE = re.compile(
    r"\bbrAIn\b|\b(?:I|I['’]m|I['’]ve|My|my|me|myself)\b|\bpersonality\b|"
    r"\binstructions?\b|\bwake word\b|\bvoice\b|\bmcp__|\bclaude-", )


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
