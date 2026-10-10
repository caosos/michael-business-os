# Receipt: GSA Auctions API smoke (read-only, DEMO_KEY), 2026-10-09 ~19:15 CDT

- **Request:** 1 GET `https://api.gsa.gov/assets/gsaauctions/v2/auctions?api_key=DEMO_KEY&format=JSON` (+1 follow of its HTTP 303 to the signed S3 file `active-auctions.json`). Rate limit header: 10 per window, 8 remaining after. No account, no key request, no paid service, no bid, no contact.
- **Result:** HTTP 200, 1179 active lots, 3.6 MB, 2.7 s. Fields: agency, lotNo, saleNo, itemName, aucStartDt/aucEndDt, highBidAmount, biddersCount, reserve, locationCity/ST, itemDescURL, imageURL, lotInfo. **No buyer premium, no sold comps in the data (never invent them).**
- **Arkansas lots now:** 19 (provenance: GSA API as of this fetch; re-fetch before any decision).

| Sale-Lot | Item | City | High bid | Bidders | Ends | Original lot URL |
|---|---|---|---|---|---|---|
| 3-1-QSC-I-27-006-005 | Trailer, Utility | Marianna | 25.0 | 1 | 2026-10-12 | https://www.gsaauctions.gov/auctions/preview/378501 |
| 3-1-QSC-I-27-017-016 | iPad Mini Lot | FAYETTEVILLE | 25.0 | 1 | 2026-10-14 | https://www.gsaauctions.gov/auctions/preview/379279 |
| 3-1-QSC-I-27-017-017 | Traulsen Double Refrigerator | FAYETTEVILLE | 45.0 | 2 | 2026-10-14 | https://www.gsaauctions.gov/auctions/preview/379280 |
| 3-1-QSC-I-27-017-037 | Metal Mop Cart Lot | FAYETTEVILLE | 10.0 | 1 | 2026-10-14 | https://www.gsaauctions.gov/auctions/preview/379292 |
| 3-1-QSC-I-27-017-038 | Workbench with Pegboard Backing | FAYETTEVILLE | 10.0 | 1 | 2026-10-14 | https://www.gsaauctions.gov/auctions/preview/379293 |
| 3-1-QSC-I-27-017-039 | Whirlpool Washing Machine | FAYETTEVILLE | None | None | 2026-10-14 | https://www.gsaauctions.gov/auctions/preview/379294 |
| 3-1-QSC-I-27-017-040 | Wheelchair Lot | FAYETTEVILLE | None | None | 2026-10-14 | https://www.gsaauctions.gov/auctions/preview/379295 |
| 3-1-QSC-I-27-017-054 | Rolling Stainless-Steel Storage Cart Lot | FAYETTEVILLE | None | None | 2026-10-14 | https://www.gsaauctions.gov/auctions/preview/379374 |
| 3-1-QSC-I-27-017-028 | Beretta Leather RH Holster Lot | NORTH LITTLE ROCK | None | None | 2026-10-14 | https://www.gsaauctions.gov/auctions/preview/379425 |
| 3-1-QSC-I-27-019-001 | 1985 Chevrolet CD30903 pickup 2 door Truck | GREENBRIER | None | None | 2026-10-23 | https://www.gsaauctions.gov/auctions/preview/379664 |
| 3-1-QSC-I-27-019-002 | 1984 International 1654 Crew Cab  Truck | GREENBRIER | None | None | 2026-10-23 | https://www.gsaauctions.gov/auctions/preview/379665 |
| 3-1-QSC-I-27-019-003 | 1983 International F1954 2.5 ton 6x4 Truck | GREENBRIER | None | None | 2026-10-23 | https://www.gsaauctions.gov/auctions/preview/379666 |
| 3-1-QSC-I-27-019-004 | 1978 Seagrave MB23098 Fire Truck | GREENBRIER | None | None | 2026-10-23 | https://www.gsaauctions.gov/auctions/preview/379667 |
| 3-1-QSC-I-27-019-005 | 1968 Kaiser M51A2 5 ton 6x6 Truck | GREENBRIER | None | None | 2026-10-23 | https://www.gsaauctions.gov/auctions/preview/379668 |
| 3-1-QSC-I-27-019-006 | 1984 Chevrolet CD30903 Pickup 2 Door Truck | GREENBRIER | None | None | 2026-10-23 | https://www.gsaauctions.gov/auctions/preview/379669 |
| 3-1-QSC-I-27-019-007 | 1977 Dodge W20 Pickup 2 door Truck | GREENBRIER | None | None | 2026-10-23 | https://www.gsaauctions.gov/auctions/preview/379670 |
| 3-1-QSC-I-27-019-009 | 1987 Chevrolet CD30903 Pickup 2 door Truck | GREENBRIER | None | None | 2026-10-23 | https://www.gsaauctions.gov/auctions/preview/379671 |
| 3-1-QSC-I-27-019-010 | 1967 Striker M5000 Tank Trailer | GREENBRIER | None | None | 2026-10-23 | https://www.gsaauctions.gov/auctions/preview/379672 |
| 3-1-QSC-I-27-019-011 | 1981 Monark 16' Boat w/ Trailer and 2005 Mercury Outboa | GREENBRIER | None | None | 2026-10-23 | https://www.gsaauctions.gov/auctions/preview/379673 |

Photo URL pattern: `imageURL` field per lot (ppms.gov). Distance to Conway not computed (needs geodata); no claim of profit.
Next: B-25 (lane 02) adapter, F-46 (lane 06) live/demo separation. Both wait for the quota guard.
