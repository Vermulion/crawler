"""Offline tests for URLFilter (same-domain, whitelist, blacklist)."""

from __future__ import annotations

from crawler.url_filter import URLFilter


def test_same_domain_only_keeps_seed_host() -> None:
    filt = URLFilter(
        same_domain_only=True,
        allowed_hosts=["https://example.com/home"],
    )
    assert filt.allow("https://example.com/blog") is True
    assert filt.allow("https://www.example.com/blog") is True
    assert filt.allow("https://other.org/blog") is False


def test_same_domain_only_false_allows_other_hosts() -> None:
    filt = URLFilter(
        same_domain_only=False,
        allowed_hosts=["https://example.com"],
    )
    assert filt.allow("https://other.org/x") is True


def test_whitelist_include_patterns() -> None:
    filt = URLFilter(
        same_domain_only=True,
        allowed_hosts=["https://example.com"],
        include_patterns=[r"/blog"],
    )
    assert filt.allow("https://example.com/blog/post") is True
    assert filt.allow("https://example.com/about") is False


def test_blacklist_exclude_patterns() -> None:
    filt = URLFilter(
        same_domain_only=True,
        allowed_hosts=["https://example.com"],
        exclude_patterns=[r"\.pdf$", r"/draft"],
    )
    assert filt.allow("https://example.com/page") is True
    assert filt.allow("https://example.com/a.pdf") is False
    assert filt.allow("https://example.com/draft") is False


def test_whitelist_then_blacklist() -> None:
    filt = URLFilter(
        same_domain_only=True,
        allowed_hosts=["https://example.com"],
        include_patterns=[r"/blog"],
        exclude_patterns=[r"\.pdf$"],
    )
    assert filt.allow("https://example.com/blog/post") is True
    assert filt.allow("https://example.com/about") is False
    assert filt.allow("https://example.com/blog/a.pdf") is False
    assert filt.allow("https://other.org/blog/post") is False
