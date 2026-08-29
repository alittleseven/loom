"""CLI smoke：init / doctor 全流程。"""
from __future__ import annotations

import pytest

from loom.cli import main


def test_init_and_doctor(tmp_path, capsys):
    target = tmp_path / "新书"
    with pytest.raises(SystemExit) as e:
        main(["init", str(target), "--genre", "都市异能"])
    assert e.value.code == 0
    assert (target / "book.yaml").exists()
    assert (target / "定稿/正文").exists()

    with pytest.raises(SystemExit) as e:
        main(["doctor", str(target)])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "健康" in out


def test_doctor_fails_on_broken_book(tmp_path, capsys):
    target = tmp_path / "坏书"
    main_init = pytest.raises(SystemExit)
    with main_init:
        main(["init", str(target), "--genre", "玄幻"])
    (target / "book.yaml").unlink()
    with pytest.raises(SystemExit) as e:
        main(["doctor", str(target)])
    assert e.value.code == 1
    assert "book.yaml" in capsys.readouterr().out


def test_cli_review_volsummary_golden_enhance(tmp_path, monkeypatch, capsys):
    """审阅报告 四.2：不可达功能补 CLI 入口（review/golden/volsummary/enhance）。"""
    from loom.core.repo.frontmatter import split
    from loom.pipeline import run_chapter
    from tests.test_pipeline import _CARD, _long_draft, _provider, _seed

    book = _seed(tmp_path)
    port = book.port
    run_chapter(book, _provider(), _CARD, contract=["含:李浮舟"])
    monkeypatch.setattr("loom.cli._make_provider",
                        lambda root: _provider(vol_summary={"summary": "卷一：李浮舟购船试灾。"}))

    # review：双审定稿，无阻断 → 0
    with pytest.raises(SystemExit) as e:
        main(["review", str(port.root), "--chapter", "1"])
    assert e.value.code == 0
    assert "通过" in capsys.readouterr().out

    # volsummary：章摘要合成卷摘要并落库
    with pytest.raises(SystemExit) as e:
        main(["volsummary", str(port.root), "--vol", "1", "--start", "1", "--end", "1"])
    assert e.value.code == 0
    assert port.exists("定稿/卷摘要/vol01.md")

    # enhance：bookmap 输出；synth 无 --yes 拒绝
    with pytest.raises(SystemExit) as e:
        main(["enhance", str(port.root), "bookmap", "--chapter", "1"])
    assert e.value.code == 0
    assert "Book Map" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        main(["enhance", str(port.root), "synth"])
    assert e.value.code == 1

    # golden harvest：分类脚本判非金句 → 0 条入库（闭环路径打通）
    final = tmp_path / "改稿.md"
    final.write_text("完全不同的新段落，长度足够触发扫描判断。" * 10, encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["golden", str(port.root), "harvest", "--chapter", "1", "--final", str(final)])
    assert e.value.code == 0
    assert "0 条" in capsys.readouterr().out

    # golden harvest 命中候选 → scribe(chN) settle 落库，工作区保持干净（第二轮 P1-2）
    monkeypatch.setattr("loom.cli._make_provider",
                        lambda root: _provider(golden={"golden": True, "scene": "渡口", "reason": "x"}))
    final2 = tmp_path / "改稿2.md"
    final2.write_text(_long_draft() + "\n全新增补的段落：雪落在城墙上，守夜人换了三次灯芯，桥头的狗叫了很久。\n",
                      encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["golden", str(port.root), "harvest", "--chapter", "1", "--final", str(final2)])
    assert e.value.code == 0
    assert "1 条" in capsys.readouterr().out
    fm, _ = split(port.read_text("文风/金句库/渡口.md"))
    assert fm["lines"][0]["status"] == "tentative"
    assert port.status_porcelain() == []                      # 收割已入 settle 事务
    assert "scribe(001)" in port._git.log("-1", "--format=%B")

    # golden confirm：tentative → active（fix(手改) settle 事务，工作区保持干净）
    with pytest.raises(SystemExit) as e:
        main(["golden", str(port.root), "confirm", "--scene", "渡口", "--index", "0"])
    assert e.value.code == 0
    fm, _ = split(port.read_text("文风/金句库/渡口.md"))
    assert fm["lines"][0]["status"] == "active"
    assert port.status_porcelain() == []
    # 重复确认（已 active）→ 退出码 1
    with pytest.raises(SystemExit) as e:
        main(["golden", str(port.root), "confirm", "--scene", "渡口", "--index", "0"])
    assert e.value.code == 1


def test_cli_friendly_error_on_halt(tmp_path, monkeypatch, capsys):
    """第二轮审阅 P2-4：域异常输出可读结论 + 退出码 1，不裸抛 traceback。"""
    from tests.test_pipeline import _provider, _seed

    book = _seed(tmp_path)
    monkeypatch.setattr("loom.cli._make_provider",
                        lambda root: _provider(manuscript="他顿悟了，系统提示响起。一切平静结束。"))
    with pytest.raises(SystemExit) as e:
        main(["next", str(book.port.root), "--chapter", "1"])
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "机检重试耗尽" in err and "Traceback" not in err
