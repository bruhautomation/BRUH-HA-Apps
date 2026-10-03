"""Which model does which job, and how hard it thinks.

Every scheduled and pressed Claude run in the add-on used to call one
global setting, so a two-turn "name four scenes" call and a sixty-turn
run that edits somebody's automations.yaml ran the same model at the same
depth. The rule this module encodes is the one the AI-first design page
states: **Haiku looks, Sonnet thinks, Opus acts, Fable is a press.**
Nothing on a timer may reach the top tier.

Three inputs decide a run's model:

* the JOB — a short name every call site passes (`"triage"`, `"card"`,
  `"fix_apply"`, …), looked up in JOBS for its default tier and effort;
* the `thinking` setting — `light` steps a job's tier down where being
  wrong is cheap, `generous` steps investigations up, `normal` is the
  table as written;
* the global `model` option — when a person has typed one, it OVERRIDES
  every job, which is exactly what it did before this module existed, so
  an install that pinned Sonnet stays pinned to Sonnet.

The table maps a tier to the CLI's own alias (`haiku`, `sonnet`, `opus`,
`fable`) rather than to a dated model id, so the account decides which
release of each tier it gets — the same reason MODEL_CHOICES offers the
aliases first. A job the table does not know runs at the `sonnet` tier:
the middle is the safe unknown, and a test pins that every job the panel
passes is in the table so the fallback is never reached in shipped code.

`effort` is the CLI's `--effort` flag. It is a request, not a promise: a
CLI too old to know the flag has it dropped and the run goes on (see
engine._run_cli), the same way a rejected `--session-id` is retried
without one.

Pure over its arguments and stdlib-only, because the shell half of the
add-on (the consolidator, study sessions, the listeners) cannot import
it and reads the same answers out of `/data/.brain_env` instead — see
`env_exports`, which run.sh writes at boot.
"""
from __future__ import annotations

