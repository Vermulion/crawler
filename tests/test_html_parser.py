"""Offline tests for HTMLParser and AsyncCrawler.fetch_and_parse."""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from crawler import AsyncCrawler, HTMLParser

SAMPLE_HTML = """
<!doctype html>
<html>
  <head>
    <title>  Sample Page </title>
    <meta name="description" content="A demo page">
    <meta name="keywords" content="demo, parser">
  </head>
  <body>
    <h1>Hello</h1>
    <h2>World</h2>
    <h3>Details</h3>
    <p>Visible text.</p>
    <script>var x = 1;</script>
    <style>.x { color: red; }</style>
    <article id="main">Only article.</article>
    <a href="/about">about</a>
    <a href="../up">up</a>
    <a href="https://example.com/contact">contact</a>
    <a href="https://example.org/abs">outer</a>
    <a href="https://example.com/about#frag">dup about</a>
    <a href="#top">fragment</a>
    <a href="javascript:void(0)">js</a>
    <a href="mailto:a@b.c">mail</a>
    <a href="http://">broken</a>
    <img src="/logo.png" alt="Logo">
    <img src="https://cdn.example.net/x.png" alt="CDN">
    <img alt="missing src">
    <table>
      <tr><th>Name</th><th>Qty</th></tr>
      <tr><td>Apples</td><td>3</td></tr>
      <tr><td>Pears</td><td>2</td></tr>
    </table>
    <ul>
      <li>One</li>
      <li>Two
        <ul><li>Nested</li></ul>
      </li>
    </ul>
    <ol>
      <li>First</li>
      <li>Second</li>
    </ol>
  </body>
</html>
"""

BASE_URL = "https://example.com/home"


@pytest.fixture
def parser() -> HTMLParser:
    return HTMLParser()


@pytest.fixture
def soup(parser: HTMLParser) -> BeautifulSoup:
    return parser._soup(SAMPLE_HTML)


@pytest.mark.asyncio
async def test_parse_html_returns_page_dict(parser: HTMLParser) -> None:
    page = await parser.parse_html(SAMPLE_HTML, BASE_URL)
    assert page["url"] == BASE_URL
    assert page["title"] == "Sample Page"
    assert "Hello" in page["text"]
    assert "Visible text." in page["text"]
    assert "var x" not in page["text"]
    assert page["links"] == [
        "https://example.com/about",
        "https://example.com/up",
        "https://example.com/contact",
    ]
    assert "https://example.org/abs" not in page["links"]
    assert page["metadata"] == {
        "title": "Sample Page",
        "description": "A demo page",
        "keywords": "demo, parser",
    }
    assert page["images"] == [
        {"src": "https://example.com/logo.png", "alt": "Logo"},
        {"src": "https://cdn.example.net/x.png", "alt": "CDN"},
    ]
    assert page["headings"] == [
        {"level": "h1", "text": "Hello"},
        {"level": "h2", "text": "World"},
        {"level": "h3", "text": "Details"},
    ]
    assert page["tables"] == [
        {"headers": ["Name", "Qty"], "rows": [["Apples", "3"], ["Pears", "2"]]}
    ]
    assert page["lists"] == [
        {"type": "ul", "items": ["One", "Two"]},
        {"type": "ol", "items": ["First", "Second"]},
    ]
    assert any(
        item["href"] == "/about" and item["absolute"] == "https://example.com/about"
        for item in page["link_details"]
    )


def test_extract_links_converts_relative_and_filters_outer(parser: HTMLParser, soup: BeautifulSoup) -> None:
    links = parser.extract_links(soup, BASE_URL)
    assert "https://example.com/about" in links
    assert "https://example.com/up" in links
    assert "https://example.org/abs" not in links
    assert all(link.startswith("https://example.com/") for link in links)


def test_extract_links_skips_non_http(parser: HTMLParser, soup: BeautifulSoup) -> None:
    links = parser.extract_links(soup, BASE_URL)
    assert "javascript:void(0)" not in links
    assert all(parser.is_valid_url(link) for link in links)


def test_to_absolute_url_and_validation(parser: HTMLParser) -> None:
    assert parser.to_absolute_url("/a", BASE_URL) == "https://example.com/a"
    assert parser.to_absolute_url("javascript:void(0)", BASE_URL) is None
    assert parser.to_absolute_url("http://", BASE_URL) is None
    assert parser.is_valid_url("https://example.com/x") is True
    assert parser.is_valid_url("ftp://example.com/x") is False
    assert parser.is_valid_url("not a url") is False


