"""盲测金标准集执行器测试（路由事实源；匿名化；永不作 fitness）。"""
from __future__ import annotations

import json

import pytest

from loom.core.repo.layout import init_book
from loom.edge.client.protocol import FakeLLMProvider
from loom.evolve.bench import (
    BLINDSET_REL,
    build_routing_table,
    load_samples,
    run_blindset,
    seed_samples,
)

_SAMPLES = [
    {"sid": "s01", "scene": "打斗", "emotion": "strong", "context": "雨夜天台。", "instruction": "写一段近身打斗。"},
    {"sid": "s02", "scene": "打斗", "emotion": "weak", "context": "废弃厂房。", "instruction": "写一段试探性交手。"},
    {"sid": "s03", "scene": "日常", "emotion": "weak", "context": "早餐摊。", "instruction": "写一段师徒日常。"},
]


def _book(tmp_path):
    return init_book(tmp_path / "盲测书", genre="都市异能")


def test_seed_and_load(book):
    seed_samples(book, _SAMPLES)
    samples = load_samples(book)
    assert [s.sid for s in samples] == ["s01", "s02", "s03"]
    assert json.loads(book.port.read_text(f"{BLINDSET_REL}/samples.json"))["version"] == "v1"


def test_run_blindset_anonymized(book):
    seed_samples(book, _SAMPLES)
    pa = FakeLLMProvider(scripts={"blindset": "A 的续写。"}, model="真实模型甲")
    pb = FakeLLMProvider(scripts={"blindset": "B 的续写。"}, model="真实模型乙")
    run_dir = run_blindset(book, {"A": pa, "B": pb})
    assert book.port.exists(f"{run_dir}/A/s01.md")
    assert book.port.read_text(f"{run_dir}/B/s03.md") == "B 的续写。"
    key = json.loads(book.port.read_text(f"{run_dir}/blinding_key.json"))
    assert key["aliases"]["A"] == "真实模型甲"  # key 单独存放，盲排期间不看


def test_routing_table(book):
    seed_samples(book, _SAMPLES)
    run_dir = str(run_blindset(book, {"A": FakeLLMProvider(scripts={"blindset": "x"}, model="mA"),
                                      "B": FakeLLMProvider(scripts={"blindset": "y"}, model="mB")}))
    ranks = "sid,rank_A,rank_B\ns01,1,2\ns02,2,1\ns03,1,2\n"
    table = build_routing_table(book, run_dir, ranks)
    assert table["wins"]["A"] == 2 and table["wins"]["B"] == 1
    assert table["winner_overall"] == "A"
    assert table["wins_by_scene"]["打斗"] == {"A": 1, "B": 1}
    assert json.loads(book.port.read_text(f"{run_dir}/routing_table.json"))["winner_overall"] == "A"


def test_missing_blindset_raises(book):
    with pytest.raises(FileNotFoundError):
        load_samples(book)
