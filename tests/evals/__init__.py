"""Eval suites for the house's LLM jobs (plan item 1.6).

A package so that its modules are imported as ``evals.<name>``. No module
here may share a standard library module's name: a script run from this
directory (the consolidator runs ``claude_tee.py`` here) has it first on
``sys.path``, and a ``select.py`` here once shadowed the ``select`` that
``subprocess`` imports. ``run.py`` also takes its own directory off the path
before it imports anything.

The rules, the case shape and how a house failure becomes a case are in
``docs/notes/diagnostics.md``.
"""
