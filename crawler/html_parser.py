"""HTML parsing helpers built on BeautifulSoup."""

from __future__ import annotations

from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

_SKIP_SCHEMES = {"javascript", "mailto", "tel", "data"}
_HTTP_SCHEMES = {"http", "https"}


class HTMLParser:
    """Parse HTML into title, visible text, absolute links, and metadata."""

    def __init__(self, features: str = "html.parser") -> None:
        self.features = features

    def _soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, self.features)

    async def parse_html(self, html: str, url: str) -> dict:
        """Parse HTML and return a page dict.

        Keys: ``url``, ``title``, ``text``, ``links`` (absolute http(s)),
        ``metadata`` (title, description, keywords).
        """
        soup = self._soup(html)
        metadata = self.extract_metadata(soup)
        return {
            "url": url,
            "title": metadata.get("title", ""),
            "text": self.extract_text(soup),
            "links": self.extract_links(soup, url),
            "metadata": metadata,
        }

    def extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Collect unique absolute http(s) links from ``<a href>``."""
        seen: set[str] = set()
        links: list[str] = []
        for tag in soup.find_all("a", href=True):
            href = tag.get("href")
            if not isinstance(href, str):
                continue
            href = href.strip()
            if not href or href.startswith("#"):
                continue
            absolute = urldefrag(urljoin(base_url, href)).url
            parsed = urlparse(absolute)
            if parsed.scheme.lower() in _SKIP_SCHEMES:
                continue
            if parsed.scheme.lower() not in _HTTP_SCHEMES:
                continue
            if not parsed.netloc:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append(absolute)
        return links

    def extract_text(self, soup: BeautifulSoup, selector: str = None) -> str:
        """Visible text, optionally limited to a CSS selector.

        Script/style tags are dropped. Whitespace is collapsed.
        """
        root = soup
        if selector:
            match = soup.select_one(selector)
            if match is None:
                return ""
            root = match
        for tag in root.find_all(["script", "style", "noscript"]):
            tag.decompose()
        text = root.get_text(separator=" ", strip=True)
        return " ".join(text.split())

    def extract_metadata(self, soup: BeautifulSoup) -> dict:
        """Extract title, description, and keywords from head/meta tags."""
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        else:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = str(og_title["content"]).strip()

        description = self._meta_content(
            soup,
            names=("description",),
            properties=("og:description",),
        )
        keywords = self._meta_content(soup, names=("keywords",))
        return {
            "title": title,
            "description": description,
            "keywords": keywords,
        }

    @staticmethod
    def _meta_content(
        soup: BeautifulSoup,
        names: tuple[str, ...] = (),
        properties: tuple[str, ...] = (),
    ) -> str:
        for name in names:
            tag = soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
        for prop in properties:
            tag = soup.find("meta", property=prop)
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
        return ""
