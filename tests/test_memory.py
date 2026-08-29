"""memory：记忆四态迁移矩阵 fail-closed / list 过滤 / settle 落库与审计链。"""
from __future__ import annotations

import pytest

from loom.core.ledger.ledger import read_ledger
from loom.core.memory import (
    MemoryTransitionError,
    list_entries,
    set_status,
)
from loom.core.repo.frontmatter import dumps, split


def _seed_entry(book, rel: str, fm: dict, body: str = "内容\n") -> None:
    """种子条目走 settle 落库，保持工作区干净（settle 拒绝脏工作区）。"""
    from loom.core.settle.transaction import FileOp, SettleInput
    from loom.core.settle.transaction import run as settle_run

    settle_run(book.port, SettleInput(
        message=f"fix(手改)\n\n种子条目 {rel}\n\n条目: -\n",
        files=[FileOp(rel, dumps(fm, body), actor="author")],
    ))


def test_list_filters_by_status(book):
    _seed_entry(book, "定稿/记忆/set-mem-a.md",
                {"id": "set-mem-a", "status": "tentative"})
    _seed_entry(book, "定稿/设定/世界观/set-w-b.md",
                {"id": "set-w-b", "family": "世界观", "status": "active"})
    assert [e.label for e in list_entries(book)] == ["set-mem-a", "set-w-b"]
    assert [e.label for e in list_entries(book, status="tentative")] == ["set-mem-a"]


def test_list_skips_files_without_status(book):
    _seed_entry(book, "定稿/记忆/备忘.md", {"note": "无 status 字段"})
    assert list_entries(book) == []


def test_set_legal_transition_settles(book):
    _seed_entry(book, "定稿/记忆/set-mem-a.md",
                {"id": "set-mem-a", "status": "tentative"})
    commit = set_status(book, "set-mem-a", "active", reason="人审通过")
    assert len(commit) == 40
    fm, _body = split(book.port.read_text("定稿/记忆/set-mem-a.md"))
    assert fm["status"] == "active"
    assert book.port.status_porcelain() == []  # 工作区干净
    transitions = [e for e in read_ledger(book) if e.get("event") == "memory_transition"]
    assert transitions == [{"event": "memory_transition",
                            "id": "set-mem-a", "rel": "定稿/记忆/set-mem-a.md",
                            "from": "tentative", "to": "active", "reason": "人审通过"}]


def test_set_by_rel_path_and_revival(book):
    _seed_entry(book, "定稿/设定/世界观/set-w-b.md",
                {"id": "set-w-b", "family": "世界观", "status": "active"})
    set_status(book, "定稿/设定/世界观/set-w-b.md", "outdated", reason="被新设定取代")
    set_status(book, "set-w-b", "active", reason="复活")  # outdated → active
    fm, _ = split(book.port.read_text("定稿/设定/世界观/set-w-b.md"))
    assert fm["status"] == "active"


def test_set_illegal_transition_rejected(book):
    _seed_entry(book, "定稿/记忆/set-mem-a.md",
                {"id": "set-mem-a", "status": "active"})
    with pytest.raises(MemoryTransitionError, match="非法迁移"):
        set_status(book, "set-mem-a", "tentative", reason="r")  # active → tentative 不允许
    assert book.port.status_porcelain() == []
    fm, _ = split(book.port.read_text("定稿/记忆/set-mem-a.md"))
    assert fm["status"] == "active"  # 原样保留


def test_set_contradicted_requires_re_review(book):
    """矛盾不入库红线：contradicted 只能回 tentative 重走人审，不得直接 active。"""
    _seed_entry(book, "定稿/记忆/set-mem-a.md",
                {"id": "set-mem-a", "status": "contradicted"})
    with pytest.raises(MemoryTransitionError, match="非法迁移"):
        set_status(book, "set-mem-a", "active", reason="r")
    set_status(book, "set-mem-a", "tentative", reason="矛盾已处置，重起")
    fm, _ = split(book.port.read_text("定稿/记忆/set-mem-a.md"))
    assert fm["status"] == "tentative"


def test_set_unknown_entry_and_missing_reason(book):
    _seed_entry(book, "定稿/记忆/set-mem-a.md",
                {"id": "set-mem-a", "status": "tentative"})
    with pytest.raises(MemoryTransitionError, match="未知条目"):
        set_status(book, "set-nope", "active", reason="r")
    with pytest.raises(MemoryTransitionError, match="reason"):
        set_status(book, "set-mem-a", "active", reason="  ")
