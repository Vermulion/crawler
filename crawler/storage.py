"""Async storage backends for crawled pages (JSON, CSV, PostgreSQL)."""

from __future__ import annotations

import csv
import io
import json
import re
import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from datetime import datetime, timezone

import aiofiles

_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class StorageError(Exception):
    """Bad data or a storage backend failure."""


class DataStorage(ABC):
    """Common interface: save one dict, then close the backend."""

    @abstractmethod
    async def save(self, data: dict) -> None:
        """Persist one record (a page dict or a report dict)."""

    async def flush(self) -> None:
        """Persist one record (a page dict or a report dict)."""

    @abstractmethod
    async def close(self) -> None:
        """Release files / database connections."""

    async def __aenter__(self) -> DataStorage:
        return self

    async def save_many(self, rows: list[dict]) -> None:
        """Save many records. PostgresStorage overrides this with executemany."""
        for row in rows:
            await self.save(row)

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def _require_dict(data: dict) -> dict:
    if not isinstance(data, dict):
        raise StorageError(f"save() expects a dict, got {type(data).__name__}")
    return data

RECORD_FIELDS = (
    "url",
    "title",
    "text",
    "links",
    "metadata",
    "crawled_at",
    "status_code",
    "content_type",
)


def _json_default(obj: Any) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def normalize_page(data: dict, *, now: datetime | None = None) -> dict:
    """Turn any dict into the saved page record (missing keys get defaults)."""
    data = _require_dict(data)
    crawled_at = data.get("crawled_at")
    if isinstance(crawled_at, datetime):
        if crawled_at.tzinfo is None:
            crawled_at = crawled_at.replace(tzinfo=timezone.utc)
    elif isinstance(crawled_at, str) and crawled_at:
        crawled_at = datetime.fromisoformat(crawled_at.replace("Z", "+00:00"))
    else:
        crawled_at = now or datetime.now(timezone.utc)

    links = data.get("links") or []
    if not isinstance(links, list):
        links = []
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

    raw_status = data.get("status_code", data.get("status"))
    try:
        status_code = int(raw_status) if raw_status is not None else 0
    except (TypeError, ValueError):
        status_code = 0

    return {
        "url": str(data.get("url") or ""),
        "title": str(data.get("title") or ""),
        "text": str(data.get("text") or ""),
        "links": [str(item) for item in links],
        "metadata": metadata,
        "crawled_at": crawled_at,
        "status_code": status_code,
        "content_type": str(data.get("content_type") or ""),
    }

def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)

def _encode_json_line(data: dict, indent: int | None, ensure_ascii: bool) -> str:
    page = normalize_page(data)
    return json.dumps(
        page,
        ensure_ascii=ensure_ascii,
        indent=indent,
        default=_json_default,
    ) + "\n"


def _encode_json_lines(
    rows: list[dict], indent: int | None, ensure_ascii: bool
) -> str:
    return "".join(_encode_json_line(row, indent, ensure_ascii) for row in rows)


def _encode_csv_chunk(
    rows: list[dict],
    *,
    fieldnames: list[str],
    delimiter: str,
    write_header: bool,
) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=fieldnames,
        extrasaction="ignore",
        restval="",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
        delimiter=delimiter,
        quotechar='"',
        doublequote=True,
    )
    if write_header:
        writer.writeheader()
    for data in rows:
        page = normalize_page(data)
        writer.writerow({key: _cell(page[key]) for key in fieldnames})
    return buf.getvalue()


def _pg_tuples(rows: list[dict]) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for data in rows:
        page = normalize_page(data)
        payload = json.dumps(page, ensure_ascii=False, default=_json_default)
        out.append((page["url"], page["title"], payload))
    return out


def _mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


class JSONStorage(DataStorage):
    """JSONL with an in-memory buffer. CPU encoding runs in a thread."""

    def __init__(
        self,
        path: str | Path,
        *,
        indent: int | None = 2,
        ensure_ascii: bool = False,
        buffer_bytes: int = 64 * 1024,
    ) -> None:
        if buffer_bytes < 1:
            raise StorageError("buffer_bytes must be >= 1")
        self.path = Path(path)
        self.indent = indent
        self.ensure_ascii = ensure_ascii
        self.buffer_bytes = buffer_bytes
        self._fh: Any = None
        self._chunks: list[str] = []
        self._buffered = 0

    async def _ensure_open(self) -> Any:
        if self._fh is None:
            await asyncio.to_thread(_mkdir, self.path.parent)
            self._fh = await aiofiles.open(self.path, "a", encoding="utf-8")
        return self._fh

    async def _flush_file(self) -> None:
        if not self._chunks:
            return
        blob = "".join(self._chunks)
        self._chunks.clear()
        self._buffered = 0
        fh = await self._ensure_open()
        await fh.write(blob)

    async def save(self, data: dict) -> None:
        await self.save_many([data])

    async def save_many(self, rows: list[dict]) -> None:
        if not rows:
            return
        text = await asyncio.to_thread(
            _encode_json_lines, rows, self.indent, self.ensure_ascii
        )
        self._chunks.append(text)
        self._buffered += len(text.encode("utf-8"))
        if self._buffered >= self.buffer_bytes:
            await self._flush_file()

    async def close(self) -> None:
        await self._flush_file()
        if self._fh is not None:
            await self._fh.flush()
            await self._fh.close()
            self._fh = None

    async def flush(self) -> None:
        await self._flush_file()
        if self._fh is not None:
            await self._fh.flush()

