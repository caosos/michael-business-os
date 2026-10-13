"""Direct, dependency-free tests for the Bright Data Facebook seam."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from operator_ui import market_facebook as fb


NOW = datetime(2026, 10, 13, 1, 30, tzinfo=timezone.utc)


class FacebookDirectTests(unittest.TestCase):
    def test_sync_discovery_then_listing_and_private_fields_removed(self):
        calls = []

        def request(method, url, headers, body, timeout):
            calls.append((method, url, headers, body, timeout))
            if "discover_new" in url:
                return 200, {}, json.dumps([{"url": "https://www.facebook.com/marketplace/item/123/"}]).encode()
            return 200, {}, json.dumps([{"url": "https://www.facebook.com/marketplace/item/123/", "product_id": "123",
                                         "title": "5x8 utility trailer", "final_price": "$450", "location": "Conway, AR",
                                         "seller_name": "private", "profile": {"id": "private"}}]).encode()

        client = fb.BrightDataClient("secret-token", request=request, sleep=lambda _: None)
        rows = client.search("utility trailer", "72032", 30)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("seller_name", rows[0])
        self.assertNotIn("profile", rows[0])
        self.assertEqual(len(calls), 2)
        self.assertIn("limit_per_input=20", calls[0][1])
        self.assertNotIn("secret-token", calls[0][1])

    def test_http_202_is_polled_and_downloaded(self):
        calls = []
        progress = iter(("running", "ready"))

        def request(method, url, headers, body, timeout):
            calls.append((method, url))
            if "/scrape?" in url:
                return 202, {}, b'{"snapshot_id":"s_abc123"}'
            if "/progress/" in url:
                return 200, {}, json.dumps({"status": next(progress)}).encode()
            if "/snapshot/" in url:
                return 200, {}, json.dumps([{"url": "https://www.facebook.com/marketplace/item/7/", "title": "Tool chest"}]).encode()
            raise AssertionError(url)

        rows = fb.BrightDataClient("token", request=request, sleep=lambda _: None).search("tools", "Conway, AR", 30)
        self.assertEqual(rows[0]["title"], "Tool chest")
        self.assertEqual([method for method, _ in calls], ["POST", "GET", "GET", "GET"])
        self.assertTrue(calls[-1][1].endswith("/snapshot/s_abc123?format=json"))

    def test_cap_and_card_shape(self):
        rows = [{"url": f"https://www.facebook.com/marketplace/item/{n}/", "title": f"Tool {n}", "price": n,
                 "location": {"name": "Conway, AR 72032", "latitude": 35.0887, "longitude": -92.4421},
                 "images": [{"url": f"https://img.example/{n}.jpg"}], "listing_date": "2026-10-12T10:00:00Z"}
                for n in range(30)]
        cards = fb.cards(rows, NOW.isoformat(), (35.0887, -92.4421))
        self.assertEqual(len(cards), fb.HARD_CAP)
        self.assertEqual(cards[0]["source"], "Facebook Marketplace")
        self.assertEqual(cards[0]["kind"], "fixed")
        self.assertEqual(cards[0]["distance"], 0.0)
        self.assertEqual(cards[0]["zip"], "72032")

    def test_failed_refresh_falls_back_to_last_successful_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facebook.json"
            path.write_text(json.dumps({"as_of": NOW.isoformat(), "records": [
                {"url": "https://www.facebook.com/marketplace/item/1/", "title": "Mower", "price": 75}
            ]}))

            class Broken:
                def search(self, *args):
                    raise fb.BrightDataError("provider unavailable")

            result = fb.load(NOW, keyword="mower", city="72032", radius=30, refresh=True, client=Broken(), path=path)
            self.assertEqual(result["status"], "connected")
            self.assertEqual(len(result["cards"]), 1)
            self.assertIn("Live refresh failed", result["message"])

    def test_error_scrubs_token(self):
        def request(*args):
            raise RuntimeError("bad secret-token")

        with self.assertRaises(fb.BrightDataError) as caught:
            fb.BrightDataClient("secret-token", request=request).search("tools", "72032", 30)
        self.assertNotIn("secret-token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
