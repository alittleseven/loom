"""settle 原子事务测试：哈希防串稿、只增不改、故障注入矩阵、run-ledger。"""
from __future__ import annotations

import hashlib

import pytest

from loom.core.settle.transaction import (
    FileOp,
    SettleInput,
    SettleRejected,
    recover,
    run,
)
from tests.conftest import manuscript_ops, settle_message
from tests.fakes import InMemoryRepoPort

FAULTS_PRE_REF = ("stage_blobs", "build_tree", "create_commit", "move_ref")


def _input(ch: int = 1, retcon: bool = False, reviewed_sha: str | None = None) -> SettleInput:
    return SettleInput(
        message=settle_message(ch, retcon=retcon),
        files=manuscript_ops(ch),
        draft_content=None if reviewed_sha is None else manuscript_ops(ch)[0].content,
        reviewed_sha256=reviewed_sha,
        chapter=ch,
    )


def test_settle_happy_path(book):
    result = run(book.port, _input(1))
    assert result.commit == book.port.head_commit()
    assert book.port.status_porcelain() == []
    text = book.port.read_text("定稿/正文/ch0001.md")
    assert "李浮舟" in text
    # 机器协议 message + 条目结转声明
    log = book.port._git.log("-1", "--format=%B")
    assert log.startswith("ch(001)") and "+F-001" in log
    # run-ledger 一行事件（A8：入 git）
    ledger = book.port.read_text("演化/run-ledger.jsonl")
    assert '"event": "settle"' in ledger and '"chapter": 1' in ledger


def test_settle_hash_guard_blocks_stale_draft(book):
    draft = manuscript_ops(1)[0].content
    wrong = hashlib.sha256(("旧审草稿" + draft).encode("utf-8")).hexdigest()
    with pytest.raises(SettleRejected, match="哈希防串稿"):
        run(book.port, _input(1, reviewed_sha=wrong))
    assert book.port.head_commit() is not None  # init 提交仍在
    assert book.port.status_porcelain() == []   # 仓库不脏
    assert not book.port.exists("定稿/正文/ch0001.md")


def test_settle_hash_guard_passes_on_match(book):
    draft = manuscript_ops(1)[0].content
    ok = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    run(book.port, _input(1, reviewed_sha=ok))
    assert book.port.exists("定稿/正文/ch0001.md")


def test_append_only_requires_retcon(book):
    run(book.port, _input(1))
    rewritten = SettleInput(
        message="ch(001)",  # 无 retcon 前缀
        files=[FileOp("定稿/正文/ch0001.md", "---\nchapter: 1\ntitle: 重写\n---\n新内容\n")],
    )
    with pytest.raises(SettleRejected, match="retcon"):
        run(book.port, rewritten)
    # 显式 retcon(N) 事务放行
    rewritten.message = "retcon(001)\n\n分析：受影响条目 F-001\n\n条目: ~F-001\n"
    rewritten.retcon = 1
    run(book.port, rewritten)
    assert "重写" in book.port.read_text("定稿/正文/ch0001.md")


def test_settle_rejects_dirty_worktree(book):
    book.port.write_text("大纲/总纲.md", "未提交的手改")
    with pytest.raises(SettleRejected, match="工作区不干净"):
        run(book.port, _input(1))


@pytest.mark.parametrize("point", FAULTS_PRE_REF)
def test_fault_injection_repo_stays_clean(book, point):
    from loom.core.ports import GitRepoPort

    port = GitRepoPort(book.port.root, fail_points=(point,))
    head_before = port._git.rev_parse("HEAD")
    with pytest.raises(Exception, match="fault injected"):
        run(port, _input(1))
    assert port.status_porcelain() == []          # 仓库不脏
    assert port._git.rev_parse("HEAD") == head_before  # HEAD 不变
    assert not port.exists("定稿/正文/ch0001.md")


def test_fault_after_ref_replay_recover(book):
    """sync_worktree 点 kill：ref 已前移、工作树未同步 → 重放恢复。"""
    from loom.core.ports import GitRepoPort

    port = GitRepoPort(book.port.root, fail_points=("sync_worktree",))
    with pytest.raises(Exception, match="fault injected"):
        run(port, _input(1))
    assert port.status_porcelain() != []          # 工作树落后（脏）
    assert port.exists("定稿/正文/ch0001.md") is False
    assert recover(port) is True                  # 重放：reset --hard HEAD
    assert port.status_porcelain() == []          # 恢复干净
    assert "李浮舟" in port.read_text("定稿/正文/ch0001.md")  # 内容已在


def test_inmemory_port_same_semantics():
    """RepoPort 替身与 git 实现同语义（接口可替换性验收）。"""
    port = InMemoryRepoPort()
    port.write_text("book.yaml", "spec_version: loom-1\ngenre: 都市异能\n")
    port.write_text("演化/run-ledger.jsonl", "")
    sha = port.commit_tree(
        {r: port.stage_blob(port.files[r]) for r in port.files},
        "init: loom-1 书仓初始化\n\n条目: -\n",
    )
    port.move_ref(sha)
    port.worktree_sync()
    result = run(port, _input(1))
    assert result.commit == port.head_commit()
    assert port.status_porcelain() == []
    assert '"event": "settle"' in port.read_text("演化/run-ledger.jsonl")
