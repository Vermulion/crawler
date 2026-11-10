"""Offline tests for DataStorage backends."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from datetime import datetime, timezone

from crawler.storage import (
    CSVStorage,
    DataStorage,
    JSONStorage,
    PostgresStorage,
    RECORD_FIELDS,
    StorageError,
    normalize_page,
)

import pytest

from crawler.storage import (
    CSVStorage,
    DataStorage,
    JSONStorage,
    PostgresStorage,
    StorageError,
)


PAGE = {
    "url": "https://example.com/",
    "title": "Example",
    "text": "Hello",
    "links": ["https://example.com/a"],
    "metadata": {"description": "demo"},
}


def test_cannot_create_abstract_storage() -> None:
    with pytest.raises(TypeError):
        DataStorage()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_json_storage_appends_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "pages.jsonl"
    async with JSONStorage(path, indent=None) as storage:
        await storage.save(PAGE)
        await storage.save({"url": "https://example.com/a", "title": "A"})

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "Example"
    assert json.loads(lines[1])["url"] == "https://example.com/a"

@pytest.mark.asyncio
async def test_json_storage_formatted_indent(tmp_path: Path) -> None:
    path = tmp_path / "page.json"
    async with JSONStorage(path, indent=2) as storage:
        await storage.save(PAGE)

    text = path.read_text(encoding="utf-8")
    assert "\n" in text
    assert '  "url":' in text
    assert json.loads(text)["title"] == "Example"


@pytest.mark.asyncio
async def test_json_storage_streams_large_text(tmp_path: Path) -> None:
    path = tmp_path / "big.jsonl"
    big = {**PAGE, "text": "x" * 50_000}
    async with JSONStorage(path, indent=None) as storage:
        await storage.save(big)

    line = path.read_text(encoding="utf-8").strip()
    loaded = json.loads(line)
    assert len(loaded["text"]) == 50_000


@pytest.mark.asyncio
async def test_csv_storage_writes_header_and_flattens(tmp_path: Path) -> None:
    path = tmp_path / "pages.csv"
    async with CSVStorage(path) as storage:
        await storage.save(PAGE)
        await storage.save({"url": "https://example.com/a", "title": "A"})

    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["url"] == "https://example.com/"
    assert rows[0]["title"] == "Example"
    assert json.loads(rows[0]["links"]) == ["https://example.com/a"]
    assert rows[1]["title"] == "A"

@pytest.mark.asyncio
async def test_csv_detects_header_from_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "pages.csv"
    async with CSVStorage(path) as storage:
        await storage.save({"url": "https://a.test/", "title": "A"})

    async with CSVStorage(path) as storage:
        await storage.save({"url": "https://b.test/", "title": "B"})
        assert storage.fieldnames == list(RECORD_FIELDS)

    text = path.read_text(encoding="utf-8")
    header = ",".join(RECORD_FIELDS)
    assert text.count(header) == 1
    rows = list(csv.DictReader(text.splitlines()))
    assert [row["title"] for row in rows] == ["A", "B"]
    assert [row["url"] for row in rows] == ["https://a.test/", "https://b.test/"]


@pytest.mark.asyncio
async def test_csv_quotes_special_characters(tmp_path: Path) -> None:
    path = tmp_path / "special.csv"
    page = {
        "url": "https://example.com/",
        "title": 'Hello, "world"',
        "text": "line1\nline2",
    }
    async with CSVStorage(path) as storage:
        await storage.save(page)

    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["title"] == 'Hello, "world"'
    assert rows[0]["text"] == "line1\nline2"
    raw = path.read_text(encoding="utf-8")
    assert '"Hello, ""world"""' in raw


