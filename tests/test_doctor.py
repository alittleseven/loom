"""doctor 体检测试。"""
from __future__ import annotations

from loom.core.doctor.doctor import run_doctor
from loom.core.repo.layout import init_book


def test_healthy_book(book):
    report = run_doctor(book.port)
    assert report.ok, report.lines()


def test_detects_unknown_config_field(book_root):
    book = init_book(book_root, genre="都市异能")
    book.port.write_text("book.yaml", "spec_version: loom-1\ngenre: 玄幻\nphantom_field: 1\n")
    report = run_doctor(book.port)
    check = next(c for c in report.checks if c.name == "book.yaml 未知字段")
    assert not check.ok and "phantom_field" in check.detail


def test_detects_orphan_entry(book):
    book.port.write_text("大纲/条目/伏笔/F-BROKEN.md", "---\nid: 错误\ntitle: x\n---\n")
    report = run_doctor(book.port)
    check = next(c for c in report.checks if c.name == "条目 orphan")
    assert not check.ok and "F-BROKEN" in check.detail


def test_detects_settle_interruption_with_repair_card(book):
    from loom.core.settle.transaction import FileOp, SettleInput, run

    run(book.port, SettleInput(
        message="ch(001)\n\n条目: +F-001\n",
        files=[FileOp("定稿/正文/ch0001.md", "---\nchapter: 1\ntitle: 灾\n---\n文\n")],
    ))
    # 模拟 settle 中断：把工作树文件改旧
    book.port.write_text("定稿/正文/ch0001.md", "旧内容（工作树落后于 HEAD）")
    report = run_doctor(book.port)
    check = next(c for c in report.checks if c.name == "工作树状态")
    assert not check.ok
    assert check.repair and "reset --hard" in check.repair


def test_workspace_scratch_not_flagged(book):
    book.port.write_text("工作区/草稿/ch0002.md", "写作中的暂存")
    report = run_doctor(book.port)
    assert report.ok, report.lines()
