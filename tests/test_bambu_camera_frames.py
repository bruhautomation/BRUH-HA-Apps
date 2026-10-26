#!/usr/bin/env python3
"""A camera frame on screen is a whole picture of the printer, nothing else.

Two ways a green band reached the Printers tab, both at the source:

* A frame cut short (a P1/A1 frame whose bytes stop before the JPEG's end
  marker, or a stream that dropped mid-picture) decodes with the missing
  rows painted in, which in a YUV JPEG is a green or grey band. A frame is
  kept only when it starts with the start-of-image marker and ends with the
  end-of-image one, and the last whole frame stays on screen meanwhile.
* A camera that encodes 1080 rows as 1088 (a whole number of 16-row blocks)
  and says 1088 in the frame's header sends eight rows that are not the
  picture: decoded, they are a green bar along the bottom. A 16:9 picture
  that is eight rows too tall is told its real height, which the decoder
  then crops to: no pixel is decoded differently.
"""
import os
import socket
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402

camera, = bambu_env.load("bambu.camera")


def jpeg(width: int, height: int, body: bytes = b"\x11" * 64) -> bytes:
    """A JPEG's markers in the order a camera writes them, with a body."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    sos = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    return b"\xff\xd8" + app0 + sof + sos + body + b"\xff\xd9"


def size_of(frame: bytes):
    i = frame.index(b"\xff\xc0")
    height, width = struct.unpack(">HH", frame[i + 5:i + 9])
    return width, height


class TestOnlyWholeFramesAreShown(unittest.TestCase):
    def test_a_frame_cut_short_is_never_served(self):
        cam = camera.Camera("10.0.0.2", "code", "jpeg")
        good = jpeg(1280, 720)
        cam._got(good)
        cut = jpeg(1280, 720)[:-40]
        cam._got(cut)
        self.assertEqual(cam.frame, good)

    def test_a_frame_cut_short_off_the_wire_is_dropped_and_the_next_one_kept(self):
        good, cut = jpeg(1280, 720), jpeg(1280, 720)[:-30] + b"\x00" * 30
        a, b = socket.socketpair()
        try:
            for frame in (cut, good):
                a.sendall(struct.pack("<I", len(frame)) + b"\x00" * 12 + frame)
            cam = camera.Camera("10.0.0.2", "code", "jpeg")
            for _ in range(2):
                cam._got(camera.read_frame(b))
                if cam.frame is not None:
                    break
            self.assertEqual(cam.frame, good)
        finally:
            a.close()
            b.close()

    def test_padding_after_the_end_marker_is_still_a_whole_frame(self):
        self.assertTrue(camera.whole(jpeg(640, 360) + b"\x00\x00"))
        self.assertFalse(camera.whole(jpeg(640, 360)[:-1]))
        self.assertFalse(camera.whole(b"nope"))


class TestThePaddedRowsAreNotShown(unittest.TestCase):
    def test_a_1088_row_16_by_9_picture_is_told_it_is_1080(self):
        fixed = camera.fit(jpeg(1920, 1088))
        self.assertEqual(size_of(fixed), (1920, 1080))
        self.assertEqual(len(fixed), len(jpeg(1920, 1088)))

    def test_a_720_row_picture_and_a_4_by_3_one_are_left_alone(self):
        for w, h in ((1280, 720), (640, 480), (1920, 1080)):
            with self.subTest(size=(w, h)):
                frame = jpeg(w, h)
                self.assertEqual(camera.fit(frame), frame)

    def test_the_fixed_frame_is_what_is_kept(self):
        cam = camera.Camera("10.0.0.2", "code", "jpeg")
        cam._got(jpeg(1920, 1088))
        self.assertEqual(size_of(cam.frame), (1920, 1080))

    def test_garbage_is_not_fitted_into_anything(self):
        self.assertEqual(camera.fit(b"\xff\xd8\xff"), b"\xff\xd8\xff")


if __name__ == "__main__":
    unittest.main()
