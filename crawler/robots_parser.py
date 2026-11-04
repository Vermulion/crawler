from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import aiohttp


class RobotsParser:
    """Download robots.txt once per site and answer allow / crawl-delay."""

    def __init__(self) -> None:
        self._cache: dict[str, RobotFileParser] = {}
        self._status: dict[str, int] = {}

    def _origin(self, url: str) -> str:
        parsed = urlsplit(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("url must include a scheme and a host, such as https://a.test/path")
        return f"{parsed.scheme}://{parsed.netloc.lower()}"

    def _stored(self, url: str) -> Optional[RobotFileParser]:
        return self._cache.get(self._origin(url))

    async def fetch_robots(self, base_url: str) -> dict:
            """GET <origin>/robots.txt and cache the parsed rules."""
            origin = self._origin(base_url)
            robots_url = origin + "/robots.txt"
            if origin in self._cache:
                return self._summary(origin, robots_url)
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(robots_url) as response:
                    status = response.status
                    text = await response.text()
            return self.store(base_url, status, text)

    def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        """True when the cached rules allow this agent to fetch url."""
        parser = self._stored(url)
        if parser is None:
            return False
        return parser.can_fetch(user_agent, url)

    def get_crawl_delay(self, url: str, user_agent: str = "*") -> float:
        """Seconds to wait between requests. 0.0 when the file has no Crawl-delay."""
        parser = self._stored(url)
        if parser is None:
            return 0.0
        delay = parser.crawl_delay(user_agent)
        if delay is None:
            return 0.0
        return float(delay)

    def store(self, base_url: str, status: int, text: str) -> dict:
        """Parse one robots.txt response and cache it for this origin."""
        origin = self._origin(base_url)
        robots_url = origin + "/robots.txt"
        parser = RobotFileParser()
        if status in (401, 403):
            parser.disallow_all = True
            parser.parse([])
        elif 400 <= status < 500:
            parser.allow_all = True
            parser.parse([])
        elif status >= 500:
            return {
                "origin": origin,
                "robots_url": robots_url,
                "status": status,
                "cached": False,
                "crawl_delay": 0.0,
                "sitemaps": [],
            }
        else:
            parser.parse(text.splitlines())
        self._cache[origin] = parser
        self._status[origin] = status
        return self._summary(origin, robots_url)

    def _summary(self, origin: str, robots_url: str) -> dict:
        parser = self._cache[origin]
        return {
            "origin": origin,
            "robots_url": robots_url,
            "status": self._status[origin],
            "cached": True,
            "crawl_delay": self.get_crawl_delay(origin + "/"),
            "sitemaps": list(parser.sitemaps),
        }

class RobotsDenied(Exception):
    """The URL is disallowed by robots.txt."""