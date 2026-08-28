"""BookRepo 门面测试：配置、所有权矩阵、写锁、seam 嗅探。"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from loom.core.repo import lock as repo_lock
from loom.core.repo.frontmatter import dumps
from loom.core.repo.layout import BookFormatError, BookRepo
from loom.core.repo.ownership import OwnershipViolation
from loom.core.seam import SeamVersionMismatch, assert_seam
from tests.fakes import InMemoryRepoPort


def test_load_config_ok(book):
    cfg = book.load_config()
    assert cfg.spec_version == "loom-1" and cfg.genre == "都市异能"


def test_load_config_missing_fails_closed():
    port = InMemoryRepoPort()
    with pytest.raises(BookFormatError):
        BookRepo(port).load_config()


def test_load_config_wrong_spec_version():
    port = InMemoryRepoPort()
    port.write_text("book.yaml", "spec_version: other\ngenre: 玄幻\n")
    with pytest.raises(BookFormatError, match="spec_version"):
        BookRepo(port).load_config()


# ---- 写入所有权矩阵（M6）----

def test_ownership_matrix_denials(book):
    port = book.port
    with pytest.raises(OwnershipViolation):  # scribe 不得写正文
        book.write_file("定稿/正文/ch0001.md", "x", actor="scribe")
    with pytest.raises(OwnershipViolation):  # 作者不得写摘要
        book.write_file("定稿/摘要/ch0001.md", "x", actor="author")
    with pytest.raises(OwnershipViolation):  # signals 内核独占
        book.write_file("演化/signals.jsonl", "x", actor="author")
    with pytest.raises(OwnershipViolation):  # prep 只能写工作区
        book.write_file("大纲/卷纲/vol01.md", "x", actor="prep")
    assert not port.exists("定稿/正文/ch0001.md")  # 全部被拒，零写入


def test_ownership_allows_expected(book):
    book.write_file("工作区/决策卡/ch0001.md", "x", actor="prep")
    book.write_file("大纲/总纲.md", "x", actor="author")
    book.write_file("演化/signals.jsonl", '{"e":1}\n', actor="core")


# ---- 书仓写锁（N5）----

def _foreign_lock(book, pid: int) -> None:
    import json
    import time

    book.port.write_text(".loom/lock.json", json.dumps({"pid": pid, "started_at": time.time()}))


def test_author_write_blocked_by_live_foreign_lock(book):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _foreign_lock(book, child.pid)
        with pytest.raises(repo_lock.RepoBusy):
            book.write_file("大纲/总纲.md", "改", actor="author")
    finally:
        child.kill()
        child.wait()


def test_stale_lock_stolen(book):
    _foreign_lock(book, 999999)  # 不存在的 pid
    assert repo_lock.is_locked_by_other(book.port) is None
    book.write_file("大纲/总纲.md", "改", actor="author")  # stale 锁不阻塞
    repo_lock.acquire(book.port)  # 接管
    assert repo_lock.read_lock(book.port)["pid"] == os.getpid()
    repo_lock.release(book.port)
    assert not book.port.exists(".loom/lock.json")


# ---- seam 版本嗅探（§2.7）----

def test_seam_sniff():
    assert_seam({})
    assert_seam({"seam_version": "1"})
    with pytest.raises(SeamVersionMismatch):
        assert_seam({"seam_version": "999"})


def test_decision_card_written_with_seam(book):
    fm = {"spec_stage": "decision_card", "seam_version": "1", "chapter": 1,
          "generated_by": "author", "contract": [], "options": []}
    rel = "工作区/决策卡/ch0001.md"
    book.write_file(rel, dumps(fm, "## 盘面\n"), actor="author")
    fm2, _ = book.read_fm(rel)
    assert_seam(fm2)  # 不抛
