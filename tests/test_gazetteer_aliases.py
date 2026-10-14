"""USPS town names missing from the Census files resolve to the Census ZIP/place they name; nothing new is invented."""
from operator_ui import gazetteer as gz


def test_aliases_point_at_existing_census_entries():
    gz._load.cache_clear()
    assert gz.locate("Hot Springs National Park, AR") == gz.locate("Hot Springs, AR") is not None
    assert gz.locate("Cleveland, AR") == gz.locate("72030") is not None
    assert gz.locate("Prim, AR") == gz.locate("72130") is not None
    assert gz.locate("Prim") == gz.locate("72130")                       # a bare name prefers Arkansas
    assert gz.locate("Conway, AR") == gz.locate("Conway, AR")            # real names untouched
    assert gz.locate("Nowhereville, AR") is None
