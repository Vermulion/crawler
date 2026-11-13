"""Offline tests for DataStorage backends."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from crawler.storage import (
    CSVStorage,
    DataStorage,
    JSONStorage,
    PostgresStorage,
    RECORD_FIELDS,
    StorageError,
    normalize_page,
)


PAGE = {
    "url": "https://example.com/",
    "title": "Example",
    "text": "Hello",
    "links": ["https://example.com/a"],
    "metadata": {"description": "demo"},
}

FULL_PAGE = {
    **PAGE,
    "crawled_at": datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
    "status_code": 200,
    "content_type": "text/html",
    "images": ["/ignore.png"],
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


@pytest.mark.asyncio
async def test_json_buffers_until_close(tmp_path: Path) -> None:
    path = tmp_path / "buf.jsonl"
    storage = JSONStorage(path, indent=None, buffer_bytes=1_000_000)
    await storage.save(PAGE)
    assert not path.exists() or path.stat().st_size == 0
    await storage.close()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["title"] == "Example"


@pytest.mark.asyncio
async def test_json_flush_writes_without_close(tmp_path: Path) -> None:
    path = tmp_path / "buf.jsonl"
    storage = JSONStorage(path, indent=None, buffer_bytes=1_000_000)
    await storage.save(PAGE)
    assert not path.exists() or path.stat().st_size == 0
    await storage.flush()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["title"] == "Example"
    await storage.close()


class _FailingWriter:
    def __init__(self, fail_times: int = 1) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.written = ""

    async def write(self, blob: str) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise OSError("disk full")
        self.written += blob

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_json_keeps_buffer_if_write_fails() -> None:
    storage = JSONStorage("unused.jsonl", indent=None, buffer_bytes=1_000_000)
    writer = _FailingWriter(fail_times=1)
    storage._fh = writer
    await storage.save(PAGE)
    assert storage._chunks
    with pytest.raises(OSError, match="disk full"):
        await storage.flush()
    assert storage._chunks
    await storage.flush()
    assert storage._chunks == []
    assert json.loads(writer.written.strip())["title"] == "Example"
    await storage.close()


@pytest.mark.asyncio
async def test_csv_keeps_buffer_if_write_fails() -> None:
    storage = CSVStorage("unused.csv", buffer_bytes=1_000_000)
    writer = _FailingWriter(fail_times=1)
    storage._fh = writer
    storage.fieldnames = list(RECORD_FIELDS)
    storage._header_written = True
    await storage.save(PAGE)
    assert storage._chunks
    with pytest.raises(OSError, match="disk full"):
        await storage.flush()
    assert storage._chunks
    await storage.flush()
    assert storage._chunks == []
    assert "Example" in writer.written
    await storage.close()


class _FailOnceConnection(FakeConnection):
    def __init__(self) -> None:
        super().__init__()
        self.fail_times = 1

    async def executemany(self, query: str, rows: list) -> str:
        if self.fail_times:
            self.fail_times -= 1
            raise OSError("another operation is in progress")
        return await super().executemany(query, rows)


@pytest.mark.asyncio
async def test_postgres_keeps_buffer_if_executemany_fails() -> None:
    fake = _FailOnceConnection()
    storage = _pg(fake, batch_size=100)
    await storage.save(PAGE)
    assert storage._buffer
    with pytest.raises(OSError, match="another operation"):
        await storage.flush()
    assert storage._buffer
    await storage.flush()
    assert storage._buffer == []
    inserts = [(q, rows) for q, rows in fake.statements if "INSERT INTO" in q]
    assert len(inserts) == 1
    await storage.close()


@pytest.mark.asyncio
async def test_csv_flush_writes_without_close(tmp_path: Path) -> None:
    path = tmp_path / "buf.csv"
    storage = CSVStorage(path, buffer_bytes=1_000_000)
    await storage.save(PAGE)
    assert not path.exists() or path.stat().st_size == 0
    await storage.flush()
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["title"] == "Example"
    await storage.close()

@pytest.mark.asyncio
async def test_json_save_many_one_chunk(tmp_path: Path) -> None:
    path = tmp_path / "many.jsonl"
    async with JSONStorage(path, indent=None, buffer_bytes=1) as storage:
        await storage.save_many(
            [
                {"url": "https://a.test/", "title": "A"},
                {"url": "https://b.test/", "title": "B"},
            ]
        )
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_postgres_rejects_bad_table_name() -> None:
    with pytest.raises(StorageError):
        PostgresStorage("postgresql://localhost/crawler", table="pages;drop")


def _assert_standard_record(loaded: dict, *, csv_cells: bool = False) -> None:
    assert set(loaded) == set(RECORD_FIELDS)
    assert loaded["url"] == FULL_PAGE["url"]
    assert loaded["title"] == FULL_PAGE["title"]
    assert loaded["text"] == FULL_PAGE["text"]
    if csv_cells:
        assert json.loads(loaded["links"]) == FULL_PAGE["links"]
        assert json.loads(loaded["metadata"]) == FULL_PAGE["metadata"]
        assert int(loaded["status_code"]) == 200
        assert loaded["crawled_at"].startswith("2026-11-10T12:00:00")
    else:
        assert loaded["links"] == FULL_PAGE["links"]
        assert loaded["metadata"] == FULL_PAGE["metadata"]
        assert loaded["status_code"] == 200
        assert loaded["crawled_at"].startswith("2026-11-10T12:00:00")
    assert loaded["content_type"] == "text/html"
    assert "images" not in loaded


@pytest.mark.asyncio
async def test_json_csv_postgres_record_integrity(tmp_path: Path) -> None:
    json_path = tmp_path / "page.jsonl"
    csv_path = tmp_path / "page.csv"
    async with JSONStorage(json_path, indent=None) as json_storage:
        await json_storage.save(FULL_PAGE)
    async with CSVStorage(csv_path) as csv_storage:
        await csv_storage.save(FULL_PAGE)

    json_loaded = json.loads(json_path.read_text(encoding="utf-8").strip())
    _assert_standard_record(json_loaded)

    with csv_path.open(encoding="utf-8", newline="") as fh:
        csv_loaded = next(csv.DictReader(fh))
    _assert_standard_record(csv_loaded, csv_cells=True)

    fake = FakeConnection()
    pg = _pg(fake)
    await pg.save(FULL_PAGE)
    await pg.close()
    inserts = [(q, rows) for q, rows in fake.statements if "INSERT INTO" in q]
    _url, _title, payload = inserts[0][1][0]
    _assert_standard_record(json.loads(payload))