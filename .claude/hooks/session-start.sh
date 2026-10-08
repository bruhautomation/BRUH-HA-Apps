#!/bin/bash
# SessionStart hook for Claude Code cloud sessions.
#
# Installs the test suite's Python dependencies so an agent's first
# `python3 -m pytest` collects instead of failing on a missing import.
# Use `python3 -m pytest`, never bare `pytest`: the `pytest` on PATH in a
# cloud session is a uv-isolated tool install that cannot see these
# packages (see CLAUDE.md › Development › Running the tests).
#
# Quiet, idempotent (pip skips what is already satisfied), and it never
# fails the session: an offline box starts exactly as it would have
# without this hook, and the first test run says what is missing.

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

req="${CLAUDE_PROJECT_DIR:-.}/tests/requirements-dev.txt"
[ -f "$req" ] || exit 0

pip_install() {
    python3 -m pip install --quiet --disable-pip-version-check \
        --timeout 15 --retries 1 "$@" -r "$req"
}

# A distro Python marked EXTERNALLY-MANAGED refuses a plain install; the
# session container is disposable, so the override is the right answer there.
pip_install >/dev/null 2>&1 || pip_install --break-system-packages >/dev/null 2>&1 \
    || echo "session-start: could not install tests/requirements-dev.txt (offline?); continuing" >&2

exit 0
