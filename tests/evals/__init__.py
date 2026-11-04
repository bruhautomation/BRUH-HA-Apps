"""Eval suites for the house's LLM jobs (plan item 1.6).

A package so that its modules are imported as ``evals.<name>`` and never by
a bare name: ``select.py`` would otherwise shadow the standard library's
``select`` for anything that put this directory first on ``sys.path``
(``subprocess`` imports it). ``run.py`` takes its own directory off the path
before it imports anything for the same reason.

The rules, the case shape and how a house failure becomes a case are in
``docs/notes/diagnostics.md``.
"""
