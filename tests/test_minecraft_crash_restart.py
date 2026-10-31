#!/usr/bin/env python3
"""A killed Java process is restarted (#585).

The kernel's out-of-memory killer ends the JVM with SIGKILL: exit 137, no crash
report. run.sh's loop treated that like any other exit only in theory - under
bashio's errexit a non-zero `su-exec` ended run.sh itself, and the add-on sat
in error for 3.5 hours with auto_restart_on_crash on. These tests lift the real
run_server_loop out of run.sh and drive it with a stubbed launcher and clock.
"""
from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUN_SH = BASE_DIR / "bruh-minecraft-server" / "run.sh"


def _function(name: str) -> str:
    source = RUN_SH.read_text()
    start = source.index(f"{name}() {{")
    depth, body = 0, ""
    for i, ch in enumerate(source[start:]):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                body = source[start:start + i + 1]
                break
    return body


def _drive(exit_codes: list[int], auto_restart: str = "true", no_restart: bool = False,
           step_seconds: int = 1) -> tuple[int, list[str], list[int]]:
    """Run the loop; each launch exits with the next code, then the stub ends
    the loop with a clean no_restart stop. Returns (rc, log lines, sleeps)."""
    with tempfile.TemporaryDirectory() as tmp:
        panel = Path(tmp) / "panel"
        panel.mkdir()
        codes = " ".join(str(c) for c in exit_codes)
        script = textwrap.dedent(f"""
            set -e
            export MC_PANEL_STATE={panel}
            AUTO_RESTART_ON_CRASH={auto_restart}
            SCRIPTS_DIR=/stub
            NOW=1000000
            LAUNCHES=0
            CODES=({codes})
            for fn in info warning error fatal notice debug; do
                eval "bashio::log.$fn() {{ printf '[%s] %s\\\\n' $fn \\"\\$*\\"; }}"
            done
            write_state() {{ :; }}
            load_config() {{ :; }}
            ensure_rcon_password() {{ :; }}
            render_server_properties() {{ :; }}
            date() {{ echo "$NOW"; }}
            sleep() {{ echo "SLEEP $1"; NOW=$((NOW + $1)); }}
            su-exec() {{
                LAUNCHES=$((LAUNCHES + 1))
                local idx=$((LAUNCHES - 1))
                if [ "$idx" -ge "${{#CODES[@]}}" ]; then
                    touch "$MC_PANEL_STATE/no_restart"; return 0
                fi
                NOW=$((NOW + {step_seconds}))
                return "${{CODES[$idx]}}"
            }}
            {"touch $MC_PANEL_STATE/no_restart" if no_restart else ""}
            {_function("run_server_loop")}
            run_server_loop
            echo "LOOP-RC $?"
            echo "LAUNCHES $LAUNCHES"
        """)
        proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    out = proc.stdout.splitlines()
    sleeps = [int(x.split()[1]) for x in out if x.startswith("SLEEP ")]
    rc = proc.returncode
    return rc, out, sleeps


class TestRestartOnKill(unittest.TestCase):
    def test_exit_137_is_restarted_and_the_loop_survives_errexit(self):
        rc, out, sleeps = _drive([137])
        self.assertEqual(rc, 0, "\n".join(out))
        self.assertIn("LAUNCHES 2", out)
        self.assertTrue(any("killed from outside" in l for l in out), "\n".join(out))
        self.assertTrue(any("memory" in l for l in out if "killed" in l))

    def test_any_non_zero_exit_restarts(self):
        for code in (1, 134, 139, 143):
            with self.subTest(code=code):
                rc, out, _ = _drive([code])
                self.assertEqual(rc, 0, "\n".join(out))
                self.assertIn("LAUNCHES 2", out)

    def test_backoff_grows_between_restarts(self):
        _, _, sleeps = _drive([137, 137, 137, 137])
        self.assertEqual(sleeps[:4], sorted(sleeps[:4]))
        self.assertGreater(sleeps[3], sleeps[0])

    def test_restarts_are_capped_per_hour(self):
        rc, out, _ = _drive([137] * 30, step_seconds=60)
        self.assertEqual(rc, 137, "\n".join(out))
        launches = [l for l in out if l.startswith("LAUNCHES")]
        self.assertTrue(any("giving up" in l for l in out), "\n".join(out))
        self.assertTrue(any("per hour" in l for l in out), "\n".join(out))
        # a cap, not an endless loop
        self.assertNotIn("LAUNCHES 30", out)

    def test_old_crashes_age_out_of_the_hour(self):
        # Eight kills spread over several hours never reach the hourly cap.
        rc, out, _ = _drive([137] * 8, step_seconds=3000)
        self.assertEqual(rc, 0, "\n".join(out))

    def test_auto_restart_off_still_exits_with_the_code(self):
        rc, out, _ = _drive([137], auto_restart="false")
        self.assertEqual(rc, 137, "\n".join(out))
        self.assertEqual(out.count("[info] Launching Minecraft server"), 1)

    def test_a_requested_stop_is_not_restarted(self):
        rc, out, _ = _drive([137], no_restart=True)
        self.assertEqual(rc, 0, "\n".join(out))
        self.assertIn("LAUNCHES 1", out)


if __name__ == "__main__":
    unittest.main()
