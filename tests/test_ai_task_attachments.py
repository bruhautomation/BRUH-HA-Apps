#!/usr/bin/env python3
"""`ai_task.generate_data` with a camera attached (#740).

The owner asked for a switch that, while on, has brAIn look at a camera
every ten minutes. brAIn's AI Task entity declared only generate_data, so
an automation could not hand it a camera image. It now declares the
attachments feature; each image attachment is staged in the task image
folder and handed to the run as a picture by the listener, and a camera's
frame is asked of the camera policy first, at the panel, like every other
unattended camera look.
"""
from __future__ import annotations

import http.server
import json
import os
import re
import subprocess
import sys
import threading
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brain_ha_env as env  # noqa: E402
from test_ai_task_and_llm_api import IntegrationCase, run  # noqa: E402

LISTENER = (Path(__file__).resolve().parent.parent / "brain" / "integrations"
            / "automation-listener.sh")
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class WithAttachments(IntegrationCase):
    """The integration loaded against a core that has the feature."""

    def setUp(self):
        had = hasattr(env.AITaskEntityFeature, "SUPPORT_ATTACHMENTS")
        env.AITaskEntityFeature.SUPPORT_ATTACHMENTS = 2
        if not had:
            self.addCleanup(delattr, env.AITaskEntityFeature, "SUPPORT_ATTACHMENTS")
        super().setUp()

    def entity(self):
        added = []
        entry = types.SimpleNamespace(entry_id="e1", data={}, options={})
        run(self.pkg.ai_task.async_setup_entry(self.hass, entry, added.extend))
        ent = added[0]
        ent.hass = self.hass
        return ent

    def attachment(self, name: str, mime: str, source: str, data: bytes = JPEG):
        path = Path(self.tmp.name) / name
        path.write_bytes(data)
        return types.SimpleNamespace(media_content_id=source, mime_type=mime,
                                     path=path)


class TestTheEntityTakesACamera(WithAttachments):

    def test_it_declares_the_attachments_feature(self):
        features = self.entity()._attr_supported_features
        self.assertTrue(features & env.AITaskEntityFeature.GENERATE_DATA)
        self.assertTrue(features & env.AITaskEntityFeature.SUPPORT_ATTACHMENTS)

    def test_a_camera_frame_reaches_the_run_as_a_picture_and_structure_comes_back(self):
        seen = {}

        def structure(data):
            if not isinstance(data, dict) or not isinstance(data.get("people"), int):
                raise ValueError("people is required")
            return data

        test = self
        bridge = self.hass.data[self.pkg.const.DOMAIN]["entry"]
        real = type(bridge).async_send_task_full

        async def send(self_, **kw):
            # What the listener would find: the staged files, still there.
            seen["files"] = [Path(p).read_bytes() for p in kw["images"]]
            return await real(self_, **kw)
        type(bridge).async_send_task_full = send
        self.addCleanup(setattr, type(bridge), "async_send_task_full", real)

        task = env.GenDataTask(
            name="Porch", instructions="How many people are at the door?",
            structure=structure,
            attachments=[
                self.attachment("snap.jpg", "image/jpeg",
                                "media-source://camera/camera.front_porch"),
                self.attachment("notes.txt", "text/plain",
                                "media-source://media_source/local/notes.txt",
                                b"hello"),
            ])
        self.answer = {"text": "", "data": {"people": 2}}
        result = run(self.entity()._async_generate_data(
            task, types.SimpleNamespace(conversation_id="c")))
        self.assertEqual(result.data, {"people": 2})
        [sent] = test.sent
        self.assertEqual(sent["tools"], "read_only")
        self.assertEqual(sent["image_cameras"], ["camera.front_porch"])
        self.assertEqual(len(sent["images"]), 1)
        image_dir = os.path.realpath(bridge.task_image_dir)
        self.assertEqual(os.path.dirname(os.path.realpath(sent["images"][0])), image_dir)
        self.assertEqual(seen["files"], [JPEG])
        self.assertIn("1 picture(s)", sent["prompt"])
        self.assertIn("1 attachment(s) were not pictures", sent["prompt"])
        # Nothing is left behind once the task has its answer.
        self.assertEqual(os.listdir(image_dir), [])

    def test_the_bridge_writes_the_pictures_into_the_task(self):
        bridge = self.pkg.bridge.ClaudeBridge(self.hass)
        os.makedirs(bridge.task_image_dir, exist_ok=True)
        inside = os.path.join(bridge.task_image_dir, "a.jpg")
        Path(inside).write_bytes(JPEG)
        outside = os.path.join(self.tmp.name, "secrets.jpg")
        written = {}

        def capture(path, data):
            written.update(data)
            raise RuntimeError("stop here")
        bridge._write_json = capture
        with self.assertRaises(RuntimeError):
            run(bridge.async_send_task_full(
                prompt="look", images=[inside, outside],
                image_cameras=["camera.front_porch", "light.x"]))
        self.assertEqual(written["images"], [inside])
        self.assertEqual(written["image_cameras"], ["camera.front_porch"])


class _Panel(http.server.BaseHTTPRequestHandler):
    reply: dict | None = {"allowed": True, "reason": ""}
    asked: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).asked.append(body)
        out = json.dumps(type(self).reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class TestTheListenerAsksTheCameraPolicy(unittest.TestCase):

    def setUp(self):
        _Panel.asked = []
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _Panel)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def refusal(self, cameras: str, url: str | None = None) -> str:
        src = LISTENER.read_text(encoding="utf-8")
        fn = re.search(r"^task_camera_refusal\(\) \{\n.*?^\}$", src, re.S | re.M).group(0)
        out = subprocess.run(
            ["bash", "-c", fn + '\ntask_camera_refusal "$1"\n', "x", cameras],
            capture_output=True, text=True, timeout=30, check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "BRAIN_PANEL_URL": url or self.url})
        return out.stdout.strip()

    def test_an_allowed_frame_is_counted_and_runs(self):
        _Panel.reply = {"allowed": True, "reason": ""}
        self.assertEqual(self.refusal("camera.front_porch"), "")
        self.assertEqual(_Panel.asked, [{"entity_id": "camera.front_porch",
                                         "channel": "task"}])

    def test_a_refused_frame_says_the_panels_sentence(self):
        _Panel.reply = {"allowed": False,
                        "reason": "brAIn has used today's 12 camera looks; it can look again tomorrow."}
        self.assertIn("12 camera looks", self.refusal("camera.front_porch"))

    def test_a_panel_that_does_not_answer_refuses(self):
        self.assertIn("could not ask", self.refusal("camera.front_porch",
                                                    url="http://127.0.0.1:9"))

    def test_the_refusal_comes_before_the_pictures_are_read(self):
        src = LISTENER.read_text(encoding="utf-8")
        body = src.split("process_task() {", 1)[1]
        self.assertLess(body.index("task_camera_refusal \"$task_image_cameras\""),
                        body.index("image_message=$(task_images_message"))


if __name__ == "__main__":
    unittest.main()
