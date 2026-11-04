"""Offline robots.txt parsing via RobotsParser.store (no network)."""

from __future__ import annotations

from crawler.robots_parser import RobotsParser

RULES = """
User-agent: BadBot
Disallow: /private
Crawl-delay: 2

User-agent: *
Disallow:
"""


def _loaded() -> RobotsParser:
    parser = RobotsParser()
    parser.store("https://a.test/page", 200, RULES)
    return parser


def test_disallow_depends_on_user_agent() -> None:
    parser = _loaded()
    assert parser.can_fetch("https://a.test/private", "BadBot") is False
    assert parser.can_fetch("https://a.test/ok", "BadBot") is True
    assert parser.can_fetch("https://a.test/private", "GoodBot") is True


def test_crawl_delay_is_read_for_matching_agent() -> None:
    parser = _loaded()
    assert parser.get_crawl_delay("https://a.test/", "BadBot") == 2.0
    assert parser.get_crawl_delay("https://a.test/", "GoodBot") == 0.0


def test_unknown_origin_is_not_allowed_yet() -> None:
    parser = _loaded()
    assert parser.can_fetch("https://other.test/") is False
    assert parser.get_crawl_delay("https://other.test/") == 0.0


def test_missing_file_allows_all() -> None:
    parser = RobotsParser()
    summary = parser.store("https://a.test/", 404, "")
    assert summary["cached"] is True
    assert parser.can_fetch("https://a.test/any") is True


def test_forbidden_robots_file_disallows_all() -> None:
    parser = RobotsParser()
    parser.store("https://a.test/", 403, "")
    assert parser.can_fetch("https://a.test/") is False


def test_second_store_replaces_cache_for_same_origin() -> None:
    parser = RobotsParser()
    parser.store("https://a.test/", 200, "User-agent: *\nDisallow: /\n")
    assert parser.can_fetch("https://a.test/x") is False
    parser.store("https://a.test/", 200, "User-agent: *\nDisallow:\n")
    assert parser.can_fetch("https://a.test/x") is True


def test_origin_is_scheme_plus_host() -> None:
    parser = RobotsParser()
    assert parser._origin("https://A.TEST/path?q=1") == "https://a.test"
