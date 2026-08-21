#!/usr/bin/env python3
"""What BRight reports when Home Assistant refuses a request.

The failure this exists for came from a real install: Test playback got
all the way to the last step and said `HTTP 500 from
/services/media_player/play_media` — which is the status code beside a
red cross that had already said something went wrong. Core had put the
reason in the response body, and `urllib`'s HTTPError *is* that response,
so the one useful sentence available was read and thrown away.

Same rule as the integration's services and the HA bridge, one layer
further down: an answer that is dropped is a success nobody earned.
"""

import io
import sys
import unittest
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "bright" / "panel"
if str(PANEL_DIR) not in sys.path:
    sys.path.append(str(PANEL_DIR))

import ha_client  # noqa: E402


def _raiser(code, body, headers=None):
    """An opener that fails the way urllib fails: with the response."""
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, code, "Server Error", headers or {},
            io.BytesIO(body if isinstance(body, bytes) else body.encode()))
    return opener


class TestCoreGetsToSayWhy(unittest.TestCase):
    def setUp(self):
        self._token = ha_client.SUPERVISOR_TOKEN
        ha_client.SUPERVISOR_TOKEN = "test-token"

    def tearDown(self):
        ha_client.SUPERVISOR_TOKEN = self._token

    def test_a_service_failure_carries_cores_message(self):
        """The real shape: Core answers a failed service call with JSON
        carrying the exception it raised."""
        result = ha_client.play_media(
            "media_player.voice", "media-source://media_source/media/x.wav",
            opener=_raiser(500, '{"message": "Failed to call service '
                                'media_player/play_media. Unsupported media '
                                'type music"}'))
        self.assertIn("HTTP 500", result["error"])
        self.assertIn("Unsupported media type music", result["error"],
                      "the sentence that names the actual problem")

    def test_a_plain_text_body_is_reported_too(self):
        result = ha_client.ha_api_request(
            "/services/x/y", method="POST", data={},
            opener=_raiser(400, "Entity not found"))
        self.assertIn("Entity not found", result["error"])

    def test_an_empty_body_leaves_the_status_alone(self):
        """No detail must stay no detail. Somebody pasting this into a bug
        report should not be pasting our note about the absence of one."""
        result = ha_client.ha_api_request(
            "/services/x/y", method="POST", data={}, opener=_raiser(502, ""))
        self.assertEqual("HTTP 502 from /services/x/y", result["error"])

    def test_a_body_that_cannot_be_read_does_not_replace_the_status(self):
        """This runs while something has already gone wrong. A failure to
        read the explanation must not become the thing reported."""
        class Hostile:
            def read(self):
                raise OSError("connection reset while reading the body")

        def opener(request, timeout=None):
            exc = urllib.error.HTTPError(
                request.full_url, 500, "boom", {}, None)
            exc.read = Hostile().read
            raise exc

        result = ha_client.ha_api_request("/services/x/y", method="POST",
                                          data={}, opener=opener)
        self.assertEqual("HTTP 500 from /services/x/y", result["error"])

    def test_a_long_body_is_capped_on_one_line(self):
        """Core can answer with a whole traceback. It goes in a panel row
        beside five other steps, so it is one line and it is bounded."""
        result = ha_client.ha_api_request(
            "/services/x/y", method="POST", data={},
            opener=_raiser(500, "line one\nline two\n" + "z" * 900))
        error = result["error"]
        self.assertNotIn("\n", error)
        self.assertLess(len(error), 400)
        self.assertIn("line one line two", error)

    def test_an_unreachable_core_is_still_its_own_message(self):
        """The other branch, unchanged — a connection that never happened
        has no body to read and a different sentence to say."""
        def opener(request, timeout=None):
            raise urllib.error.URLError("no route to host")

        result = ha_client.ha_api_request("/states", opener=opener)
        self.assertIn("cannot reach Home Assistant", result["error"])


if __name__ == "__main__":
    unittest.main()
