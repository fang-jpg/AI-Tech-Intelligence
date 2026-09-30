from ai_tech_intelligence.utils import canonicalize_url, domain_matches, parse_date


def test_canonicalize_url_removes_tracking_and_fragment() -> None:
    value = canonicalize_url("https://OpenAI.com/index/test/?utm_source=x&b=2&a=1#part")
    assert value == "https://openai.com/index/test?a=1&b=2"


def test_domain_matching_uses_domain_boundary() -> None:
    assert domain_matches("https://news.openai.com/x", ["openai.com"])
    assert not domain_matches("https://openai.com.bad.example/x", ["openai.com"])


def test_parse_date_returns_iso_date() -> None:
    assert parse_date("September 18, 2026") == "2026-09-18"

