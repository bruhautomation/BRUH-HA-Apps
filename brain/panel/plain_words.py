"""What brAIn's own parts are called, in words the owner reads.

brAIn's machinery is named for whoever writes it — `check:dev.frozen`,
`resident`, `mute_offer`, `user-1789499215`, a run "ended crash" — and every
screen that reads its own diagnostics used to print those names straight
through. ⚙ › Diagnostics said "Producer Sensors frozen on one value
(check:dev.frozen): ignored 3 of 4 times" and "Run (memory): ended crash",
and the queue's mute suggestion said the same rule was "marked wrong 4 of
4": two wordings of one count, neither naming what it counted.

So every name and every count a person reads about brAIn itself is worded
HERE, once, and the ids ride underneath for whoever is debugging. Three
rules.

**A leaf.** Nothing of the panel is imported, because `reports` (which
must run with the panel down), `mute_offer` and `server` all read it.

**A name nobody gave is not invented.** A title a caller has is used as
it is; the tables only answer for brAIn's own producers and jobs, and an
id nothing knows is turned into words rather than shown as an id.

**One count, one sentence.** `record_words` is the only place a record of
answers becomes words, so the Health list, the scorecard and the queue's
question cannot word the same numbers two ways.
"""
from __future__ import annotations

import re

# brAIn's own producers: what files a finding or a question when no card
# or check does. A producer not here is named by its title, else its id
# put into words.
PRODUCER_NAMES = {
    "mute_offer": "Rule suggestions",
    "notify_policy": "Notification suggestions",
    "sre": "Overnight health check",
    "resident": "brAIn's own investigations",
    "safety": "Safety detectors",
    "correction": "Your corrections",
    "house_book": "House book questions",
    "healing": "Overnight repair",
    "condition": "Automation condition suggestions",
    "scene": "Scene suggestions",
    "security": "Tripwire",
    "doctor": "The full self-test",
    "chat": "Conversations in Ask",
    "study": "Study sessions",
}

# The jobs a run in the journal was doing, by its `source`.
JOB_NAMES = {
    "memory": "Filing facts into memory",
    "study": "Studying the house",
    "voice": "Voice answers",
    "automation": "Tasks from automations",
    "card": "Insight cards",
    "insight": "Insight cards",
    "fix": "Fixes",
    "doctor": "The full self-test",
    "curiosity": "Working out why something was done by hand",
    "triage": "Checking new findings",
    "resident": "Checking new findings",
    "gate": "Checking actions before they run",
    "followup": "Checking fixes still hold",
    "replay": "Scoring prompts",
    "maintenance": "Upkeep jobs",
    "chat": "Conversations in Ask",
    "reply": "Replies from your phone",
    "healing": "Overnight repair",
    "sre": "Overnight health check",
    "baselines": "Measuring what is normal",
    "checks": "House checks",
    "intent": "Rules asked for in a sentence",
    "proposal": "Suggestions",
    "brief": "Morning brief",
    "weekly": "Weekly report",
    "weekly_pick": "Weekly report",
    "extract": "Learning from conversations",
}

# The background processes the roll-call names.
DAEMON_NAMES = {
    "assist_listener": "Voice answers",
    "assist_pool": "Voice answers",
    "automation_listener": "Tasks from automations",
    "consolidator": "Filing facts into memory",
    "memory_consolidator": "Filing facts into memory",
    "study_watcher": "Study sessions",
    "usage_tracker": "Usage figures",
    "usage_limits_tracker": "Usage figures",
    "ttyd": "The terminal",
    "terminal": "The terminal",
}

_NO_TITLE = ("", "custom", "?")


def words_of(ident: str) -> str:
    """An id nobody named, put into words: "forecast.decline" → "Forecast
    decline", "assist_listener" → "Assist listener"."""
    text = re.sub(r"[._:-]+", " ", str(ident or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:1].upper() + text[1:] if text else ""


def producer_name(source: str, title: str = "") -> str:
    """What a producer is called on any screen a person reads."""
    source = str(source or "")
    title = str(title or "").strip()
    if title and title.lower() not in _NO_TITLE and title != source:
        return title[:120]
    if source in PRODUCER_NAMES:
        return PRODUCER_NAMES[source]
    if source.startswith("user-"):
        return "A card you made"
    if source.startswith("custom-"):
        return "A question you asked"
    if source.startswith("check:"):
        return f"House check: {words_of(source[6:]).lower()}"
    return words_of(source) or "An unnamed rule"


def job_name(source: str) -> str:
    source = str(source or "")
    return JOB_NAMES.get(source) or words_of(source) or "A background job"


def daemon_name(name: str) -> str:
    return DAEMON_NAMES.get(str(name or "")) or words_of(name)


def plural(n: int, one: str, many: str = "") -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def record_words(wrong: int, total: int) -> str:
    """The one sentence for how often a rule's reports were answered wrong.

    "4 marked wrong of 6 answers": it says what is counted (answers you
    gave, and how many of them said the report was wrong), where the
    Health list said "ignored 4 of 6 times" and the queue said "4 of 6
    reports were marked wrong" about the same two numbers."""
    wrong, total = int(wrong or 0), int(total or 0)
    return f"{wrong} marked wrong of {plural(total, 'answer')}"


def score_words(confirmed: int, wrong: int) -> str:
    """The scorecard's count: "right 1 of 4, wrong 3"."""
    confirmed, wrong = int(confirmed or 0), int(wrong or 0)
    return f"right {confirmed} of {confirmed + wrong}, wrong {wrong}"


# How many answers before a verdict word means anything, and the share of
# wrong ones past which a rule is doubtful. `findings_store`'s floor.
VERDICT_MIN = 3


def verdict(confirmed: int, wrong: int, muted: bool = False) -> str:
    """One word for how far a rule can be trusted on this house:
    `muted`, `doubtful`, `trusted`, or `too few answers`."""
    if muted:
        return "muted"
    confirmed, wrong = int(confirmed or 0), int(wrong or 0)
    if confirmed + wrong < VERDICT_MIN:
        return "too few answers"
    return "doubtful" if wrong > confirmed else "trusted"
