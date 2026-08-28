"""prep 编译器测试：确定性快照（N4 硬验收——同书同章重编译 pack 字节一致）。"""
from __future__ import annotations

from loom.core.prep.prep import BUDGET_DEFAULT, compile_pack, estimate_tokens
from loom.core.repo.frontmatter import dumps
from loom.core.repo.layout import init_book
from loom.core.repo.schema import ChapterCardFM


def _seed_book(tmp_path):
    book = init_book(tmp_path / "prep书", genre="都市异能")
    port = book.port
    port.write_text("定稿/设定/名册/李浮舟.md", dumps(
        {"id": "set-mc", "family": "名册", "name": "李浮舟", "status": "active",
         "triggers": ["李浮舟", "浮舟"]}, "主角，能『借灾』。\n"))
    port.write_text("定稿/设定/名册/陈阿婆.md", dumps(
        {"id": "set-npc", "family": "名册", "name": "陈阿婆", "status": "active",
         "triggers": ["陈阿婆"]}, "渡口船家的母亲。\n"))
    port.write_text("定稿/设定/名册/王铁匠.md", dumps(
        {"id": "set-smith", "family": "名册", "name": "王铁匠", "status": "active",
         "triggers": ["王铁匠"]}, "铁匠铺老板。\n"))
    port.write_text("定稿/设定/信息差/身世.md", dumps(
        {"id": "set-sec", "family": "信息差", "status": "active",
         "visibility": "hidden", "secret_keywords": ["魔神转世"]}, ""))
    port.write_text("大纲/条目/伏笔/F-001.md", dumps(
        {"id": "F-001", "kind": "伏笔", "strength": "high", "status": "active",
         "opened_ch": 1, "due_ch": 16}, "渡口的旧船有来历。\n"))
    port.write_text("大纲/卷纲/vol01.md", dumps(
        {"spec_stage": "plan", "vol": 1, "climax_chapters": [5, 20],
         "entry_plan": [{"id": "F-001", "action": "开启", "due_chapter": 16}],
         "time_span": {"start": "元启三年春", "end": "元启三年夏"},
         "chapter_types": {f"ch{i:04d}": "main" for i in range(1, 9)},
         "rhythm": {"entry_density": [2, 4], "climax_gap": 8, "deadline_margin": 5},
         "waivers": []}, "# 卷一\n"))
    port.write_text("定稿/摘要/ch0001.md", dumps({"chapter": 1, "word_count": 3000},
                                                 "李浮舟在渡口初试借灾。\n"))
    port.write_text("文风/金句库/渡口.md", dumps(
        {"scene": "渡口", "lines": [
            {"text": "水声像谁在底下数着银子。", "status": "active", "source_ch": 1},
            {"text": " tentative 未确认句", "status": "tentative", "source_ch": 1}]}, ""))
    return book


_CARD = ChapterCardFM(spec_stage="chapter_card", chapter=2, touches=["F-001"], scenes=2,
                      hook_type="cliff", time_anchor="元启三年春", word_tier="standard")


def test_snapshot_deterministic(tmp_path):
    """同书同章重编译 pack 字节一致——'上下文是编译出来的'的可测试形态。"""
    book1 = _seed_book(tmp_path / "a")
    pack1 = compile_pack(book1, 2, _CARD, contract=["含:李浮舟"])
    book2 = _seed_book(tmp_path / "b")  # 重建一份内容相同的书仓
    pack2 = compile_pack(book2, 2, _CARD, contract=["含:李浮舟"])
    assert pack1.text == pack2.text
    assert pack1.slots == pack2.slots
    # 同仓重复编译
    assert compile_pack(book1, 2, _CARD, contract=["含:李浮舟"]).text == pack1.text


def test_trigger_injection_and_info_gap(tmp_path):
    book = _seed_book(tmp_path)
    pack = compile_pack(book, 2, _CARD, contract=["含:李浮舟", "含:陈阿婆"])
    assert "李浮舟" in pack.slots["facts"] and "借灾" in pack.slots["facts"]
    assert "陈阿婆" in pack.slots["facts"]  # 合同点名 → 命中触发器注入
    assert "王铁匠" not in pack.text         # 全书未提及本章 → 不注入
    assert "魔神转世" not in pack.text       # 信息差永不进包


def test_golden_lines_active_only_and_budget(tmp_path):
    book = _seed_book(tmp_path)
    pack = compile_pack(book, 2, _CARD, scenario="渡口")
    assert "水声像谁在底下数着银子。" in pack.slots["style"]
    assert "tentative 未确认句" not in pack.slots["style"]
    assert pack.tokens <= BUDGET_DEFAULT


def test_budget_truncation(tmp_path):
    book = _seed_book(tmp_path)
    pack = compile_pack(book, 2, _CARD, budget=60)
    assert pack.tokens <= 60 or "预算截断" in pack.text


def test_estimate_tokens():
    assert estimate_tokens("四个汉字") == 6
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("") == 0
