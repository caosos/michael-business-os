"""Direct, dependency-free tests for the Bright Data Facebook seam."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from operator_ui import market_facebook as fb
from operator_ui import market_source_view as source_view


NOW = datetime(2026, 10, 13, 1, 30, tzinfo=timezone.utc)


class FacebookDirectTests(unittest.TestCase):
    def test_missing_listing_location_never_breaks_the_feed(self):
        self.assertIsNone(fb._distance((35.1, -92.4), None))

    def test_sync_discovery_then_listing_and_private_fields_removed(self):
        calls = []

        def request(method, url, headers, body, timeout):
            calls.append((method, url, headers, body, timeout))
            if len(calls) == 1:
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
        self.assertNotIn("limit_per_input", calls[0][1])
        self.assertIn("discover_by=keyword", calls[0][1])
        self.assertIn("type=discover_new", calls[0][1])
        self.assertNotIn("secret-token", calls[0][1])
        self.assertEqual(json.loads(calls[0][3]), {"input": [{"keyword": "utility trailer", "city": "Conway, AR"}], "limit_per_input": 20})
        self.assertEqual(json.loads(calls[1][3]),
                         {"input": [{"url": "https://www.facebook.com/marketplace/item/123/"}], "limit_per_input": 1})

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

    def test_pending_snapshot_is_saved_and_resumed_without_a_second_paid_search(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facebook.json"

            class PendingThenReady:
                def __init__(self):
                    self.searches = 0
                    self.resumes = 0

                def search(self, *args):
                    self.searches += 1
                    raise fb.BrightDataPending("s_keep123")

                def resume(self, snapshot_id):
                    self.resumes += 1
                    self.assert_id = snapshot_id
                    return [{"url": "https://www.facebook.com/marketplace/item/9/", "title": "Utility trailer"}]

            provider = PendingThenReady()
            first = fb.load(NOW, keyword="trailer", city="72032", radius=30, refresh=True, client=provider, path=path)
            self.assertEqual(first["status"], "offline")
            self.assertIn("still running", first["message"])
            second = fb.load(NOW, keyword="trailer", city="72032", radius=30, refresh=True, client=provider, path=path)
            self.assertEqual(second["status"], "connected")
            self.assertEqual((provider.searches, provider.resumes, provider.assert_id), (1, 1, "s_keep123"))

    def test_merged_cap_and_card_shape(self):
        rows = [{"url": f"https://www.facebook.com/marketplace/item/{n}/", "title": f"Tool {n}", "price": n,
                 "location": {"name": "Conway, AR 72032", "latitude": 35.0887, "longitude": -92.4421},
                 "images": [{"url": f"https://img.example/{n}.jpg"}], "listing_date": "2026-10-12T10:00:00Z"}
                for n in range(30)]
        cards = fb.cards(rows, NOW.isoformat(), (35.0887, -92.4421))
        self.assertEqual(len(cards), 30)
        self.assertEqual(cards[0]["source"], "Facebook Marketplace")
        self.assertEqual(cards[0]["kind"], "fixed")
        self.assertEqual(cards[0]["distance"], 0.0)
        self.assertEqual(cards[0]["zip"], "72032")

    def test_default_density_search_uses_multiple_bounded_inputs_and_dedupes(self):
        calls = []

        def request(method, url, headers, body, timeout):
            calls.append((url, json.loads(body)))
            return 200, {}, json.dumps([
                {"url": "https://www.facebook.com/marketplace/item/1/", "title": "Trailer"},
                {"url": "https://www.facebook.com/marketplace/item/1/", "title": "Trailer duplicate"},
                {"url": "https://www.facebook.com/marketplace/item/2/", "title": "Mower"},
            ]).encode()

        rows = fb.BrightDataClient("token", request=request).search_many(fb.DENSITY_TERMS, "72032", 30)
        self.assertEqual([row["title"] for row in rows], ["Trailer", "Mower"])
        self.assertEqual(len(calls[0][1]["input"]), len(fb.DENSITY_TERMS))
        self.assertEqual(calls[0][1]["limit_per_input"], fb.HARD_CAP)
        self.assertTrue(all(set(value) == {"keyword", "city"} for value in calls[0][1]["input"]))

    def test_different_searches_accumulate_fresh_deduped_shards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facebook.json"

            class Provider:
                def search(self, keyword, *_):
                    common = {"url": "https://www.facebook.com/marketplace/item/1/", "title": "Shared"}
                    return [common, {"url": f"https://www.facebook.com/marketplace/item/{2 if keyword == 'tools' else 3}/",
                                     "title": keyword}]

            provider = Provider()
            first = fb.load(NOW, keyword="tools", city="72032", radius=30, refresh=True, client=provider, path=path)
            later = NOW.replace(minute=50)
            second = fb.load(later, keyword="mower", city="72032", radius=30, refresh=True, client=provider, path=path)
            self.assertEqual(len(first["cards"]), 2)
            self.assertEqual({card["title"] for card in second["cards"]}, {"Shared", "tools", "mower"})
            doc = json.loads(path.read_text())
            self.assertEqual(len(doc["shards"]), 2)
            self.assertEqual(len(doc["records"]), 3)

    def test_town_without_provider_coordinates_uses_local_gazetteer(self):
        rows = [{"url": "https://www.facebook.com/marketplace/item/1/", "title": "Mower",
                 "location": "Conway, AR"}]
        cards = fb.cards(rows, NOW.isoformat(), (35.0887, -92.4421))
        self.assertIsNotNone(cards[0]["distance"])
        self.assertLess(cards[0]["distance"], 5)

    def test_documented_api_key_name_and_file_alias_are_supported(self):
        with patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "official-name", "BRIGHTDATA_TOKEN": ""}, clear=False):
            self.assertEqual(fb.token(), "official-name")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "", "BRIGHTDATA_TOKEN": ""}, clear=False):
            key_file = Path(directory) / "BRIGHTDATA_API_KEY"
            key_file.write_text("file-key\n", encoding="utf-8")
            self.assertEqual(fb.token(key_file), "file-key")

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

    def test_same_recent_query_reuses_cache_without_a_paid_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facebook.json"
            path.write_text(json.dumps({"as_of": NOW.isoformat(), "query": {"keyword": "tools", "city": "72032", "radius": 30},
                                        "records": [{"url": "https://www.facebook.com/marketplace/item/1/", "title": "Tools"}]}))

            class MustNotRun:
                def search(self, *args):
                    raise AssertionError("recent identical query should use its cache")

            result = fb.load(NOW, keyword="tools", city="72032", radius=30, refresh=True, client=MustNotRun(), path=path)
            self.assertEqual(result["status"], "connected")
            self.assertEqual(result["cards"][0]["title"], "Tools")

    def test_no_paid_refresh_without_explicit_search(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facebook.json"

            class MustNotRun:
                def search(self, *args):
                    raise AssertionError("ordinary page loads must not call the paid provider")

            result = fb.load(NOW, keyword="tools", city="72032", radius=30,
                             refresh=False, client=MustNotRun(), path=path)
            self.assertEqual(result["status"], "offline")
            self.assertFalse(path.exists())

    def test_probe_distinguishes_configured_credential_from_successful_cache(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "configured", "BRIGHTDATA_TOKEN": ""}, clear=False):
            result = fb.probe(NOW, Path(directory) / "missing.json")
            self.assertEqual(result["status"], "offline")
            self.assertTrue(result["credential_configured"])
            self.assertIn("No successful", result["message"])

    def test_facebook_and_multi_source_filters_are_not_blocked_by_legacy_gate(self):
        self.assertIsNone(source_view.gate({"source": "facebook"}, {}))
        self.assertIsNone(source_view.gate({"source": "gsa,facebook"}, {}))
        self.assertIsNotNone(source_view.gate({"source": "unknown-provider"}, {}))


if __name__ == "__main__":
    unittest.main()
