#!/bin/bash
# The $BROWSER for everything on this screen: Claude Code's /login opens its
# sign-in page with xdg-open, which runs this, so the page opens as a tab in
# the Chrome already running (a second `google-chrome` hands its URL to the
# first and exits) rather than in a browser that does not exist.
# --no-sandbox only so this short-lived hand-off can start where the sandbox
# cannot (see the panel's browser.py); it changes nothing in the running one.
exec google-chrome --no-sandbox "$@" >/dev/null 2>&1
