"""Which files build a prompt for a house LLM job, and which job each feeds.

One list, read three ways: ``run.py --changed`` narrows a run to the jobs
a change can reach, ``.github/workflows/evals.yml``'s ``paths:`` filter is
held equal to ``workflow_paths()`` by ``test_graders.py``, and
``tests/affected.py`` (or anything else asking "is this a prompt file") can
import ``is_prompt_path``. A prompt builder added somewhere this list does
not name is a prompt nothing re-measures, so a new job's builder goes here
in the same change as its cases.

Import this as ``evals.selection``. It was ``select.py`` and shadowed the
standard library's ``select`` for every script run from this directory.
"""
from __future__ import annotations

from fnmatch import fnmatch

# path glob -> the jobs whose prompt (or whose prompt's inputs) it builds.
# "*" means every job: the harness itself, and shared prompt machinery.
PROMPT_FILES: dict[str, tuple[str, ...]] = {
    "brain/scripts/brain-memory-extract.py": ("extractor",),
    "brain/scripts/brain-memory-consolidate.sh": ("consolidator",),
    "brain/panel/outcomes.py": ("reflect", "first_look"),
    "brain/panel/resident.py": ("first_look",),
    "brain/panel/signals.py": ("first_look", "reflect"),
    "brain/panel/prompt_kit.py": ("reflect", "first_look"),
    "brain/morph/service/learning.py": ("morph_learning",),
    "brain/panel/devloop/streams.py": ("devloop_streams",),
    "tests/corpus/entries/*.json": ("first_look",),
    "tests/evals/cases/extractor/*": ("extractor",),
    "tests/evals/cases/consolidator/*": ("consolidator",),
    "tests/evals/cases/reflect/*": ("reflect",),
    "tests/evals/cases/first_look/*": ("first_look",),
    "tests/evals/cases/morph_learning/*": ("morph_learning",),
    "tests/evals/cases/devloop_streams/*": ("devloop_streams",),
    "tests/evals/*.py": ("*",),
    "tests/evals/graders/*.py": ("*",),
    ".github/workflows/evals.yml": ("*",),
}


def jobs_for(path: str) -> tuple[str, ...]:
    """The jobs one changed path can move; () for a path that builds none."""
    path = str(path).lstrip("./")
    hit: list[str] = []
    for pattern, jobs in PROMPT_FILES.items():
        if fnmatch(path, pattern):
            for job in jobs:
                if job not in hit:
                    hit.append(job)
    return tuple(hit)


def is_prompt_path(path: str) -> bool:
    return bool(jobs_for(path))


def selected_jobs(paths, all_jobs) -> list[str]:
    """The jobs a set of changed paths reaches, in ``all_jobs`` order."""
    wanted: set[str] = set()
    for path in paths or []:
        for job in jobs_for(path):
            if job == "*":
                return list(all_jobs)
            wanted.add(job)
    return [job for job in all_jobs if job in wanted]


def workflow_paths() -> list[str]:
    """The ``on.pull_request.paths`` filter, as GitHub spells globs."""
    out = []
    for pattern in PROMPT_FILES:
        out.append(pattern[:-1] + "**" if pattern.endswith("/*") else pattern)
    return out
