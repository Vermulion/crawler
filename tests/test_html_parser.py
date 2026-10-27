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
    <p>Visible text.</p>
    <script>var x = 1;</script>
    <style>.x { color: red; }</style>
    <article id="main">Only article.</article>
    <a href="/about">about</a>
    <a href="https://example.org/abs">abs</a>
    <a href="https://example.com/about#frag">dup about</a>
    <a href="#top">fragment</a>
    <a href="javascript:void(0)">js</a>
    <a href="mailto:a@b.c">mail</a>
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
        "https://example.org/abs",
    ]
    assert page["metadata"] == {
        "title": "Sample Page",
        "description": "A demo page",
        "keywords": "demo, parser",
    }


def test_extract_links_skips_non_http(parser: HTMLParser, soup: BeautifulSoup) -> None:
    links = parser.extract_links(soup, BASE_URL)
    assert "javascript:void(0)" not in links
    assert all(link.startswith("http") for link in links)


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
    await crawler.close()
