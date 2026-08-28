"""cache 可删重建测试（N4：删除后由源文件全量重建，查询一致是硬验收）。"""
from __future__ import annotations

import pytest

from loom.core.cache import EntryIndex
from loom.core.repo.frontmatter import dumps


@pytest.fixture
def entries(book):
    port = book.port
    port.write_text(
        "大纲/条目/伏笔/F-001.md",
        dumps({"id": "F-001", "kind": "伏笔", "strength": "high", "status": "active",
               "opened_ch": 1, "due_ch": 16}, "伏笔内容\n"),
    )
    port.write_text(
        "大纲/条目/感情线/R-001.md",
        dumps({"id": "R-001", "kind": "感情线", "strength": "mid", "status": "tentative",
               "opened_ch": 2}, "感情线内容\n"),
    )
    port.write_text(
        "定稿/设定/名册/李浮舟.md",
        dumps({"id": "set-ming-ce-001", "family": "名册", "name": "李浮舟",
               "status": "active", "triggers": ["李浮舟", "浮舟"]}, "主角。\n"),
    )
    return book


def _snapshot(idx: EntryIndex) -> dict:
    data = {"all": {}}
    for row in idx._db.execute("SELECT id, kind, status, path, content_hash FROM entries ORDER BY id"):
        data["all"][row[0]] = row[1:]
    return data


def test_rebuild_and_query(entries):
    idx = EntryIndex(entries.port.root)
    assert idx.rebuild(entries.port) == 3
    got = idx.get("F-001")
    assert got["status"] == "active" and got["kind"] == "伏笔"
    assert idx.get("set-ming-ce-001")["path"].startswith("定稿/设定/")
    assert [r["id"] for r in idx.by_kind("伏笔")] == ["F-001"]
    idx.close()


def test_delete_and_rebuild_consistent(entries):
    idx = EntryIndex(entries.port.root)
    idx.rebuild(entries.port)
    before = _snapshot(idx)
    idx.close()

    EntryIndex.destroy(entries.port.root)  # 删除 .cache/index.db
    idx2 = EntryIndex(entries.port.root)
    idx2.rebuild(entries.port)
    after = _snapshot(idx2)
    idx2.close()
    assert before == after  # 重建结果与原查询一致（硬验收）


def test_wal_and_busy_timeout(entries):
    idx = EntryIndex(entries.port.root)
    assert idx._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert idx._db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    idx.close()


def test_broken_file_skipped(entries):
    entries.port.write_text("大纲/条目/伏笔/F-099.md", "---\nid: F-999\nkind: 伏笔\n---\n")  # id/kind 矛盾
    idx = EntryIndex(entries.port.root)
    assert idx.rebuild(entries.port) == 3  # 非法文件不入索引（doctor 负责 orphan 报告）
    idx.close()
