"""v6→loom-1 迁移器测试（源只读/失败零残留/映射单列验收/doctor 零孤儿）。"""
from __future__ import annotations

import pytest

from loom.core.doctor.doctor import run_doctor
from loom.core.migrate.v6 import migrate
from loom.core.repo.layout import init_book


@pytest.fixture
def v6_src(tmp_path):
    src = tmp_path / "v6书"
    (src / "正文").mkdir(parents=True)
    (src / "设定集").mkdir()
    (src / "大纲").mkdir()
    (src / "正文" / "第0001章-天裂.md").write_text(
        "# 第1章 天裂\n\n凌晨五点半，苏小白从便利店后门出来。\n", encoding="utf-8")
    (src / "正文" / "第0002章-想活.md").write_text(
        "# 第2章 想活\n\n他抬头看了一眼，天是灰蓝色的。\n", encoding="utf-8")
    (src / "正文" / "乱名的文件.md").write_text("# x\n\n内容\n", encoding="utf-8")
    (src / "设定集" / "主角卡.md").write_text(
        "# 主角卡\n\n## 基本信息\n- 姓名：苏小白\n- 身份：便利店夜班店员\n", encoding="utf-8")
    (src / "大纲" / "总纲.md").write_text("# 总纲\n\n末世吃灾求生。\n", encoding="utf-8")
    (src / "大纲" / "第1卷-详细大纲.md").write_text("# 卷一\n\n废墟求生。\n", encoding="utf-8")
    (src / "大纲" / "第1卷-节拍表.md").write_text(
        "# 节拍表\n\n| 1 | 妖物潮首波，埋下天裂之谜的伏笔 |\n"
        "| 2 | 熊哥营地冲突，铺垫庇护所矛盾 |\n", encoding="utf-8")
    return src


def test_migrate_full(tmp_path, v6_src):
    target = tmp_path / "loom书"
    report = migrate(v6_src, target, genre="末世求生")
    assert report.chapters == 2
    assert report.settings == 1 and report.entries == 2
    # 迁移产物结构
    book_text = (target / "定稿" / "正文" / "ch0001.md").read_text(encoding="utf-8")
    assert "spec_stage: manuscript" in book_text and "migrated_from: v6" in book_text
    assert "苏小白从便利店后门出来" in book_text
    # 待校对清单落盘
    todo = (target / "迁移待校对清单.md").read_text(encoding="utf-8")
    assert "待校对" in todo
    # git 历史两次提交，仓库干净
    assert (target / ".git").exists()
    # doctor：迁移产物零孤儿（tentative 条目 schema 合法）
    from loom.core.ports import GitRepoPort

    dr = run_doctor(GitRepoPort(target))
    orphan = next(c for c in dr.checks if c.name == "条目 orphan")
    assert orphan.ok, orphan.detail


def test_source_readonly(tmp_path, v6_src):
    """源目录全程只读：迁移后源文件内容与 mtime 均不变。"""
    target = tmp_path / "loom书"
    before = {p: (p.read_bytes(), p.stat().st_mtime) for p in v6_src.rglob("*") if p.is_file()}
    migrate(v6_src, target, genre="末世求生")
    after = {p: (p.read_bytes(), p.stat().st_mtime) for p in v6_src.rglob("*") if p.is_file()}
    assert before == after


def test_migrate_refuses_existing_book(tmp_path, v6_src):
    target = tmp_path / "已有书"
    init_book(target, genre="末世求生")
    with pytest.raises(FileExistsError):
        migrate(v6_src, target, genre="末世求生")


def test_dry_run(tmp_path, v6_src):
    report = migrate(v6_src, tmp_path / "nowhere", genre="x", dry_run=True)
    assert report.chapters == 2
    assert not (tmp_path / "nowhere").exists()
