from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse

class URLFilter:
    """Decide whether a URL may be queued."""
    def __init__(self,
    *,
    same_domain_only: bool = True,
    allowed_hosts: Optional[Iterable[str]] = None,
    include_patterns: Optional[Iterable[str]] = None,
    exclude_patterns: Optional[Iterable[str]] = None,

    ) -> None:
        self.same_domain_only = same_domain_only
        self.allowed_hosts = {self._host(h) for h in (allowed_hosts or []) if h}
        self.include_patterns = self._compile(include_patterns)
        self.exclude_patterns = self._compile(exclude_patterns)
    

    @staticmethod
    def _compile(patterns: Optional[Iterable[str]]) -> list[re.Pattern[str]]:
        compiled: list[re.Pattern[str]] = []
        for raw in patterns or []:
            compiled.append(re.compile(raw))
        return compiled

    @staticmethod
    def _host(url_or_host: str) -> str:
        text = url_or_host.strip().lower()
        if "://" in text:
            host = urlparse(text).netloc
        else:
            host = text
        host = host.split("@")[-1]
        if host.startswith("www."):
            host = host[4:]
        return host

    def allow(self, url: str) -> bool:
        """True if this URL should be crawled."""
        host = self._host(url)
        if self.same_domain_only and self.allowed_hosts:
            if host not in self.allowed_hosts:
                return False
        if self.include_patterns:
            if not any(p.search(url) for p in self.include_patterns):
                return False
        if self.exclude_patterns:
            if any(p.search(url) for p in self.exclude_patterns):
                return False
        return True