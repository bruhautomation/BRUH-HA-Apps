"""BRUH Task Manager: reading /proc, naming containers, and the arithmetic.

Driven against a /proc tree written in the kernel's own layout
(tests/task_manager_fake.py), because the failure modes here are parsing
ones: a comm with a space and a parenthesis in it, a cgroup path from inside
a private cgroup namespace, a mountinfo path with an escaped space.
"""
import os
import shutil
import tempfile
import unittest

import task_manager_env

procs, machine, runaway = task_manager_env.load("procs", "machine", "runaway")
fake_mod = task_manager_env.fake()


class TestParsing(unittest.TestCase):
    def test_a_comm_with_spaces_and_parentheses_is_read_whole(self):
        comm, rest = procs.parse_stat("42 (Web (Content) 2) S 1 0 0 0 -1 4194560 "
                                      + " ".join(["0"] * 40))
        self.assertEqual("Web (Content) 2", comm)
        self.assertEqual("S", rest[0])
        self.assertEqual("1", rest[1])

    def test_the_v2_line_names_the_container(self):
        cid = "a" * 64
        text = f"0::/system.slice/docker-{cid}.scope\n"
        self.assertIn(cid, procs.parse_cgroup(text))

    def test_a_path_outside_our_cgroup_namespace_still_names_it(self):
        # From inside a private cgroup namespace other containers read as
        # "/../docker-<id>.scope": the regex must not need the slice.
        cid = "b" * 64
        path = procs.parse_cgroup(f"0::/../docker-{cid}.scope\n")
        self.assertEqual(cid, procs.CONTAINER_RE.search(path).group(1))

    def test_v1_falls_back_to_the_first_docker_line(self):
        cid = "c" * 64
        text = f"12:memory:/docker/{cid}\n11:cpu:/docker/{cid}\n0::/\n"
        self.assertIn(cid, procs.parse_cgroup(text))

    def test_mountinfo_unescapes_and_finds_the_addon_slug(self):
        info = ("1 0 0:1 / / rw - overlay overlay rw\n"
                "2 1 8:1 /supervisor/addons/data/local_my\\040app /data rw - ext4 /dev/sda8 rw\n")
        found = procs.identify_mounts(info)
        self.assertEqual(("addon", "addon:local_my app"), (found.kind, found.key))

    def test_home_assistant_is_the_container_with_config_and_no_data(self):
        info = "2 1 8:1 /supervisor/homeassistant /config rw - ext4 /dev/sda8 rw\n"
        self.assertEqual("core", procs.identify_mounts(info).kind)

    def test_an_app_that_maps_config_is_still_the_app(self):
        info = ("2 1 8:1 /supervisor/homeassistant /config rw - ext4 /dev/sda8 rw\n"
                "3 1 8:1 /supervisor/addons/data/core_mosquitto /data rw - ext4 /dev/sda8 rw\n")
        self.assertEqual("addon:core_mosquitto", procs.identify_mounts(info).key)

    def test_a_data_mount_nobody_recognises_names_nothing(self):
        info = "3 1 8:1 /somewhere/else /data rw - ext4 /dev/sda8 rw\n"
        self.assertIsNone(procs.identify_mounts(info))

    def test_plugins_are_named_by_their_command(self):
        self.assertEqual("plugin:dns",
                         procs.identify_commands(["coredns -conf /config/corefile"]).key)
        self.assertIsNone(procs.identify_commands(["/usr/bin/mystery"]))

    def test_os_units_read_as_their_service_name(self):
        self.assertEqual("NetworkManager",
                         procs.os_unit("/system.slice/NetworkManager.service"))
        self.assertEqual("systemd", procs.os_unit("/init.scope"))


