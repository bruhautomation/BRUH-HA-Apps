#!/usr/bin/env python3
"""What is coming up reads the weather entity that can answer it.

Occasions took the first `weather.*` in the state list. On a house whose
first one had no daily forecast every read failed with "does not support
'daily' forecast", while another weather entity beside it had one (#635).
The entity is chosen by its `supported_features` now (daily, then
twice-daily, then hourly), and a forecast type it does not have is not
asked for.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import occasions  # noqa: E402
from test_occasions import FORECAST, NOW, FakeCore  # noqa: E402


def weather(eid, features, state="cloudy"):
    return {"entity_id": eid, "state": state,
            "attributes": {"supported_features": features,
                           "temperature_unit": "°C"}}


class TestThePick(unittest.TestCase):
    def test_daily_beats_the_first_in_the_list(self):
        states = [weather("weather.a", occasions.FORECAST_HOURLY),
                  weather("weather.b", occasions.FORECAST_DAILY
                          | occasions.FORECAST_HOURLY)]
        self.assertEqual(occasions.pick_weather(states)["entity_id"], "weather.b")

    def test_twice_daily_beats_hourly_and_unavailable_goes_last(self):
        states = [weather("weather.a", occasions.FORECAST_HOURLY),
                  weather("weather.b", occasions.FORECAST_TWICE_DAILY),
                  weather("weather.c", occasions.FORECAST_DAILY, "unavailable")]
        self.assertEqual(occasions.pick_weather(states)["entity_id"], "weather.b")

    def test_one_entity_is_that_one_and_none_is_none(self):
        self.assertEqual(occasions.pick_weather([weather("weather.x", 0)])
                         ["entity_id"], "weather.x")
        self.assertIsNone(occasions.pick_weather([{"entity_id": "sun.sun"}]))

    def test_an_unsupported_type_is_not_asked_for(self):
        kinds = [c["service_data"]["type"] for c in
                 occasions.commands("weather.a", [], NOW, occasions.FORECAST_HOURLY)]
        self.assertEqual(kinds, ["hourly"])
        kinds = [c["service_data"]["type"] for c in
                 occasions.commands("weather.a", [], NOW, 0)]
        self.assertEqual(kinds, ["daily", "hourly"])


class TestTheReadUsesTheBetterEntity(FakeCore):
    STATES = [weather("weather.first", occasions.FORECAST_HOURLY),
              weather("weather.home", occasions.FORECAST_DAILY
                      | occasions.FORECAST_HOURLY)]

    async def test_the_daily_forecast_comes_back_with_no_error(self):
        weather_id, _unit, daily_rows, _hourly, _cal, errors = \
            await self.server._occasions_fetch([], NOW)
        self.assertEqual(weather_id, "weather.home")
        self.assertEqual(daily_rows, FORECAST)
        self.assertEqual(errors, {})


if __name__ == "__main__":
    unittest.main()
