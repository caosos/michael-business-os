from mbos_discovery import location as loc
from mbos_discovery.location import User, OWNER, sources_for, zip_centroid

REG = loc.load_registry()
CL = {s["source_id"] for s in REG if s["source_id"].startswith("craigslist_")}
NATIONAL = {s["source_id"] for s in REG if s["coverage"]["scope"] == "national"}


def active(u):
    return {c.source_id for c in sources_for(u) if c.active}


def test_zip_table_size_and_known_points():
    lat, lng = zip_centroid("72032")
    assert abs(lat - 35.0656) < 0.01 and abs(lng + 92.3628) < 0.01
    assert zip_centroid("72032-1234") == zip_centroid("72032")
    assert zip_centroid("00000") is None and zip_centroid("") is None and zip_centroid("abcde") is None
    assert len(loc._zcta()) > 33000


AR_HOUSES = {"wooley_auctioneers", "wilson_auctioneers", "blackmon_auctions", "ar_state_surplus"}  # D-38 registry


def test_owner_output_is_arkansas_everything():
    got = sources_for(OWNER)
    ids = {c.source_id for c in got if c.active}
    assert ids == {s["source_id"] for s in REG}  # all national + AR craigslist + AR states
    assert all(c.radius_mi == 150.0 for c in got)


def test_ohio_user_sees_no_arkansas():
    ohio = User(home_zip="43215", home_state="OH", default_radius_mi=50)
    ids = active(ohio)
    assert not (ids & CL) and not (ids & AR_HOUSES)
    assert NATIONAL <= ids
    assert {c.source_id for c in sources_for(ohio) if not c.active} == CL | AR_HOUSES


def test_distance_match_without_state():
    fs = User(home_zip="72901")  # Fort Smith, no state given
    ids = active(fs)
    assert "craigslist_fortsmith" in ids and "craigslist_fayar" in ids
    assert not (ids & AR_HOUSES)  # states-scope needs a state


def test_border_user_in_missouri_reaches_nw_arkansas_only():
    joplin = User(home_zip="64801", home_state="MO", default_radius_mi=30)
    ids = active(joplin)
    assert "craigslist_fayar" in ids and "craigslist_littlerock" not in ids


def test_unknown_location_gets_national_only_and_blocked_status_is_reported():
    ids = active(User())
    assert ids == NATIONAL
    by = {c.source_id: c for c in sources_for(User())}
    assert by["fb_marketplace"].status == "blocked" and by["fb_marketplace"].active


def test_default_radius():
    metro = next(s for s in REG if s["source_id"] == "craigslist_fayar")
    assert loc.default_radius(User(), metro) == 100.0
    assert loc.default_radius(User(default_radius_mi=40), metro) == 40.0


def test_active_sorted_first_and_no_network():
    got = sources_for(User(home_zip="43215", home_state="OH"))
    flags = [c.active for c in got]
    assert flags == sorted(flags, reverse=True)