TIERS = ("haiku", "sonnet", "opus", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
THINKING = ("light", "normal", "generous")
DEFAULT_THINKING = "normal"

# job → (tier, effort, may_step_down, may_step_up)
#
# `may_step_down` is False where a wrong answer costs a house or a
# person's trust rather than a card: `light` must not turn an apply run
# into a Sonnet run. `may_step_up` is True only for the reasoning jobs a
# person would plausibly want a stronger model on; `generous` never
# promotes a naming call to Opus.
JOBS: dict[str, tuple[str, str, bool, bool]] = {
    # Looks — volume work with a closed vocabulary.
    "triage":          ("haiku",  "low",    False, True),
    "first_look":      ("haiku",  "low",    False, True),
    "scene_names":     ("haiku",  "low",    False, False),
    "playbook_text":   ("haiku",  "low",    False, False),
    "episode_summary": ("haiku",  "low",    False, False),
    "consolidate":     ("haiku",  "low",    False, False),
    "reflect":         ("haiku",  "low",    False, False),
    "auth_check":      ("haiku",  "low",    False, False),
    # One sentence over a deterministic digest of who can reach the house.
    "access_review":   ("haiku",  "low",    False, False),
    # Thinks — reasoning with tools where a wrong answer costs a card.
    "card":            ("sonnet", "medium", True,  True),
    "ask":             ("sonnet", "medium", True,  True),
    "milestone":       ("sonnet", "medium", True,  False),
    "brief":           ("sonnet", "medium", True,  False),
    "weekly":          ("sonnet", "medium", True,  True),
    "curiosity":       ("sonnet", "medium", True,  False),
    "onboarding":      ("sonnet", "medium", True,  False),
    # Proposing a card set is the same job onboarding does, at a moment
    # when the house has months of history behind it — so it reasons
    # rather than summarises, and it may not step DOWN: a weak ideas pass
    # proposes the generic cards the whole page exists to avoid, and the
    # page is the only thing that would show it.
    "ideas":           ("sonnet", "high",   False, True),
    "study":           ("sonnet", "medium", True,  True),
    "investigate":     ("sonnet", "high",   False, True),
    "fix_plan":        ("sonnet", "high",   False, True),
    "voice":           ("sonnet", "low",    True,  False),
    "task":            ("sonnet", "medium", False, True),
    # Home Assistant's own maintainer (tidy, the house book, the nightly
    # SRE pass, the upgrade advisor). Naming in a house's own style and a
    # manual are cheap to get slightly wrong — every row is reviewed or
    # cited — so they may step down; an upgrade verdict is the one that
    # decides whether somebody installs tonight, so it may not.
    "tidy":            ("sonnet", "low",    True,  False),
    "house_book":      ("sonnet", "medium", True,  False),
    "sre":             ("sonnet", "medium", True,  True),
    "upgrade_advice":  ("sonnet", "high",   False, True),
    # Acts — changes a house or decides what a person acts on.
    "fix_apply":       ("opus",   "xhigh",  False, False),
    "intent":          ("opus",   "high",   False, False),
    "automation":      ("opus",   "high",   False, False),
    "synthesis":       ("opus",   "high",   False, False),
    # A press, never a timer. Nothing in the scheduler names this job.
    "deep_review":     ("fable",  "high",   False, False),
}

# The one job that may never be reached from a loop. `resolve` refuses it
# unless the caller says a person pressed for it.
PRESS_ONLY = frozenset({"deep_review"})

_DOWN = {"opus": "sonnet", "sonnet": "haiku", "haiku": "haiku", "fable": "opus"}
_UP = {"haiku": "sonnet", "sonnet": "opus", "opus": "opus", "fable": "fable"}


def resolve(job: str, thinking: str = DEFAULT_THINKING, override: str = "",
            *, pressed: bool = False) -> tuple[str, str]:
    """`(model, effort)` for a job.

    `override` is the global `model` option; non-empty means every job
    runs it, which is the pre-2.0 behaviour kept on purpose for anybody
    who typed one. `pressed` is required for a PRESS_ONLY job, and a
    refusal is a ValueError rather than a silent downgrade, because a
    scheduler reaching for the top tier is a bug somebody should see.
    """
    if job in PRESS_ONLY and not pressed:
        raise ValueError(f"{job} may only be run by a person's press")
    tier, effort, down_ok, up_ok = JOBS.get(job, ("sonnet", "medium", True, True))
    if thinking == "light" and down_ok:
        tier = _DOWN[tier]
        effort = "low" if effort in ("low", "medium") else "medium"
    elif thinking == "generous" and up_ok:
        tier = _UP[tier]
    model = str(override or "").strip() or tier
    return model, effort


def tier_of(model: str) -> str | None:
    """The tier a model id or alias belongs to, or None when it names none.

    Read off the name, because the name is all a typed override carries:
    `opus`, `claude-opus-5-5` and `claude-opus-4-8` are all the Opus tier,
    and a model whose name holds no tier word is unknown rather than
    guessed — the caller then falls back to the job's own tier, which is
    the direction where being wrong costs a budget line rather than a run.
    Highest tier first, so a name that somehow carried two is read as the
    dearer.
    """
    low = str(model or "").strip().lower()
    if not low:
        return None
    for tier in reversed(TIERS):
        if tier in low:
            return tier
    return None


def guard_override(job: str, override: str, thinking: str = DEFAULT_THINKING,
                   *, pressed: bool = False) -> tuple[str, str]:
    """`(override, "")`, or `("", why)` when a timer may not run it.

    A typed `model` overrides every job — the pre-2.0 behaviour, kept on
    purpose — except in the one place the plan exists to forbid: a Fable
    model on a job nobody pressed for. `PRESS_ONLY` refuses the top tier
    by JOB; this refuses it by MODEL, which is the door a typed override
    walked straight through — "fable" in ⚙ put every scheduled card, look
    and consolidation on the press-only tier, billing usage credits with
    nobody asked. The refusal falls back to the job's own planned tier and
    says so, `PRESS_ONLY`'s shape with the exception swapped for a
    sentence, because a scheduler that cannot run is worse than one that
    runs a tier lower than somebody typed.

    A typed Opus is honoured. What bounds it on a timer is the Resident's
    ledger, which charges a run to the tier it actually ran on.
    """
    override = str(override or "").strip()
    if not override or pressed or job in PRESS_ONLY:
        return override, ""
    if tier_of(override) == "fable":
        return "", (f"the {override} model is only ever run by a person's "
                    "press, so this unattended run used its planned tier")
    return override, ""


def run_tier(job: str, thinking: str = DEFAULT_THINKING, override: str = "",
             *, pressed: bool = False) -> str:
    """The tier this job will actually be CHARGED to on this install.

    The table's tier is what the job is planned at; the dial and a typed
    override move it, and a budget keyed on the table's answer was a
    budget a `generous` dial or an Opus override walked round — an
    investigation on Opus counted against the Sonnet allowance, a first
    look on Opus against nothing at all. A model whose name holds no tier
    is charged at the job's planned tier.
    """
    allowed, _why = guard_override(job, override, thinking, pressed=pressed)
    model, _effort = resolve(job, thinking, allowed, pressed=True)
    planned, _effort = resolve(job, thinking, "", pressed=True)
    return tier_of(model) or tier_of(planned) or JOBS.get(job, ("sonnet",))[0]


def env_exports(override: str = "", thinking: str = DEFAULT_THINKING) -> dict[str, str]:
    """The tier answers as environment variables for the shell half.

    run.sh writes these into /data/.brain_env; brain-learn.sh,
    brain-memory-consolidate.sh and the listeners read them. One table,
    two readers — a second copy of the tiers in shell is how the
    consolidator ends up on Opus the day somebody edits the wrong file.
    """
    def model(job: str, pressed: bool = False) -> str:
        # The shell half runs the consolidator and study on timers, so a
        # typed Fable meets the same guard the panel's runs do. Voice is
        # somebody speaking and the apply tier is somebody's press.
        allowed, _why = guard_override(job, override, thinking, pressed=pressed)
        return resolve(job, thinking, allowed)[0]

    out = {
        "BRAIN_MODEL_HAIKU": model("triage"),
        "BRAIN_MODEL_SONNET": model("card"),
        "BRAIN_MODEL_OPUS": model("fix_apply", pressed=True),
        "BRAIN_MODEL_STUDY": model("study"),
        "BRAIN_MODEL_MEMORY": model("consolidate"),
        "BRAIN_MODEL_VOICE": model("voice", pressed=True),
        # The voice job's depth beside its model: the pool and the classic
        # listener pass it as `--effort` when an agent is set to Default
        # (and the CLI takes the flag). The one effort the shell half
        # reads, because voice is the one shell job a person waits on.
        "BRAIN_EFFORT_VOICE": resolve("voice", thinking, override)[1],
        "BRAIN_MODEL_TASK": model("task"),
        "BRAIN_THINKING": thinking if thinking in THINKING else DEFAULT_THINKING,
    }
    return out


def describe(job: str, thinking: str = DEFAULT_THINKING, override: str = "") -> dict:
    """What a diagnostics page shows for one job: the tier, the model
    that will actually be sent, and the effort."""
    model, effort = resolve(job, thinking, override, pressed=True)
    tier = JOBS.get(job, ("sonnet",))[0]
    return {"job": job, "tier": tier, "model": model, "effort": effort,
            "press_only": job in PRESS_ONLY}


__all__ = ["DEFAULT_THINKING", "EFFORTS", "JOBS", "PRESS_ONLY", "THINKING",
           "TIERS", "describe", "env_exports", "guard_override", "resolve",
           "run_tier", "tier_of"]


def _settings_thinking() -> str:
    """The dial as saved by the panel, read without importing the panel.

    run.sh runs this at boot as root before the panel is up, and the
    panel's settings module drags in more than a boot script wants; the
    file is one JSON object and the key is one string.
    """
    import json
    import os
    path = os.environ.get("BRAIN_SETTINGS_FILE", "/data/settings.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return DEFAULT_THINKING
    value = data.get("thinking") if isinstance(data, dict) else None
    return value if value in THINKING else DEFAULT_THINKING


def main(argv: list[str]) -> int:
    """Print the tier answers as `export` lines for /data/.brain_env.

    `python3 model_plan.py [override]` — the override is the `model`
    option, and an empty one means the tiers stand. The output is what
    run.sh appends to the env file, so the shell half reads the same
    table the panel does rather than a copy of it.
    """
    override = argv[1] if len(argv) > 1 else ""
    for key, value in env_exports(override, _settings_thinking()).items():
        safe = value.replace("\\", "").replace('"', "").replace("$", "").replace("`", "")
        print(f'export {key}="{safe}"')
    return 0


if __name__ == "__main__":  # pragma: no cover — driven by the tests below
    import sys
    raise SystemExit(main(sys.argv))
