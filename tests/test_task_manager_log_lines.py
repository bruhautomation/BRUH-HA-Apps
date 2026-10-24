"""A value a request carries cannot forge a line in the add-on's log."""

import unittest

import task_manager_env

(server,) = task_manager_env.load("server")


class TestARequestValueIsOneLogLine(unittest.TestCase):
    def test_a_line_break_in_a_name_does_not_start_a_new_line(self):
        cleaned = server._for_log("Plex\n2026-10-24 ERROR forged line")
        self.assertNotIn("\n", cleaned)
        self.assertTrue(cleaned.startswith("Plex?"))

    def test_other_control_characters_are_replaced_too(self):
        self.assertEqual(server._for_log("a\rb\x1bc\td"), "a?b?c?d")

    def test_an_ordinary_name_is_unchanged(self):
        self.assertEqual(server._for_log("Mosquitto broker"), "Mosquitto broker")

    def test_a_long_value_is_cut(self):
        out = server._for_log("x" * 500)
        self.assertEqual(len(out), 121)
        self.assertTrue(out.endswith("…"))



class TestTheJobLogLine(unittest.IsolatedAsyncioTestCase):
    async def test_a_job_logs_its_name_on_one_line(self):
        class Supervisor:
            async def post(self, path, timeout=0):
                return {}
        monitor = server.Monitor.__new__(server.Monitor)
        monitor.supervisor = Supervisor()
        job = {"id": "x", "key": "core_mosquitto", "action": "restart",
               "name": "Broker\nERROR forged", "status": "running"}
        with self.assertLogs("task_manager", "WARNING") as logs:
            try:
                await monitor._run_job(job)
            except AttributeError:
                pass  # what follows the log line needs a real Monitor
        line = logs.output[0]
        self.assertNotIn("\n", line)
        self.assertIn("Broker?ERROR forged", line)


if __name__ == "__main__":
    unittest.main()
