"""state.json names the running world, so a status asker can say which one.

run.sh's write_state wrote the server's type and settings but not the world,
and minecraft_status read `active_world` from that file and got nothing.
This lifts the real write_state out of run.sh and runs it.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from test_minecraft_crash_restart import _function


class TestStateNamesTheWorld(unittest.TestCase):
    def test_state_json_carries_the_active_world(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp) / "server"
            server.mkdir()
            state = Path(tmp) / "state.json"
            script = textwrap.dedent(f"""
                set -e
                export SERVER_TYPE=paper MINECRAFT_VERSION=1.21 MEMORY_MB=2048
                export ACTIVE_WORLD=Garden
                MC_SERVER_DIR={server}
                MC_STATE_FILE={state}
                {_function("write_state")}
                write_state running
            """)
            subprocess.run(["bash", "-c", script], check=True, timeout=30)
            self.assertEqual(json.loads(state.read_text())["active_world"], "Garden")


if __name__ == "__main__":
    unittest.main()
