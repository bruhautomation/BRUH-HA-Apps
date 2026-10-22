"""BRUH Task Manager: which processes may be ended, and ending them.

The policy is asked twice — when the page is drawn and again over a fresh
read when End is pressed — so both are tested: the table of refusals, and
the route's re-ask against a process that is not what the page showed.
"""
import asyncio
import errno
import os
import shutil
import signal
import tempfile
import unittest

import task_manager_env

policy, procs, ending = task_manager_env.load("policy", "procs", "ending")
fake_mod = task_manager_env.fake()

ON = {"level2_active": True, "ending_on": True}


def row(**kw):
    base = {"pid": 500, "name": "worker", "cmd": "worker --go", "ns_pid": 7,
            "kernel": False}
    base.update(kw)
    return base


class TestVerdict(unittest.TestCase):
    def test_an_app_process_may_be_ended(self):
        ok, why = policy.verdict(row(), {"kind": "addon", "name": "Frigate"}, **ON)
        self.assertTrue(ok)
        self.assertEqual("", why)

    def test_nothing_outside_an_app_may_be_ended_and_each_says_why(self):
        for kind in ("kernel", "os", "supervisor", "core", "plugin", "self", "container"):
            with self.subTest(kind=kind):
                ok, why = policy.verdict(row(), {"kind": kind}, **ON)
                self.assertFalse(ok)
                self.assertEqual(policy.REFUSALS[kind], why)

    def test_home_assistant_and_the_supervisor_point_at_restart(self):
        for kind in ("core", "supervisor", "plugin"):
            self.assertIn("Restart", policy.REFUSALS[kind])

    def test_an_unknown_kind_is_refused_as_unknown(self):
        ok, why = policy.verdict(row(), {"kind": "surprise"}, **ON)
        self.assertFalse(ok)
        self.assertEqual(policy.REFUSALS["container"], why)

    def test_an_apps_init_is_refused_by_namespace_pid_or_name(self):
        group = {"kind": "addon", "name": "Frigate"}
        self.assertFalse(policy.verdict(row(ns_pid=1), group, **ON)[0])
        for name in ("s6-svscan", "s6-supervise", "tini"):
            ok, why = policy.verdict(row(name=name), group, **ON)
            self.assertFalse(ok)
            self.assertIn("keeps Frigate running", why)

    def test_the_protected_list_matches_names_executables_and_slugs(self):
        group = {"kind": "addon", "name": "Frigate", "slug": "ccab4aaf_frigate"}
        for pattern in ("worker", "WORKER", "*_frigate", "frig*"):
            with self.subTest(pattern=pattern):
                ok, why = policy.verdict(row(), group, protected=[pattern], **ON)
                self.assertFalse(ok)
                self.assertIn("Never end these", why)
        self.assertTrue(policy.verdict(row(), group, protected=["mosquitto", ""], **ON)[0])

    def test_both_switches_have_to_be_on(self):
        group = {"kind": "addon"}
        self.assertFalse(policy.verdict(row(), group, level2_active=False, ending_on=True)[0])
        ok, why = policy.verdict(row(), group, level2_active=True, ending_on=False)
        self.assertFalse(ok)
        self.assertIn("switched off", why)


class TestEnding(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.fake = fake_mod.FakeProc(os.path.join(self.dir, "proc"))
        self.sampler = procs.ProcessSampler(self.fake.root, self_pid=901, hz=100, ncpu=4)
        self.sampler.sample()
        self.sent = []
        self.clock = [0.0]
        self.behaviour = "obey"

        def kill(pid, sig):
            self.sent.append((pid, sig))
            if self.behaviour == "denied":
                raise PermissionError(errno.EACCES, "Permission denied")
            if self.behaviour == "gone":
                raise ProcessLookupError()
            if self.behaviour == "obey" or sig == signal.SIGKILL:
                self.fake.end(pid)

        async def sleep(_s):
            self.clock[0] += _s
            await asyncio.sleep(0)

        self.ender = ending.Ender(self.sampler, kill=kill, clock=lambda: self.clock[0],
                                  sleep=sleep)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def allowed(self, proc, identity):
        group = {"kind": identity.kind, "name": identity.name, "slug": identity.slug}
        return policy.verdict(procs.row_of(proc, None), group, **ON)

    def start_of(self, pid):
        return procs.read_proc(self.fake.root, pid).start

    async def test_asking_works_and_sends_term_only(self):
        result = await self.ender.end(602, self.start_of(602), False, self.allowed)
        self.assertEqual("ended", result["outcome"])
        self.assertEqual([(602, signal.SIGTERM)], self.sent)

    async def test_force_is_refused_before_asking_and_during_the_grace(self):
        start = self.start_of(602)
        result = await self.ender.end(602, start, True, self.allowed)
        self.assertEqual("ask_first", result["outcome"])
        self.assertEqual([], self.sent)
        self.behaviour = "ignore"
        asked = await self.ender.end(602, start, False, self.allowed)
        self.assertEqual("asked", asked["outcome"])
        self.clock[0] = self.ender.asked[(602, start)] + 1.0  # inside the grace
        early = await self.ender.end(602, start, True, self.allowed)
        self.assertEqual("too_soon", early["outcome"])
        self.clock[0] = ending.GRACE_S + 1
        forced = await self.ender.end(602, start, True, self.allowed)
        self.assertEqual("ended", forced["outcome"])
        self.assertEqual(signal.SIGKILL, self.sent[-1][1])

    async def test_a_different_process_under_that_pid_is_not_signalled(self):
        result = await self.ender.end(602, self.start_of(602) + 1, False, self.allowed)
        self.assertEqual("changed", result["outcome"])
        self.assertEqual([], self.sent)

    async def test_policy_is_asked_over_the_fresh_read(self):
        result = await self.ender.end(401, self.start_of(401), False, self.allowed)
        self.assertEqual("refused", result["outcome"])
        self.assertIn("Home Assistant itself", result["message"])
        self.assertEqual([], self.sent)

    async def test_a_kernel_refusal_names_restart(self):
        self.behaviour = "denied"
        result = await self.ender.end(602, self.start_of(602), False, self.allowed)
        self.assertEqual("denied", result["outcome"])
        self.assertIn("security profile", result["message"])
        self.assertIn("Use Restart on", result["message"])

    async def test_a_process_that_already_went_is_gone_not_an_error(self):
        self.behaviour = "gone"
        result = await self.ender.end(602, self.start_of(602), False, self.allowed)
        self.assertTrue(result["ok"])
        self.assertEqual("gone", result["outcome"])
        self.fake.end(601)
        result = await self.ender.end(601, 1, False, self.allowed)
        self.assertEqual("gone", result["outcome"])


if __name__ == "__main__":
    unittest.main()
