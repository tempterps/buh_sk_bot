from buh_news.discovery import parse_date, canonical
def test_social_insurance_date_is_local_midnight():
    date=parse_date('27.11.2026')
    assert date.isoformat()=='2026-11-27T00:00:00+01:00'
def test_url_normalization():
    assert canonical('HTTP://Example.SK/a/')=='http://example.sk/a'