class FakeMachine(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.fake = fake_mod.FakeProc(os.path.join(self.dir, "proc"))
        self.clock = [100.0]
        self.sampler = procs.ProcessSampler(self.fake.root, self_pid=901,
                                            clock=lambda: self.clock[0],
                                            hz=100, ncpu=4)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def groups(self, sample):
        return {g["key"]: g for g in sample["groups"]}


class TestGrouping(FakeMachine):
    def test_every_process_lands_with_its_owner(self):
        groups = self.groups(self.sampler.sample())
        expect = {
            "kernel": {2, 12}, "os": {1, 210, 220}, "supervisor": {300},
            "core": {400, 401, 402}, "addon:core_mosquitto": {500, 501, 502},
            "addon:a0d7b954_vscode": {600, 601, 602}, "plugin:dns": {700},
            "self": {900, 901},
        }
        for key, pids in expect.items():
            with self.subTest(group=key):
                self.assertEqual(pids, {p["pid"] for p in groups[key]["procs"]})
        unknown = [k for k in groups if k.startswith("container:")]
        self.assertEqual(1, len(unknown), "the mystery container is unknown, not guessed")

    def test_the_first_reading_has_no_cpu_and_says_so(self):
        sample = self.sampler.sample()
        self.assertFalse(sample["measured"])
        self.assertTrue(all(p["cpu"] is None
                            for g in sample["groups"] for p in g["procs"]))

    def test_cpu_is_a_share_of_the_whole_machine(self):
        self.sampler.sample()
        self.fake.advance(2.0, jitter=False)
        self.clock[0] += 2.0
        groups = self.groups(self.sampler.sample())
        host = {p["pid"]: p for p in groups["addon:a0d7b954_vscode"]["procs"]}
        # Weight 90 = 0.9 of one CPU, on a 4-CPU machine: 22.5%.
        self.assertAlmostEqual(22.5, host[602]["cpu"], places=1)
        self.assertAlmostEqual(sum(p["cpu"] for p in host.values()),
                               groups["addon:a0d7b954_vscode"]["cpu"], places=1)

    def test_a_reused_pid_does_not_inherit_the_old_process_ticks(self):
        self.sampler.sample()
        # Same pid, a different start time and a huge tick count: a new
        # process that happens to have been given the old one's number.
        with open(os.path.join(self.fake.root, "602", "stat"), "w") as handle:
            handle.write(fake_mod.stat_line(602, "node", "S", 601, 0, 999_999_999, 4, 77777))
        self.clock[0] += 2.0
        groups = self.groups(self.sampler.sample())
        row = next(p for p in groups["addon:a0d7b954_vscode"]["procs"] if p["pid"] == 602)
        self.assertIsNone(row["cpu"], "a new process must not be charged the old one's ticks")

    def test_kernel_threads_are_the_proof_of_the_host_namespace(self):
        self.assertTrue(procs.host_visible(self.fake.root))

    def test_a_private_namespace_is_not_the_host(self):
        private = os.path.join(self.dir, "private")
        procs_, mounts = fake_mod.private_namespace()
        fake_mod.FakeProc(private, procs_, mounts)
        self.assertFalse(procs.host_visible(private))

    def test_resident_memory_is_read_and_proportional_left_absent(self):
        groups = self.groups(self.sampler.sample())
        row = groups["core"]["procs"]
        ha = next(p for p in row if p["pid"] == 401)
        self.assertEqual(620000, ha["rss_kb"])
        self.assertIsNone(ha["pss_kb"], "no smaps_rollup is not a zero")

    def test_describe_reads_one_process_fresh(self):
        self.sampler.sample()
        proc, ident = self.sampler.describe(602)
        self.assertEqual("node", proc.comm)
        self.assertEqual("addon:a0d7b954_vscode", ident.key)
        self.fake.end(602)
        self.assertEqual((None, None), self.sampler.describe(602))


class TestMachine(FakeMachine):
    def test_cpu_is_busy_over_total_between_two_readings(self):
        m = machine.MachineSampler(self.fake.root, ncpu=4)
        self.assertIsNone(m.sample()["cpu"])
        self.fake.cpu_total = [self.fake.cpu_total[0] + 100, self.fake.cpu_total[1] + 300]
        self.fake.write()
        reading = m.sample()
        self.assertEqual(25.0, reading["cpu"])
        self.assertEqual(3900000 * 1024, reading["mem_total"])
        self.assertEqual((3900000 - 1500000) * 1024, reading["mem_used"])
        self.assertEqual([1.42, 1.10, 0.95], reading["load"])


class TestRunaway(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.tracker = runaway.RunawayTracker(clock=lambda: self.now[0])

    def step(self, cpu, minutes=1):
        self.now[0] += minutes * 60
        return self.tracker.update([{"key": "addon:x", "name": "X", "cpu": cpu}], 80, 10)

    def test_a_streak_long_enough_is_running_away(self):
        self.tracker.update([{"key": "addon:x", "name": "X", "cpu": 95}], 80, 10)
        for _ in range(9):
            self.assertEqual([], self.step(95))
        self.assertEqual(["addon:x"], [r["key"] for r in self.step(95)])

    def test_a_dip_ends_the_streak(self):
        self.tracker.update([{"key": "addon:x", "name": "X", "cpu": 95}], 80, 10)
        for _ in range(8):
            self.step(95)
        self.step(10)
        for _ in range(9):
            self.assertEqual([], self.step(95))

    def test_a_missing_reading_is_not_a_dip(self):
        self.tracker.update([{"key": "addon:x", "name": "X", "cpu": 95}], 80, 10)
        for _ in range(5):
            self.step(95)
        self.step(None)
        for _ in range(3):
            self.step(95)
        self.assertEqual(1, len(self.step(95)))

    def test_this_add_on_is_never_reported(self):
        out = self.tracker.update([{"key": "addon:me", "cpu": 100, "is_self": True}], 80, 0)
        self.assertEqual([], out)


if __name__ == "__main__":
    unittest.main()
