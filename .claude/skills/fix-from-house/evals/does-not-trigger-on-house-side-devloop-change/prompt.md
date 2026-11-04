---
tags: [fix-from-house, trigger, should-not]
max_turns: 20
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Bash]
---

Change brain/panel/devloop/upstream.py so a declined report stands down for 90 days instead of forever, with a test.
