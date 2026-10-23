"""Print failure detection: watch a print, look hard at the moments it is
likely to go wrong, warn, and pause one that has failed.

* `vision`  — free, local looks at a camera frame: is the lens covered or
  the chamber dark, did the scene change suddenly, is the plate empty.
* `plan`    — the print's own G-code read once, turned into the layers worth
  a look (the first layer, a sharp narrowing, bridges, a colour change, a
  part getting tall and thin) and a budget of looks per print.
* `judge`   — one look by brAIn: the live frame, the picture of what is being
  printed and an earlier frame, answered as a verdict the code checks.
* `watcher` — the state machine per printer that decides when to look,
  what a verdict means, and keeps the history the panel and Home Assistant
  show.
"""