@pytest.mark.asyncio
async def test_csv_encoding_cp1251(tmp_path: Path) -> None:
    path = tmp_path / "ru.csv"
    async with CSVStorage(path, encoding="cp1251") as storage:
        await storage.save({"url": "https://example.com/", "title": "Привет"})

    raw = path.read_bytes()
    assert "Привет".encode("cp1251") in raw
    with path.open(encoding="cp1251", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["title"] == "Привет"

@pytest.mark.asyncio
async def test_save_rejects_non_dict(tmp_path: Path) -> None:
    storage = JSONStorage(tmp_path / "x.jsonl")
    with pytest.raises(StorageError):
        await storage.save(["not", "a", "dict"])  # type: ignore[arg-type]


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[tuple] = []
        self.closed = False

    async def execute(self, query: str, *args: object) -> str:
        self.statements.append((query, args))
        return "OK"

    async def executemany(self, query: str, rows: list) -> str:
        self.statements.append((query, rows))
        return "OK"

    async def close(self) -> None:
        self.closed = True


def _pg(fake: FakeConnection, **kwargs: object) -> PostgresStorage:
    async def connect(dsn: str) -> FakeConnection:
        assert dsn.startswith("postgresql://")
        return fake

    return PostgresStorage(
        "postgresql://user:pass@localhost:5432/crawler",
        connect=connect,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_postgres_init_db_creates_table_and_indexes() -> None:
    fake = FakeConnection()
    storage = _pg(fake)
    await storage.init_db()
    sql = " ".join(q for q, _ in fake.statements)
    assert "CREATE TABLE IF NOT EXISTS pages" in sql
    assert "pages_url_idx" in sql
    assert "pages_saved_at_idx" in sql
    assert "USING GIN" in sql
    await storage.close()


@pytest.mark.asyncio
async def test_postgres_save_flushes_on_close() -> None:
    fake = FakeConnection()
    storage = _pg(fake, batch_size=100)
    await storage.save(PAGE)
    batches = [rows for q, rows in fake.statements if "INSERT INTO" in q]
    assert batches == []
    await storage.close()
    assert fake.closed is True
    inserts = [(q, rows) for q, rows in fake.statements if "INSERT INTO" in q]
    assert len(inserts) == 1
    query, rows = inserts[0]
    assert "pages" in query
    assert rows[0][0] == "https://example.com/"
    assert json.loads(rows[0][2])["title"] == "Example"


@pytest.mark.asyncio
async def test_postgres_batch_insert_when_buffer_full() -> None:
    fake = FakeConnection()
    storage = _pg(fake, batch_size=2)
    await storage.save({"url": "https://a.test/", "title": "A"})
    await storage.save({"url": "https://b.test/", "title": "B"})
    inserts = [(q, rows) for q, rows in fake.statements if "INSERT INTO" in q]
    assert len(inserts) == 1
    assert len(inserts[0][1]) == 2
    await storage.close()


@pytest.mark.asyncio
async def test_postgres_save_many() -> None:
    fake = FakeConnection()
    storage = _pg(fake)
    await storage.save_many(
        [
            {"url": "https://a.test/", "title": "A"},
            {"url": "https://b.test/", "title": "B"},
        ]
    )
    inserts = [(q, rows) for q, rows in fake.statements if "INSERT INTO" in q]
    assert len(inserts[0][1]) == 2
    await storage.close()

def test_normalize_page_fills_defaults() -> None:
    record = normalize_page(
        {"url": "https://example.com/", "title": "Example", "images": ["/x.png"]},
        now=datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
    )
    assert list(record) == list(RECORD_FIELDS)
    assert "images" not in record
    assert record["text"] == ""
    assert record["links"] == []
    assert record["metadata"] == {}
    assert record["status_code"] == 0
    assert record["content_type"] == ""
    assert record["crawled_at"] == datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)

@pytest.mark.asyncio
async def test_json_storage_writes_standard_record(tmp_path: Path) -> None:
    path = tmp_path / "page.jsonl"
    fixed = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    async with JSONStorage(path, indent=None) as storage:
        await storage.save(
            {
                "url": "https://example.com/",
                "title": "Example",
                "text": "Hello",
                "links": ["https://example.com/a"],
                "metadata": {"description": "demo"},
                "crawled_at": fixed,
                "status_code": 200,
                "content_type": "text/html",
            }
        )
    loaded = json.loads(path.read_text(encoding="utf-8").strip())
    assert set(loaded) == set(RECORD_FIELDS)
    assert loaded["status_code"] == 200
    assert loaded["content_type"] == "text/html"
    assert loaded["crawled_at"].startswith("2026-11-10T12:00:00")