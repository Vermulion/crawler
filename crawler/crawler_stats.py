"""Snapshot of crawl totals: pages, errors, speed, status codes, domains."""

from __future__ import annotations

import html
import json
from io import BytesIO
from pathlib import Path
import base64
import time
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

class CrawlerStats:
    """Read-only summary. Call summary() whenever you need numbers."""

    def __init__(self, crawler: Any, *, top_n: int = 10) -> None:
        self._crawler = crawler
        self.top_n = top_n

    def summary(self) -> dict:
        """Return a dict of crawl stats."""
        c = self._crawler
        elapsed = time.monotonic() - c._stats_start
        pages = len(c.processed_urls)
        failed = len(c.failed_urls)
        speed = pages / elapsed if elapsed > 0 else 0.0
        status_codes: Counter[int] = Counter()
        domains: Counter[str] = Counter()
        for url, page in c.processed_urls.items():
            raw = page.get("status_code")
            try:
                status_codes[int(raw)] += 1
            except (TypeError, ValueError):
                pass
            host = urlsplit(url).netloc.lower()
            if host:
                domains[host] += 1
        for row in c.error_log:
            if row.get("result") != "failure":
                continue
            status = row.get("status")
            if status is None:
                continue
            try:
                status_codes[int(status)] += 1
            except (TypeError, ValueError):
                pass
        return {
            "pages_processed": pages,
            "successful_requests": pages,
            "failed_requests": failed,
            "total_pages": pages,       # homework alias
            "successful": pages,
            "failed": failed,
            "avg_pages_per_second": speed,
            "status_codes": dict(status_codes),
            "top_domains": domains.most_common(self.top_n),
            "elapsed_seconds": elapsed,
            "failed_urls": dict(c.failed_urls),
        }

    def export_to_json(self, filename: str) -> str:
        """Write summary() to a UTF-8 JSON file. Returns the absolute path."""
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.summary()
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return str(path.resolve())

    def export_charts(self, directory: str) -> dict[str, str]:
        """Save PNG bar charts. Returns {chart_name: filepath}."""
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        pngs = self._chart_pngs()
        saved: dict[str, str] = {}
        for name, blob in pngs.items():
            dest = target / f"{name}.png"
            dest.write_bytes(blob)
            saved[name] = str(dest.resolve())
        return saved

    def export_to_html_report(self, filename: str) -> str:
        """Write an HTML report with tables and embedded charts."""
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._html_report(), encoding="utf-8")
        return str(path.resolve())

    def _chart_pngs(self) -> dict[str, bytes]:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        stats = self.summary()
        out: dict[str, bytes] = {}

        def _bar(title: str, labels: list[str], values: list[float], name: str) -> None:
            fig, ax = plt.subplots(figsize=(6, 3.5))
            if labels:
                ax.bar(labels, values)
            else:
                ax.text(0.5, 0.5, "no data", ha="center", va="center")
                ax.set_xticks([])
                ax.set_yticks([])
            ax.set_title(title)
            fig.tight_layout()
            buf = BytesIO()
            fig.savefig(buf, format="png", dpi=100)
            plt.close(fig)
            out[name] = buf.getvalue()

        codes = stats["status_codes"]
        _bar(
            "HTTP status codes",
            [str(k) for k in codes],
            [float(v) for v in codes.values()],
            "status_codes",
        )
        domains = stats["top_domains"]
        _bar(
            "Top domains (pages)",
            [str(host) for host, _n in domains],
            [float(n) for _host, n in domains],
            "top_domains",
        )
        _bar(
            "Success vs failed pages",
            ["successful", "failed"],
            [
                float(stats["successful_requests"]),
                float(stats["failed_requests"]),
            ],
            "success_fail",
        )
        return out

    def _html_report(self) -> str:
        stats = self.summary()
        pngs = self._chart_pngs()

        def img(name: str) -> str:
            b64 = base64.b64encode(pngs[name]).decode("ascii")
            return (
                f'<img alt="{html.escape(name)}" '
                f'src="data:image/png;base64,{b64}" />'
            )

        def kv_table(rows: list[tuple[str, object]]) -> str:
            body = "".join(
                "<tr><th>{}</th><td>{}</td></tr>".format(
                    html.escape(str(k)), html.escape(str(v))
                )
                for k, v in rows
            )
            return f"<table>{body}</table>"

        overview = kv_table(
            [
                ("pages_processed", stats["pages_processed"]),
                ("successful_requests", stats["successful_requests"]),
                ("failed_requests", stats["failed_requests"]),
                ("avg_pages_per_second", f"{stats['avg_pages_per_second']:.4f}"),
                ("elapsed_seconds", f"{stats['elapsed_seconds']:.4f}"),
            ]
        )
        status_rows = kv_table(
            [(str(code), count) for code, count in stats["status_codes"].items()]
        )
        domain_rows = kv_table(
            [(host, count) for host, count in stats["top_domains"]]
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Crawler report</title>
  <style>
    body {{ font-family: sans-serif; max-width: 900px; margin: 2rem auto; }}
    table {{ border-collapse: collapse; margin: 1rem 0; }}
    th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.7rem; text-align: left; }}
    img {{ max-width: 100%; height: auto; margin: 0.5rem 0; }}
  </style>
</head>
<body>
  <h1>Crawler statistics</h1>
  <h2>Overview</h2>
  {overview}
  <h2>Status codes</h2>
  {status_rows}
  {img("status_codes")}
  <h2>Top domains</h2>
  {domain_rows}
  {img("top_domains")}
  <h2>Success vs failed</h2>
  {img("success_fail")}
</body>
</html>
"""
