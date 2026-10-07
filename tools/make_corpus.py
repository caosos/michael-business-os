"""Generate the deterministic 7-day discovery corpus used by the F1–F4 harness (READY_QUEUE B-10).

    python -I tools/make_corpus.py tests/fixtures/corpus7d

Writes day0..day6/{ebay,gsa,email,intake/...}/ shaped like each adapter's real input, plus `labels.json`. That file
maps every sighting `source|listing_id` to the PHYSICAL object it describes. Labels are ground truth for scoring F2
only; the pipeline never reads them. Seeded, stdlib-only, byte-stable output.

Scenarios (all ILLUSTRATIVE, hand-designed to stress dedup):
* persistence: most listings re-appear daily (identity), several with price drops (update, not new item)
* overlap: some eBay listings match both search queries the same day (identity)
* relist: an eBay listing ends, and the same seller re-posts the same unit under a NEW itemId days later
  (same physical object → should be ONE Item)
* twins: a dealer lists two identical units at once (two physical objects → must stay TWO Items)
* GSA lots re-polled daily with rising bids; GovDeals alert e-mails repeat lots across days
* service: a customer uses both the web form and a referral; another submits the form twice
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
CATS = [("trailer", "{w}x{l} enclosed trailer", (900, 3500)), ("trailer", "{w}x{l} utility trailer", (400, 1500)),
        ("mower", "{brand} zero turn mower {n}in", (800, 3000)), ("generator", "{brand} {n}W portable generator", (200, 900)),
        ("welder", "{brand} {n} MIG welder", (250, 900)), ("compressor", "{brand} {n} gallon air compressor", (150, 600))]
BRANDS = ["Lincoln", "Miller", "Honda", "Generac", "Kubota", "Craftsman", "Husqvarna", "Campbell", "Champion", "Hobart"]
CITIES = [("Conway", "AR", "720"), ("Little Rock", "AR", "722"), ("Searcy", "AR", "721"), ("Benton", "AR", "720"),
          ("Russellville", "AR", "728"), ("Hot Springs", "AR", "719")]


def ebay_summary(lst: dict, price: float) -> dict:
    city, st, z = lst["city"]
    return {"itemId": lst["id"], "title": lst["title"], "price": {"value": f"{price:.2f}", "currency": "USD"},
            "buyingOptions": ["FIXED_PRICE"], "condition": "Used", "conditionId": "3000",
            "itemWebUrl": f"https://www.ebay.com/itm/{lst['id'].split('|')[1]}",
            "itemLocation": {"city": city, "stateOrProvince": st, "postalCode": f"{z}**", "country": "US"},
            "distanceFromPickupLocation": {"value": str(lst["miles"]), "unitOfMeasure": "MILE"},
            "seller": {"username": lst["seller"], "sellerAccountType": "BUSINESS" if lst.get("dealer") else "INDIVIDUAL"},
            "categories": [{"categoryName": lst["cat"].title()}]}


def main(out: Path) -> None:
    rnd = random.Random(20261001)
    labels: dict[str, str] = {}
    out.mkdir(parents=True, exist_ok=True)

    # ---- eBay listings ------------------------------------------------------------------------
    ebay: list[dict] = []
    for i in range(20):
        cat, pat, (lo, hi) = CATS[i % len(CATS)]
        title = pat.format(w=rnd.choice([5, 6, 7]), l=rnd.choice([8, 10, 12, 14]), brand=rnd.choice(BRANDS),
                           n=rnd.choice([48, 52, 60, 3500, 5500, 7500, 140, 180, 211, 20, 30, 60]))
        ebay.append({"obj": f"obj-ebay-{i:02d}", "id": f"v1|5000000{i:05d}|0", "title": title, "cat": cat,
                     "seller": f"seller_{i:02d}", "city": rnd.choice(CITIES), "miles": rnd.randint(3, 95),
                     "price": float(rnd.randint(lo, hi)), "days": list(range(rnd.randint(0, 2), 7)),
                     "query": "trailer" if cat == "trailer" else "equipment"})
    for lst in ebay[:5]:                                          # price drop on day 4
        lst["drop_day"] = 4
    for k, lst in enumerate(ebay[5:8]):                           # relists: end, then same unit, new itemId
        lst["days"] = [0, 1, 2]
        ebay.append({**lst, "id": f"v1|5100000{k:05d}|0", "days": list(range(3 + k % 2, 7)),
                     "price": round(lst["price"] * 0.92), "relist_of": lst["id"]})
    twin = ebay[8]                                                # dealer twins: two units, both active
    twin.update(dealer=True, title=f"{twin['title']} - NEW STOCK", seller="dealer_outdoor_power", days=list(range(7)))
    ebay.append({**twin, "obj": "obj-ebay-twin-b", "id": "v1|52000000001|0"})
    for lst in ebay[9:11]:                                        # appears in both queries
        lst["both_queries"] = True

    for d in range(7):
        day = out / f"day{d}"
        pages: dict[str, list] = {"trailer": [], "equipment": []}
        for lst in ebay:
            if d not in lst["days"]:
                continue
            price = lst["price"] * (0.85 if lst.get("drop_day") is not None and d >= lst["drop_day"] else 1)
            s = ebay_summary(lst, price)
            pages[lst["query"]].append(s)
            if lst.get("both_queries"):
                pages["equipment" if lst["query"] == "trailer" else "trailer"].append(s)
            labels[f"ebay|{lst['id']}"] = lst["obj"]
        (day / "ebay").mkdir(parents=True, exist_ok=True)
        (day / "ebay" / "token.json").write_text('{"access_token": "corpus", "expires_in": 7200}\n')
        for q, items in pages.items():
            (day / "ebay" / f"search-{q}.json").write_text(json.dumps({"total": len(items), "itemSummaries": items},
                                                                       indent=1, sort_keys=True) + "\n")

    # ---- GSA lots (re-polled daily, bids rising) ---------------------------------------------------
    gsa = [{"obj": f"obj-gsa-{i}", "SaleNo": f"71QSCI2610{i}", "LotNo": i + 1,
            "ItemName": ["UTILITY TRAILER 6X10", "GENERATOR 5500W", "AIR COMPRESSOR 60 GAL", "WELDER, MIG 180",
                         "MOWER, ZERO TURN 60IN", "FORKLIFT 5000LB"][i],
            "PropertyCity": CITIES[i][0].upper(), "PropertyState": "AR", "PropertyZip": f"{CITIES[i][2]}01",
            "start": i % 3, "end": 6 if i < 4 else 4} for i in range(6)]
    for d in range(7):
        res = []
        for g in gsa:
            if g["start"] <= d <= g["end"]:
                bidders = max(0, d - g["start"])
                res.append({"SaleNo": g["SaleNo"], "LotNo": g["LotNo"], "ItemName": g["ItemName"],
                            "AucEndDt": (T0 + timedelta(days=g["end"] + 1)).date().isoformat(), "AuctionStatus": "A",
                            "PropertyCity": g["PropertyCity"], "PropertyState": "AR", "PropertyZip": g["PropertyZip"],
                            "BiddersCount": bidders, "HighBidAmount": 100.0 * bidders,
                            "AgencyName": "GENERAL SERVICES ADMINISTRATION",
                            "ItemDescURL": f"https://www.gsaauctions.gov/corpus/{g['SaleNo']}/{g['LotNo']}"})
                labels[f"gsa_auctions|{g['SaleNo']}-{g['LotNo']}"] = g["obj"]
        (out / f"day{d}" / "gsa").mkdir(parents=True, exist_ok=True)
        (out / f"day{d}" / "gsa" / "auctions.json").write_text(json.dumps({"results": res}, indent=1, sort_keys=True) + "\n")

    # ---- GovDeals alert e-mails (lots repeat across days) ------------------------------------------
    lots = [("4101/9001", "Snapper riding mower 42in", "Conway, AR 72032", 150), ("4102/9001", "Utility trailer 5x8", "Searcy, AR", 300),
            ("4103/9002", "Pressure washer 3000 PSI", "Benton, AR", 75), ("4104/9002", "Shop air compressor 80 gal", "Little Rock, AR 72201", 220)]
    for d in range(7):
        todays = [l for k, l in enumerate(lots) if k <= d < k + 4]
        (out / f"day{d}" / "email").mkdir(parents=True, exist_ok=True)
        if not todays:
            continue
        rows = "".join(f'<tr><td><a href="https://www.govdeals.com/asset/{lid}">{t}</a></td>'
                       f"<td>Current Bid: ${p + 25 * d}.00 Closes: {(T0 + timedelta(days=9)).date()} {place}</td></tr>"
                       for lid, t, place, p in todays)
        sent = (T0 + timedelta(days=d, hours=-6)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        msg = ("From: GovDeals Alerts <alerts@govdeals.com>\nTo: michael@example.invalid\n"
               f"Subject: Saved search results day {d}\nDate: {sent}\nMessage-ID: <corpus-{d}@govdeals.com>\n"
               "Authentication-Results: mx.example.invalid; dkim=pass header.d=govdeals.com\n"
               "MIME-Version: 1.0\nContent-Type: text/html; charset=utf-8\n\n"
               f"<html><body><table>{rows}</table></body></html>\n")
        (out / f"day{d}" / "email" / f"alert-{d}.eml").write_text(msg)
        for lid, *_ in todays:
            labels[f"govdeals_email|{lid}"] = f"obj-gd-{lid}"

    # ---- service leads (inbox accumulates) --------------------------------------------------------
    leads = [  # (day, channel, id, customer, request)
        (0, "website_form", "w-001", "ana@example.invalid", "Drywall patch in hallway"),
        (1, "referral", "r-001", "ana@example.invalid", "Drywall repair hallway (referred)"),
        (1, "website_form", "w-002", "bo@example.invalid", "Assemble IKEA bed frame"),
        (2, "website_form", "w-003", "cy@example.invalid", "Mower won't start, needs repair"),
        (3, "website_form", "w-004", "cy@example.invalid", "Mower won't start - following up"),
        (4, "website_form", "w-005", "di@example.invalid", "Install smart thermostat"),
        (5, "referral", "r-002", "ed@example.invalid", "Mount TV on wall"),
    ]
    objs = {"ana@example.invalid": "obj-svc-ana", "bo@example.invalid": "obj-svc-bo", "cy@example.invalid": "obj-svc-cy",
            "di@example.invalid": "obj-svc-di", "ed@example.invalid": "obj-svc-ed"}
    for d in range(7):
        for ch in ("website_form", "referral"):
            (out / f"day{d}" / "intake" / ch).mkdir(parents=True, exist_ok=True)
        for day, ch, sid, who, req in leads:
            if day <= d:
                sub = {"submission_id": sid, "received_at": (T0 + timedelta(days=day, hours=-2)).isoformat(),
                       "service_requested": req, "description": req, "email": who, "city": "Conway", "state": "AR",
                       "zip": "72034"}
                (out / f"day{d}" / "intake" / ch / f"{sid}.json").write_text(json.dumps(sub, sort_keys=True) + "\n")
                labels[f"{'website_lead' if ch == 'website_form' else 'referral'}|{sid}"] = objs[who]

    (out / "labels.json").write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
    (out / "README.md").write_text(__doc__.split("\n\n", 1)[1])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
