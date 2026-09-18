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
    # Thinks — reasoning with tools where a wrong answer costs a card.
    "card":            ("sonnet", "medium", True,  True),
    "ask":             ("sonnet", "medium", True,  True),
    "milestone":       ("sonnet", "medium", True,  False),
    "brief":           ("sonnet", "medium", True,  False),
    "weekly":          ("sonnet", "medium", True,  True),
    "curiosity":       ("sonnet", "medium", True,  False),
    "onboarding":      ("sonnet", "medium", True,  False),
    "study":           ("sonnet", "medium", True,  True),
    "investigate":     ("sonnet", "high",   False, True),
    "fix_plan":        ("sonnet", "high",   False, True),
    "voice":           ("sonnet", "low",    True,  False),
    "task":            ("sonnet", "medium", False, True),
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


def env_exports(override: str = "", thinking: str = DEFAULT_THINKING) -> dict[str, str]:
    """The tier answers as environment variables for the shell half.

    run.sh writes these into /data/.brain_env; brain-learn.sh,
    brain-memory-consolidate.sh and the listeners read them. One table,
    two readers — a second copy of the tiers in shell is how the
    consolidator ends up on Opus the day somebody edits the wrong file.
    """
    out = {
        "BRAIN_MODEL_HAIKU": resolve("triage", thinking, override)[0],
        "BRAIN_MODEL_SONNET": resolve("card", thinking, override)[0],
        "BRAIN_MODEL_OPUS": resolve("fix_apply", thinking, override)[0],
        "BRAIN_MODEL_STUDY": resolve("study", thinking, override)[0],
        "BRAIN_MODEL_MEMORY": resolve("consolidate", thinking, override)[0],
        "BRAIN_MODEL_VOICE": resolve("voice", thinking, override)[0],
        "BRAIN_MODEL_TASK": resolve("task", thinking, override)[0],
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
           "TIERS", "describe", "env_exports", "resolve"]
