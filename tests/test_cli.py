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
