"""Offline tests for DataStorage backends."""

from __future__ import annotations

import csv
import json
from pathlib import Path

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

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_postgres_storage_inserts_and_closes() -> None:
    fake = FakeConnection()

    async def connect(dsn: str) -> FakeConnection:
        assert dsn.startswith("postgresql://")
        return fake

    storage = PostgresStorage(
        "postgresql://user:pass@localhost:5432/crawler",
        connect=connect,
    )
    await storage.save(PAGE)
    await storage.close()

    assert fake.closed is True
    creates = [q for q, _ in fake.statements if "CREATE TABLE" in q]
    inserts = [(q, a) for q, a in fake.statements if "INSERT INTO" in q]
    assert len(creates) == 1
    assert len(inserts) == 1
    query, args = inserts[0]
    assert "pages" in query
    assert args[0] == "https://example.com/"
    assert json.loads(args[1])["title"] == "Example"


def test_postgres_rejects_bad_table_name() -> None:
    with pytest.raises(StorageError):
        PostgresStorage("postgresql://localhost/crawler", table="pages;drop")