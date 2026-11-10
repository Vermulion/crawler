"""Async storage backends for crawled pages (JSON, CSV, PostgreSQL)."""

from __future__ import annotations

import csv
import io
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import aiofiles

_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class StorageError(Exception):
    """Bad data or a storage backend failure."""


class DataStorage(ABC):
    """Common interface: save one dict, then close the backend."""

    @abstractmethod
    async def save(self, data: dict) -> None:
        """Persist one record (a page dict or a report dict)."""

    @abstractmethod
    async def close(self) -> None:
        """Release files / database connections."""

    async def __aenter__(self) -> DataStorage:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def _require_dict(data: dict) -> dict:
    if not isinstance(data, dict):
        raise StorageError(f"save() expects a dict, got {type(data).__name__}")
    return data


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


class JSONStorage(DataStorage):
    """Append one JSON value per save() (JSONL). Use indent=2 for pretty output."""

    def __init__(
        self,
        path: str | Path,
        *,
        indent: int | None = 2,
        ensure_ascii: bool = False,
    ) -> None:
        self.path = Path(path)
        self.indent = indent
        self.ensure_ascii = ensure_ascii
        self._fh: Any = None

    async def _ensure_open(self) -> Any:
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = await aiofiles.open(self.path, "a", encoding="utf-8")
        return self._fh

    async def save(self, data: dict) -> None:
        data = _require_dict(data)
        fh = await self._ensure_open()
        encoder = json.JSONEncoder(
            ensure_ascii=self.ensure_ascii,
            indent=self.indent,
        )
        # Stream chunks: a large "text" / links list is not dumped as one string.
        for chunk in encoder.iterencode(data):
            await fh.write(chunk)
        await fh.write("\n")
        await fh.flush()

    async def close(self) -> None:
        if self._fh is not None:
            await self._fh.close()
            self._fh = None


class CSVStorage(DataStorage):
    """Append one CSV row per save(). Headers come from the first row or an existing file."""

    def __init__(
        self,
        path: str | Path,
        *,
        fieldnames: Optional[list[str]] = None,
        encoding: str = "utf-8",
        delimiter: str = ",",
    ) -> None:
        self.path = Path(path)
        self.fieldnames = list(fieldnames) if fieldnames else None
        self.encoding = encoding
        self.delimiter = delimiter
        self._fh: Any = None
        self._header_written = False

    def _writer(self, buf: io.StringIO) -> csv.DictWriter:
        if self.fieldnames is None:
            raise StorageError("CSV headers are not set")
        return csv.DictWriter(
            buf,
            fieldnames=self.fieldnames,
            extrasaction="ignore",
            restval="",
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
            delimiter=self.delimiter,
            quotechar='"',
            doublequote=True,
        )

    async def _ensure_open(self) -> Any:
        if self._fh is not None:
            return self._fh
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists() and self.path.stat().st_size > 0
        if self.fieldnames is None and exists:
            async with aiofiles.open(
                self.path, "r", encoding=self.encoding, newline=""
            ) as fh:
                first = await fh.readline()
            columns = next(csv.reader([first], delimiter=self.delimiter), [])
            if columns:
                self.fieldnames = columns
                self._header_written = True
        self._fh = await aiofiles.open(
            self.path, "a", encoding=self.encoding, newline=""
        )
        return self._fh

    async def save(self, data: dict) -> None:
        data = _require_dict(data)
        row = {key: _cell(value) for key, value in data.items()}
        fh = await self._ensure_open()
        if self.fieldnames is None:
            self.fieldnames = list(row.keys())
        if not self._header_written:
            buf = io.StringIO()
            self._writer(buf).writeheader()
            await fh.write(buf.getvalue())
            self._header_written = True
        buf = io.StringIO()
        self._writer(buf).writerow(row)
        await fh.write(buf.getvalue())
        await fh.flush()

    async def close(self) -> None:
        if self._fh is not None:
            await self._fh.close()
            self._fh = None


class PostgresStorage(DataStorage):
    """INSERT each dict as JSON. Pass connect=... in tests (no real database)."""

    def __init__(
        self,
        dsn: str,
        *,
        table: str = "pages",
        connect: Optional[Callable[[str], Awaitable[Any]]] = None,
    ) -> None:
        if not _TABLE_NAME.match(table):
            raise StorageError(f"Invalid table name: {table!r}")
        self.dsn = dsn
        self.table = table
        self._connect = connect
        self._conn: Any = None

    async def _get_conn(self) -> Any:
        if self._conn is not None:
            return self._conn
        connect = self._connect
        if connect is None:
            import asyncpg

            connect = asyncpg.connect
        self._conn = await connect(self.dsn)
        await self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                id SERIAL PRIMARY KEY,
                url TEXT,
                payload JSONB NOT NULL,
                saved_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        return self._conn

    async def save(self, data: dict) -> None:
        data = _require_dict(data)
        conn = await self._get_conn()
        payload = json.dumps(data, ensure_ascii=False)
        url = str(data.get("url") or "")
        await conn.execute(
            f"INSERT INTO {self.table} (url, payload) VALUES ($1, $2::jsonb)",
            url,
            payload,
        )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None