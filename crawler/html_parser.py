"""HTML parsing helpers built on BeautifulSoup."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_SKIP_SCHEMES = {"javascript", "mailto", "tel", "data"}
_HTTP_SCHEMES = {"http", "https"}


class HTMLParser:
    """Parse HTML into title, text, same-host links, and structured extras."""

    def __init__(self, features: str = "html.parser") -> None:
        self.features = features

    def _soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, self.features)

    def _empty_page(self, url: str) -> dict:
        return {
            "url": url,
            "title": "",
            "text": "",
            "links": [],
            "link_details": [],
            "metadata": {"title": "", "description": "", "keywords": ""},
            "images": [],
            "headings": [],
            "tables": [],
            "lists": [],
        }

    async def parse_html(self, html: str, url: str) -> dict:
        """Parse HTML and return a page dict.

        Always returns a dict with ``url``. Extractor failures are logged and
        replaced with empty defaults so the caller still gets a partial result.
        """
        page = self._empty_page(url)
        if html is None:
            logger.warning("Empty HTML for %s", url)
            return page

        try:
            soup = self._soup(html)
        except Exception as exc:
            logger.warning("Failed to parse HTML for %s [%s]: %s", url, type(exc).__name__, exc)
            return page

        page["metadata"] = self._safe_extract("metadata", url, lambda: self.extract_metadata(soup), page["metadata"])
        page["title"] = page["metadata"].get("title", "") if isinstance(page["metadata"], dict) else ""
        page["text"] = self._safe_extract("text", url, lambda: self.extract_text(soup), "")
        page["links"] = self._safe_extract("links", url, lambda: self.extract_links(soup, url), [])
        page["link_details"] = self._safe_extract(
            "link_details", url, lambda: self.extract_link_details(soup, url), []
        )
        page["images"] = self._safe_extract("images", url, lambda: self.extract_images(soup, url), [])
        page["headings"] = self._safe_extract("headings", url, lambda: self.extract_headings(soup), [])
        page["tables"] = self._safe_extract("tables", url, lambda: self.extract_tables(soup), [])
        page["lists"] = self._safe_extract("lists", url, lambda: self.extract_lists(soup), [])
        return page

    def _safe_extract(self, name: str, url: str, fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception as exc:
            logger.warning("Failed to extract %s from %s [%s]: %s", name, url, type(exc).__name__, exc)
            return default

    @staticmethod
    def _host(url: str) -> str:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host

    def is_valid_url(self, url: str) -> bool:
        """True if ``url`` is absolute http(s) with a host."""
        if not url or not isinstance(url, str):
            return False
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in _HTTP_SCHEMES:
            return False
        if not parsed.netloc:
            return False
        return True

    def to_absolute_url(self, href: str, base_url: str) -> Optional[str]:
        """Resolve ``href`` against ``base_url``. None if invalid."""
        if not isinstance(href, str):
            return None
        href = href.strip()
        if not href or href.startswith("#"):
            return None
        parsed_raw = urlparse(href)
        if parsed_raw.scheme.lower() in _SKIP_SCHEMES:
            return None
        absolute = urldefrag(urljoin(base_url, href)).url
        if not self.is_valid_url(absolute):
            return None
        return absolute

    def extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Same-host absolute http(s) links from ``<a href>``.

        Relative hrefs are resolved. Outer hosts, fragments, mailto, and
        javascript are dropped. Invalid URLs are skipped with a warning.
        """
        seen: set[str] = set()
        links: list[str] = []
        base_host = self._host(base_url)
        for tag in soup.find_all("a", href=True):
            href = tag.get("href")
            if not isinstance(href, str):
                continue
            raw = href.strip()
            absolute = self.to_absolute_url(raw, base_url)
            if absolute is None:
                if raw and not raw.startswith("#"):
                    logger.warning("Skipping invalid link %r on %s", raw, base_url)
                continue
            if self._host(absolute) != base_host:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append(absolute)
        return links

    def extract_link_details(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Original href plus resolved absolute URL and keep/skip reason."""
        details: list[dict] = []
        base_host = self._host(base_url)
        for tag in soup.find_all("a", href=True):
            href = tag.get("href")
            if not isinstance(href, str):
                continue
            raw = href.strip()
            if not raw:
                continue
            absolute = self.to_absolute_url(raw, base_url)
            if absolute is None:
                details.append({"href": raw, "absolute": None, "kept": False, "reason": "invalid"})
                continue
            if self._host(absolute) != base_host:
                details.append({"href": raw, "absolute": absolute, "kept": False, "reason": "outer"})
                continue
            details.append({"href": raw, "absolute": absolute, "kept": True, "reason": "ok"})
        return details

    def extract_text(self, soup: BeautifulSoup, selector: str = None) -> str:
        """Visible text, optionally limited to a CSS selector."""
        root = BeautifulSoup(str(soup), self.features)
        if selector:
            match = root.select_one(selector)
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

    def extract_images(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Images as ``{src, alt}``. ``src`` is absolute when possible."""
        images: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for tag in soup.find_all("img"):
            src_raw = tag.get("src")
            if not isinstance(src_raw, str) or not src_raw.strip():
                logger.warning("Skipping image without src on %s", base_url)
                continue
            src = self.to_absolute_url(src_raw, base_url) or src_raw.strip()
            alt = tag.get("alt")
            alt_text = alt.strip() if isinstance(alt, str) else ""
            key = (src, alt_text)
            if key in seen:
                continue
            seen.add(key)
            images.append({"src": src, "alt": alt_text})
        return images

    def extract_headings(self, soup: BeautifulSoup) -> list[dict]:
        """``h1`` / ``h2`` / ``h3`` as ``{level, text}``."""
        headings: list[dict] = []
        for tag in soup.find_all(["h1", "h2", "h3"]):
            text = " ".join(tag.get_text(separator=" ", strip=True).split())
            if not text:
                continue
            headings.append({"level": tag.name, "text": text})
        return headings

    def extract_tables(self, soup: BeautifulSoup) -> list[dict]:
        """Tables as ``{headers, rows}``."""
        tables: list[dict] = []
        for table in soup.find_all("table"):
            headers: list[str] = []
            header_row = table.find("tr")
            if header_row:
                header_cells = header_row.find_all(["th", "td"])
                headers = [" ".join(cell.get_text(" ", strip=True).split()) for cell in header_cells]
            rows: list[list[str]] = []
            body_rows = table.find_all("tr")
            start = 1 if headers else 0
            for row in body_rows[start:]:
                cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all(["td", "th"])]
                if any(cells):
                    rows.append(cells)
            if headers or rows:
                tables.append({"headers": headers, "rows": rows})
        return tables

    def extract_lists(self, soup: BeautifulSoup) -> list[dict]:
        """``ul`` / ``ol`` as ``{type, items}``. Nested lists are flattened per item text."""
        lists: list[dict] = []
        for tag in soup.find_all(["ul", "ol"]):
            if tag.find_parent(["ul", "ol"]) is not None:
                continue
            items: list[str] = []
            for li in tag.find_all("li", recursive=False):
                clone = BeautifulSoup(str(li), self.features).li
                if clone is None:
                    continue
                for nested in clone.find_all(["ul", "ol"]):
                    nested.decompose()
                text = " ".join(clone.get_text(" ", strip=True).split())
                if text:
                    items.append(text)
            if items:
                lists.append({"type": tag.name, "items": items})
        return lists

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