def test_www_and_bare_host_are_same_site(parser: HTMLParser) -> None:
    html = """
    <a href="https://www.example.com/a">www</a>
    <a href="https://example.com/b">bare</a>
    <a href="https://other.com/c">outer</a>
    """
    soup = parser._soup(html)
    links = parser.extract_links(soup, "https://www.example.com/")
    assert "https://www.example.com/a" in links
    assert "https://example.com/b" in links
    assert "https://other.com/c" not in links


def test_extract_link_details_marks_relative_and_outer(parser: HTMLParser, soup: BeautifulSoup) -> None:
    details = parser.extract_link_details(soup, BASE_URL)
    by_href = {item["href"]: item for item in details}
    assert by_href["/about"]["absolute"] == "https://example.com/about"
    assert by_href["/about"]["kept"] is True
    assert by_href["https://example.org/abs"]["kept"] is False
    assert by_href["https://example.org/abs"]["reason"] == "outer"
    assert by_href["javascript:void(0)"]["kept"] is False


def test_extract_text_with_selector(parser: HTMLParser, soup: BeautifulSoup) -> None:
    assert parser.extract_text(soup, selector="#main") == "Only article."
    assert parser.extract_text(soup, selector="#missing") == ""


def test_extract_metadata_falls_back_to_og() -> None:
    html = """
    <html><head>
      <meta property="og:title" content="OG Title">
      <meta property="og:description" content="OG Desc">
    </head></html>
    """
    parser = HTMLParser()
    meta = parser.extract_metadata(parser._soup(html))
    assert meta["title"] == "OG Title"
    assert meta["description"] == "OG Desc"
    assert meta["keywords"] == ""


def test_extract_images_headings_tables_lists(parser: HTMLParser, soup: BeautifulSoup) -> None:
    images = parser.extract_images(soup, BASE_URL)
    assert {"src": "https://example.com/logo.png", "alt": "Logo"} in images
    headings = parser.extract_headings(soup)
    assert headings[0] == {"level": "h1", "text": "Hello"}
    tables = parser.extract_tables(soup)
    assert tables[0]["headers"] == ["Name", "Qty"]
    lists = parser.extract_lists(soup)
    assert lists[0]["type"] == "ul"
    assert "Nested" not in lists[0]["items"]


@pytest.mark.asyncio
async def test_parse_html_handles_incorrect_html(parser: HTMLParser) -> None:
    page = await parser.parse_html("<div><p>broken", BASE_URL)
    assert page["url"] == BASE_URL
    assert "broken" in page["text"]
    assert page["links"] == []
    assert page["images"] == []


@pytest.mark.asyncio
async def test_parse_html_returns_partial_on_extractor_error(
    parser: HTMLParser, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(parser, "extract_links", boom)
    with caplog.at_level("WARNING", logger="crawler.html_parser"):
        page = await parser.parse_html(SAMPLE_HTML, BASE_URL)
    assert page["url"] == BASE_URL
    assert page["title"] == "Sample Page"
    assert page["links"] == []
    assert page["images"]
    assert any("Failed to extract links" in rec.getMessage() for rec in caplog.records)
    assert any("[RuntimeError]" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_parse_html_logs_invalid_links(parser: HTMLParser, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="crawler.html_parser"):
        await parser.parse_html(SAMPLE_HTML, BASE_URL)
    messages = [rec.getMessage() for rec in caplog.records]
    assert any("Skipping invalid link" in msg for msg in messages)
    assert any("Skipping image without src" in msg for msg in messages)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self._text = text
        self.status = 200

    async def text(self) -> str:
        return self._text

    def raise_for_status(self) -> None:
        return None


class _FakeCM:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeSession:
    closed = False

    def __init__(self, html: str) -> None:
        self.html = html

    def get(self, url: str) -> _FakeCM:
        return _FakeCM(_FakeResponse(self.html))

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_fetch_and_parse_uses_parser() -> None:
    crawler = AsyncCrawler()
    crawler._session = _FakeSession(SAMPLE_HTML)  # type: ignore[assignment]
    page = await crawler.fetch_and_parse(BASE_URL)
    assert page["url"] == BASE_URL
    assert page["title"] == "Sample Page"
    assert "https://example.com/about" in page["links"]
    assert page["images"]
    await crawler.close()
