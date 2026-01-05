from datetime import date

from lumibot.tools.thetadata_helper import _thetadata_option_query_expiration


def test_thetadata_monthly_expiration_maps_to_occ_saturday() -> None:
    """ThetaData represents standard monthlies using the OCC Saturday expiry date.

    LumiBot strategies typically use the last tradable Friday as the "expiration" date. Without
    mapping, ThetaData history endpoints can return placeholder-only responses (472/empty) even
    when the contract exists.
    """

    # Third Friday of Aug 2013 -> OCC Saturday
    assert _thetadata_option_query_expiration(date(2013, 8, 16)) == date(2013, 8, 17)

    # Third Friday of Feb 2014 -> OCC Saturday
    assert _thetadata_option_query_expiration(date(2014, 2, 21)) == date(2014, 2, 22)


def test_thetadata_weekly_expiration_kept_on_friday() -> None:
    # Weekly expiration (not the 3rd Friday) should stay on Friday.
    assert _thetadata_option_query_expiration(date(2013, 8, 9)) == date(2013, 8, 9)


def test_thetadata_holiday_thursday_expiration_kept() -> None:
    # Some expirations are represented as Thursday due to market holidays (e.g., Good Friday).
    assert _thetadata_option_query_expiration(date(2015, 4, 2)) == date(2015, 4, 2)

