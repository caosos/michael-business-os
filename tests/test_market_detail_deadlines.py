"""GSA pay-by / remove-by come from the published instruction text, exactly as written; nothing is computed or guessed."""
import pytest

from operator_ui.market_detail import deadline


@pytest.mark.parametrize("text,pay,remove", [
    ("SALE DATES: OCT 07 – OCT 14, PAY BY: OCT 16 REMOVE BY: OCT 28", "OCT 16 (as published)", "OCT 28 (as published)"),
    ("Payment is due by 10/20/26 and the property must be removed by 10/30/26.", "10/20/26 (as published)", "10/30/26 (as published)"),
    ("PAYMENT DUE BY 10-16-26 & REMOVAL BY 10-28-26", "10-16-26 (as published)", "10-28-26 (as published)"),
    ("Pay by: 10/16/26 Remove by:10/28/26", "10/16/26 (as published)", "10/28/26 (as published)"),
    ("Property must be removed within 10 business days from the time of award.", None, "within 10 business days of the sale (as published)"),
    ("REMOVAL BY APPOINTMENT ONLY", None, None),
    ("", None, None),
])
def test_deadline_as_published(text, pay, remove):
    assert deadline(text, "pay") == pay and deadline(text, "remove") == remove
