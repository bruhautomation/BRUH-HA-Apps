# Design notes

Self-contained HTML pages (open them in a browser; nothing to build). They
are the roadmap the code is built against, written before the code, and
kept here so a future change can be checked against the reasoning rather
than reconstructed from it.

| Page | What it covers | Status |
| --- | --- | --- |
| [brain-checks-and-self-tests.html](brain-checks-and-self-tests.html) | Deterministic house checks (findings that cost nothing), the in-situ self-test, and the feedback loop: run journal, diagnostics bundle, producer scorecard, corpus and replay. | Tiers 1–2 and part of 3 shipped in brAIn 1.29.0: `panel/checks/`, `panel/journal.py`, `/api/diagnostics` + the integration's diagnostics platform, the scorecard, `brain check`, `brain doctor --json`, `brain report`, `protected_entities`. Deep doctor, rehearsal, corpus and replay are not built yet. |
| [brain-capability-map.html](brain-capability-map.html) | About a hundred capabilities in sixteen themes that would make brAIn proactive rather than a reporter, with the platform enablers most of them stand on and a ranked top twelve. | Roadmap. The first forecast (`forecast.battery`) and the protected-entity policy shipped in 1.29.0; everything else is proposed. |

Check ids, thresholds and tier contents in the pages are proposals to be
edited; where the code disagrees with a page, the code is what shipped and
the page is what was intended.
