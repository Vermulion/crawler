"""Load sitemap.xml: urlset pages and recursive sitemap indexes."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Optional
from urllib.parse import urljoin

import aiohttp

class SitemapParser:
    """Fetch sitemap.xml and return page URLs (not nested sitemap file URLs)."""
    def __init__(self, session: Any | None = None) -> None:
        self._session = session

    def _local(self, tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    def _locs(self, root: ET.Element) -> list[str]:
        out: list[str] = []
        for el in root.iter():
            if self._local(el.tag) == "loc" and el.text:
                loc = el.text.strip()
                if loc:
                    out.append(loc)
        return out

    def parse_sitemap(self, xml_text: str) -> tuple[str, list[str]]:
        """Return ('urlset' | 'index', list of <loc> strings)."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return "urlset", []
        kind = self._local(root.tag)
        locs = self._locs(root)
        if kind == "sitemapindex":
            return "index", locs
        return "urlset", locs

    async def _get_text(self, url: str, session: Any) -> Optional[str]:
        try:
            async with session.get(url) as response:
                if response.status >= 400:
                    return None
                return await response.text()
        except (aiohttp.ClientError, OSError):
            return None

    async def fetch_sitemap(
        self,
        sitemap_url: str,
        session: Any | None = None,
        *,
        _seen: set[str] | None = None,
    ) -> list[str]:
        """GET sitemap_url; follow indexes; return page URLs in order, unique."""
        session = session or self._session
        if session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as owned:
                return await self.fetch_sitemap(
                    sitemap_url, session=owned, _seen=_seen
                )

        seen = _seen if _seen is not None else set()
        sitemap_url = sitemap_url.strip()
        if not sitemap_url or sitemap_url in seen:
            return []

        seen.add(sitemap_url)
        text = await self._get_text(sitemap_url, session)
        if not text:
            return []
        kind, locs = self.parse_sitemap(text)
        pages: list[str] = []
        found: set[str] = set()

        def add(url: str) -> None:
            url = urljoin(sitemap_url, url.strip())
            if url and url not in found:
                found.add(url)
                pages.append(url)
        if kind == "index":
            for child in locs:
                child_url = urljoin(sitemap_url, child)
                for url in await self.fetch_sitemap(
                    child_url, session=session, _seen=seen
                ):
                    add(url)
            return pages
        for loc in locs:
            add(loc)
        return pages