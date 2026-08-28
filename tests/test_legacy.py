"""legacy 零件测试：合同引擎（含占位符拒绝 N2）+ CSV 检索（BM25/CJK bigram）。"""
from __future__ import annotations

import pytest

from loom.core.legacy.contract import (
    ContractPlaceholderError,
    evaluate,
    parse_assertion,
    summary,
)
from loom.core.legacy.csv_retrieval import KnowledgeTable, tokenize


def test_parse_kinds():
    assert parse_assertion("含:李浮舟").kind == "contain"
    assert parse_assertion("禁:圣母").kind == "forbid"
    assert parse_assertion("字数:2600-3600").value == (2600, 3600)
    assert parse_assertion(" plain text").kind == "contain"


@pytest.mark.parametrize("bad", ["{章纲目标}", "占位符", "含:{x}", "字数:99-10", ""])
def test_placeholder_rejected(bad):
    with pytest.raises(ContractPlaceholderError):
        parse_assertion(bad)


def test_evaluate():
    draft = "李浮舟吞下灾厄，眼底闪过一丝红光。"
    items = evaluate(draft, ["含:李浮舟，灾厄", "禁:圣母", "字数:10-100", "含:未出现词"])
    s = summary(items)
    assert s["missed"] == ["含:未出现词"]
    assert s["covered"] == ["含:李浮舟，灾厄", "禁:圣母", "字数:10-100"]


def test_tokenize_cjk_bigram():
    toks = tokenize("借灾hd")
    assert "借" in toks and "借灾" in toks and "hd" in toks


def test_bm25_search(tmp_path):
    p = tmp_path / "知识表.csv"
    p.write_text(
        "id,标题,正文\n"
        "1,金手指觉醒,主角第一次使用金手指时要有代价感不能太顺\n"
        "2,打脸节奏,打脸前先抑后扬对手要嚣张三行\n"
        "3,感情线推进,感情线推进要靠事件不能靠内心独白\n",
        encoding="utf-8",
    )
    table = KnowledgeTable.load_csv(p)
    hits = table.search("金手指使用代价")
    assert hits and hits[0][0]["id"] == "1"
    hits2 = table.search("打脸嚣张")
    assert hits2 and hits2[0][0]["id"] == "2"
