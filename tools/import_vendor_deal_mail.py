#!/usr/bin/env python3
"""Read DealSniffer's vendor inbox and create review-pending offers.

No message is sent, deleted, moved, copied, or marked read.  ``--live`` is
required before the existing IMAP reader will connect.  Sender/customer
onboarding is a separate verified-registry operation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from mbos_discovery.adapters.email_alerts import ImapReader
from operator_ui import vendor_deals
from operator_ui.vendor_mail import (QuarantineStore, VendorMailPipeline,
                                     VendorRegistry, dkim_authenticated_sender)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="open the mailbox read-only")
    parser.add_argument("--days", type=int, default=2, help="lookback window (1..14 days)")
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 14:
        parser.error("--days must be between 1 and 14")
    host = os.environ.get("MBOS_VENDOR_IMAP_HOST")
    user = os.environ.get("MBOS_VENDOR_IMAP_USER")
    password_env = os.environ.get("MBOS_VENDOR_IMAP_PASSWORD_ENV")
    folder = os.environ.get("MBOS_VENDOR_IMAP_FOLDER", "DealSniffer/Vendors")
    if not (host and user and password_env and os.environ.get(password_env)):
        print(json.dumps({"result": "not_configured", "created": 0,
                          "why": "vendor mailbox credentials are not configured; no mailbox was read"}))
        return 0
    if not args.live:
        print(json.dumps({"result": "dry_run", "created": 0,
                          "why": "pass --live to read the mailbox"}))
        return 0
    now = datetime.now(timezone.utc)
    pipeline = VendorMailPipeline(VendorRegistry(), vendor_deals.Store(), QuarantineStore())
    reader = ImapReader(host, user, password_env, folder, live=True)
    results = pipeline.import_reader(reader, now - timedelta(days=args.days), provider="imap",
                                     authentication=dkim_authenticated_sender, clock=lambda: now)
    counts = {state: sum(result.state == state for result in results)
              for state in ("REVIEW_PENDING", "DUPLICATE", "QUARANTINED")}
    print(json.dumps({"result": "read", "messages": len(results), "created": counts["REVIEW_PENDING"],
                      "duplicates": counts["DUPLICATE"], "quarantined": counts["QUARANTINED"],
                      "as_of": now.isoformat()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
