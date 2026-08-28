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
    from loom.core.repo.frontmatter import dumps, split
    from loom.pipeline import run_chapter
    from tests.test_pipeline import _CARD, _provider, _seed

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

    # golden confirm：tentative → active
    port.write_text("文风/金句库/渡口.md", dumps(
        {"scene": "渡口", "lines": [{"text": "水声像谁在底下数着银子。",
                                     "status": "tentative", "source_ch": 1}]}, ""))
    with pytest.raises(SystemExit) as e:
        main(["golden", str(port.root), "confirm", "--scene", "渡口", "--index", "0"])
    assert e.value.code == 0
    fm, _ = split(port.read_text("文风/金句库/渡口.md"))
    assert fm["lines"][0]["status"] == "active"
    # 重复确认（已 active）→ 退出码 1
    with pytest.raises(SystemExit) as e:
        main(["golden", str(port.root), "confirm", "--scene", "渡口", "--index", "0"])
    assert e.value.code == 1