class CSVStorage(DataStorage):
    """Append CSV rows with an in-memory buffer. Encoding runs in a thread."""

    def __init__(
        self,
        path: str | Path,
        *,
        fieldnames: Optional[list[str]] = None,
        encoding: str = "utf-8",
        delimiter: str = ",",
        buffer_bytes: int = 64 * 1024,
    ) -> None:
        if buffer_bytes < 1:
            raise StorageError("buffer_bytes must be >= 1")
        self.path = Path(path)
        self.fieldnames = list(fieldnames) if fieldnames else None
        self.encoding = encoding
        self.delimiter = delimiter
        self.buffer_bytes = buffer_bytes
        self._fh: Any = None
        self._header_written = False
        self._chunks: list[str] = []
        self._buffered = 0

    async def _prepare(self) -> None:
        if self.fieldnames is not None:
            return
        exists = await asyncio.to_thread(
            lambda: self.path.exists() and self.path.stat().st_size > 0
        )
        if exists:
            async with aiofiles.open(
                self.path, "r", encoding=self.encoding, newline=""
            ) as fh:
                first = await fh.readline()
            columns = next(csv.reader([first], delimiter=self.delimiter), [])
            if columns:
                self.fieldnames = columns
                self._header_written = True
        if self.fieldnames is None:
            self.fieldnames = list(RECORD_FIELDS)

    async def _ensure_open(self) -> Any:
        if self._fh is None:
            await asyncio.to_thread(_mkdir, self.path.parent)
            self._fh = await aiofiles.open(
                self.path, "a", encoding=self.encoding, newline=""
            )
        return self._fh

    async def _flush_file(self) -> None:
        if not self._chunks:
            return
        blob = "".join(self._chunks)
        self._chunks.clear()
        self._buffered = 0
        fh = await self._ensure_open()
        await fh.write(blob)

    async def save(self, data: dict) -> None:
        await self.save_many([data])

    async def save_many(self, rows: list[dict]) -> None:
        if not rows:
            return
        await self._prepare()
        assert self.fieldnames is not None
        write_header = not self._header_written
        text = await asyncio.to_thread(
            _encode_csv_chunk,
            rows,
            fieldnames=self.fieldnames,
            delimiter=self.delimiter,
            write_header=write_header,
        )
        if write_header:
            self._header_written = True
        self._chunks.append(text)
        self._buffered += len(text.encode(self.encoding, errors="replace"))
        if self._buffered >= self.buffer_bytes:
            await self._flush_file()

    async def close(self) -> None:
        await self._flush_file()
        if self._fh is not None:
            await self._fh.flush()
            await self._fh.close()
            self._fh = None

    async def flush(self) -> None:
        await self._flush_file()
        if self._fh is not None:
            await self._fh.flush()


class PostgresStorage(DataStorage):
    """Insert page dicts with asyncpg. Call init_db() once; save() batches with executemany."""

    def __init__(
        self,
        dsn: str,
        *,
        table: str = "pages",
        batch_size: int = 100,
        connect: Optional[Callable[[str], Awaitable[Any]]] = None,
    ) -> None:
        if not _TABLE_NAME.match(table):
            raise StorageError(f"Invalid table name: {table!r}")
        if batch_size < 1:
            raise StorageError("batch_size must be >= 1")
        self.dsn = dsn
        self.table = table
        self.batch_size = batch_size
        self._connect = connect
        self._conn: Any = None
        self._ready = False
        self._buffer: list[tuple[str, str, str]] = []

    async def _get_conn(self) -> Any:
        if self._conn is not None:
            return self._conn
        connect = self._connect
        if connect is None:
            import asyncpg

            connect = asyncpg.connect
        self._conn = await connect(self.dsn)
        return self._conn

    async def init_db(self) -> None:
        """Create the table and search indexes (safe to call more than once)."""
        conn = await self._get_conn()
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                id SERIAL PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT,
                payload JSONB NOT NULL,
                saved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.table}_url_idx ON {self.table} (url)"
        )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.table}_saved_at_idx "
            f"ON {self.table} (saved_at)"
        )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.table}_payload_gin_idx "
            f"ON {self.table} USING GIN (payload)"
        )
        self._ready = True

    async def flush(self) -> None:
        """Send buffered rows in one executemany() call."""
        if not self._buffer:
            return
        if not self._ready:
            await self.init_db()
        conn = await self._get_conn()
        rows = list(self._buffer)
        self._buffer.clear()
        await conn.executemany(
            f"INSERT INTO {self.table} (url, title, payload) "
            f"VALUES ($1, $2, $3::jsonb)",
            rows,
        )

    async def save(self, data: dict) -> None:
        tuples = await asyncio.to_thread(_pg_tuples, [data])
        self._buffer.extend(tuples)
        if len(self._buffer) >= self.batch_size:
            await self.flush()

    async def save_many(self, rows: list[dict]) -> None:
        if not rows:
            return
        tuples = await asyncio.to_thread(_pg_tuples, rows)
        self._buffer.extend(tuples)
        await self.flush()

    async def close(self) -> None:
        await self.flush()
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> PostgresStorage:
        await self.init_db()
        return self