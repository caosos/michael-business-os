"""Direct, dependency-free tests for the Facebook historical-cache seam. Paid-provider client behaviour was removed by DS-SOURCE-01
(see tests/test_ds_source01_no_paid.py, which proves every paid path is denied)."""

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

    def test_private_fields_are_removed_from_cached_rows(self):
        rows = fb._rows(json.dumps([{"url": "https://www.facebook.com/marketplace/item/123/", "title": "5x8 utility trailer",
                                     "seller_name": "private", "profile": {"id": "private"}}]).encode())
        self.assertNotIn("seller_name", rows[0])
        self.assertNotIn("profile", rows[0])

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
            self.assertIn("does not use paid listing providers", result["message"])

    def test_facebook_and_multi_source_filters_are_not_blocked_by_legacy_gate(self):
        self.assertIsNone(source_view.gate({"source": "facebook"}, {}))
        self.assertIsNone(source_view.gate({"source": "gsa,facebook"}, {}))
        self.assertIsNotNone(source_view.gate({"source": "unknown-provider"}, {}))


if __name__ == "__main__":
    unittest.main()
