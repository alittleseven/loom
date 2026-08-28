"""机检十项 + plan_gates 六道测试（表驱动：每项检查一个违例场景 + 通过场景）。"""
from __future__ import annotations

import pytest

from loom.core.checks.checks import (
    ChapterContext,
    check_banned_patterns,
    check_banned_words,
    check_entry_form,
    check_fulfillment,
    check_leak,
    check_ngram_repetition,
    check_no_hook,
    check_proper_nouns,
    check_timeline,
    check_word_count,
    load_entries,
    run_checks,
    run_plan_gates,
)
from loom.core.repo.frontmatter import dumps
from loom.core.repo.schema import (
    EntryFM,
    GenreProfileFM,
    ManuscriptFM,
    VolOutlineFM,
)


@pytest.fixture
def rich_book(book):
    """装载名册/信息差/时间线/条目/风格宪法的书仓。"""
    port = book.port
    port.write_text("文风/风格宪法.md", dumps(
        {"banned_words": ["顿悟", "系统提示"], "banned_patterns": ["瞬间爆{1,3}发"], "catchphrases": []}, ""))
    port.write_text("定稿/设定/名册/李浮舟.md", dumps(
        {"id": "set-mc", "family": "名册", "name": "李浮舟", "status": "active",
         "triggers": ["李浮舟", "浮舟"]}, ""))
    port.write_text("定稿/设定/信息差/身世.md", dumps(
        {"id": "set-secret", "family": "信息差", "status": "active",
         "visibility": "revealed@10", "secret_keywords": ["魔神转世"]}, ""))
    port.write_text("定稿/设定/时间线/t1.md", dumps(
        {"id": "set-tl-1", "family": "时间线", "status": "active", "ch": 1,
         "book_time": "元启三年春", "event": "开局", "present": ["李浮舟"]}, ""))
    port.write_text("定稿/设定/时间线/t2.md", dumps(
        {"id": "set-tl-2", "family": "时间线", "status": "active", "ch": 2,
         "book_time": "元启三年夏", "event": "离村", "present": ["李浮舟"]}, ""))
    port.write_text("定稿/设定/时间线/t3.md", dumps(
        {"id": "set-tl-3", "family": "时间线", "status": "active", "ch": 3,
         "book_time": "元启三年秋", "event": "入城", "present": ["李浮舟"]}, ""))
    port.write_text("大纲/条目/伏笔/F-001.md", dumps(
        {"id": "F-001", "kind": "伏笔", "strength": "high", "status": "active",
         "opened_ch": 1, "due_ch": 16}, ""))
    return book


def _ctx(chapter=2, draft="正文。就在这时，李浮舟出手了！", anchor="元启三年夏",
         touches=("F-001",), contract=None, tier="standard", wc=3000, card=None):
    ms = ManuscriptFM(spec_stage="manuscript", chapter=chapter, title="章",
                      time_anchor=anchor,
                      entry_changes=[{"id": t, "action": "~"} for t in touches],
                      contract_digest=[], word_count=wc)
    return ChapterContext(chapter=chapter, draft=draft, manuscript=ms,
                          card=card, contract=contract or [])


def _entry_book_with_vol(rich_book, vol_fm_extra=None, chapter_types=None):
    port = rich_book.port
    vol = dict(spec_stage="plan", vol=1, climax_chapters=[5, 20],
               entry_plan=[{"id": "F-001", "action": "兑付", "due_chapter": 10}],
               time_span={"start": "元启三年春", "end": "元启三年夏"},
               chapter_types=chapter_types or {f"ch{i:04d}": "main" for i in range(1, 9)},
               rhythm={"entry_density": [1, 4], "climax_gap": 20, "deadline_margin": 5},
               waivers=[])
    vol.update(vol_fm_extra or {})
    port.write_text("大纲/卷纲/vol01.md", dumps(vol, "# 卷一\n"))
    return rich_book


# ---- 逐项检查 ----

def test_banned_words(rich_book):
    issues = check_banned_words("他顿悟了", {"banned_words": ["顿悟"]})
    assert issues and issues[0].level == "block"
    assert check_banned_words("正常文字", {"banned_words": ["顿悟"]}) == []


def test_banned_pattern_regex(rich_book):
    assert check_banned_patterns("力量瞬间爆发", {"banned_patterns": ["瞬间爆{1,3}发"]})
    assert not check_banned_patterns("正常", {"banned_patterns": ["瞬间爆{1,3}发"]})


def test_leak_scan(rich_book):
    # 第 2 章：revealed@10 尚未揭示 → 提到"魔神转世"即泄密
    assert check_leak(rich_book, 2, "他想起自己竟是魔神转世。")
    assert not check_leak(rich_book, 10, "魔神转世早已公开。")  # 已揭示章
    assert not check_leak(rich_book, 2, "普通叙述。")


def test_proper_noun_drift(rich_book):
    assert check_proper_nouns(rich_book, "李浮看着远处。")   # 未登记变体且全名未出现
    assert not check_proper_nouns(rich_book, "李浮舟看着远处。")


def test_fulfillment():
    issues, s = check_fulfillment("有灾厄在场", ["含:灾厄", "含:不存在的词"])
    assert len(issues) == 1 and s["missed"] == ["含:不存在的词"] and s["covered"] == ["含:灾厄"]


def test_timeline_monotonic(rich_book):
    # ch4 锚点回到 春（序 0 < 秋 序 2）→ block（时间回退）
    assert any(i.level == "block" for i in check_timeline(rich_book, 4, "元启三年春"))
    # ch4 停留在 秋 → 合法
    assert not check_timeline(rich_book, 4, "元启三年秋")
    # 同锚停留合法（ch2 停留 ch1 的 春）
    assert not [i for i in check_timeline(rich_book, 2, "元启三年春") if i.level == "block"]
    # 未登记锚点 → warn
    assert any(i.level == "warn" for i in check_timeline(rich_book, 2, "未登记锚"))


def test_word_count_tiers():
    assert check_word_count("standard", 200)
    assert not check_word_count("standard", 3000)
    assert not check_word_count("climax", 4000)
    assert check_word_count("climax", 3000)


def test_ngram_repetition():
    good = "李浮舟踏出山门，山门外风雪未歇，他裹紧了旧棉袍往渡口走去。渡口的船家认得他，招了招手便撑篙离岸，留下他站在原地等着下一班船。"
    assert not check_ngram_repetition(good)
    bad = "他走了过去他走了过去他走了过去他走了过去他走了过去他走了过去他走了过去他走了过去。"
    assert check_ngram_repetition(bad)


def test_entry_form(rich_book):
    entries = load_entries(rich_book)
    ok_ctx = _ctx(touches=("F-001",))
    assert not check_entry_form(rich_book, ok_ctx, entries)
    missing = _ctx(touches=())
    assert any("未 touch" in i.msg for i in check_entry_form(rich_book, missing, entries))
    gone = _ctx(touches=("F-999",))
    assert any("不存在" in i.msg for i in check_entry_form(rich_book, gone, entries))


def test_no_hook():
    assert check_no_hook("平淡收尾，无事发生。")
    assert not check_no_hook("长长长" * 100 + "就在这时，门外传来敲门声！")


def test_run_checks_full_pipeline(rich_book):
    clean = _ctx(draft="元启三年夏，李浮舟离村。就在这时，身后传来一声呼唤！")
    assert run_checks(rich_book, clean) == []
    dirty = _ctx(draft="他顿悟了，想起魔神转世。他走了过去他走了过去他走了过去他走了过去他走了过去他走了过去他走了过去他走了过去。",
                 contract=["含:不存在的词"], wc=9999, touches=())
    kinds = {i.rule for i in run_checks(rich_book, dirty)}
    assert {"banned_word", "leak", "fulfillment", "word_count", "ngram", "entry_form"} <= kinds


# ---- plan_gates 六道 ----

def _profile():
    return GenreProfileFM(spec_stage="genre_profile", genre="测试", entry_density=(1, 4),
                          climax_gap=20, deadline_margin=5,
                          ratio_redlines={"main": (0.55, 0.85), "romance": (0.1, 0.35), "side": (0.0, 0.3)})


def _vol(**extra):
    base = dict(spec_stage="plan", vol=1, climax_chapters=[5, 20],
                entry_plan=[{"id": "F-001", "action": "开启", "due_chapter": 16}],
                time_span={"start": "元启三年春", "end": "元启三年夏"},
                chapter_types={**{f"ch{i:04d}": "main" for i in range(1, 7)},
                               "ch0007": "romance", "ch0008": "side"},
                rhythm={"entry_density": [1, 4], "climax_gap": 20, "deadline_margin": 5},
                waivers=[])
    base.update(extra)
    return VolOutlineFM.model_validate(base)


def test_gates_pass():
    entries = {"F-001": EntryFM(id="F-001", kind="伏笔", strength="high", status="active", opened_ch=1, due_ch=16)}
    issues = run_plan_gates(_vol(), entries, _profile(), ["元启三年春", "元启三年夏"])
    assert [i for i in issues if i.level == "block"] == []


def test_gate1_deadline():
    entries = {}
    vol = _vol(entry_plan=[{"id": "F-002", "action": "开启", "due_chapter": 46}])  # 40+5=45 上限
    issues = run_plan_gates(vol, entries, _profile(), [])
    assert any(i.rule == "gate1_deadline" for i in issues)


def test_gate3_climax_gap():
    vol = _vol(climax_chapters=[2, 25])  # 间距 23 > 20
    issues = run_plan_gates(vol, {}, _profile(), [])
    assert any(i.rule == "gate3_climax_gap" for i in issues)


def test_gate4_time_regression():
    vol = _vol(time_span={"start": "元启三年夏", "end": "元启三年春"})  # 回退
    issues = run_plan_gates(vol, {}, _profile(), ["元启三年春", "元启三年夏"])
    assert any(i.rule == "gate4_time" and i.level == "block" for i in issues)


def test_gate5_overdue_uncovered():
    entries = {"F-000": EntryFM(id="F-000", kind="伏笔", strength="high", status="active",
                                opened_ch=1, due_ch=3)}
    vol = _vol(start_ch=10, end_ch=40)  # F-000 期限章 3 早于本卷起始 → 超期
    issues = run_plan_gates(vol, entries, _profile(), [])
    assert any(i.rule == "gate5_overdue" for i in issues)
    # 有兑付安排 → 通过
    vol2 = _vol(start_ch=10, end_ch=40,
                entry_plan=[{"id": "F-000", "action": "兑付", "due_chapter": 12},
                            {"id": "F-001", "action": "开启", "due_chapter": 16}])
    assert not [i for i in run_plan_gates(vol2, entries, _profile(), []) if i.rule == "gate5_overdue"]


def test_gate6_ratio_redline():
    types = {f"ch{i:04d}": "main" for i in range(1, 9)}
    for i in range(1, 5):
        types[f"ch{i:04d}"] = "side"  # side 占 50% 越红线 0.3
    vol = _vol(chapter_types=types)
    issues = run_plan_gates(vol, {}, _profile(), [])
    assert any(i.rule == "gate6_ratio" and "side" in i.msg for i in issues)


def test_poison_points_act_as_banned_words(rich_book):
    """题材毒点（权重≥0.8）视同禁词（§6.4 poison_points 消费点）。"""
    from loom.core.checks.checks import ChapterContext, ManuscriptFM, run_checks
    from loom.core.repo.frontmatter import dumps as _dumps

    rich_book.port.write_text("文风/题材/都市异能.md", _dumps(
        {"spec_stage": "genre_profile", "genre": "都市异能",
         "entry_density": [2, 4], "climax_gap": 8, "deadline_margin": 5,
         "ratio_redlines": {"main": [0.55, 0.85], "romance": [0.1, 0.35], "side": [0.0, 0.3]},
         "poison_points": {"圣母": 0.9, "降智": 0.9, "懦弱退让": 0.5}}, ""))
    ms = ManuscriptFM(spec_stage="manuscript", chapter=2, title="x",
                      time_anchor="元启三年夏", entry_changes=[{"id": "F-001", "action": "~"}],
                      contract_digest=[], word_count=3000)
    ctx = ChapterContext(chapter=2, draft="他圣母了，一路降智。", manuscript=ms, card=None, contract=[])
    targets = {i.target for i in run_checks(rich_book, ctx) if i.rule == "banned_word"}
    assert {"圣母", "降智"} <= targets and "懦弱退让" not in targets
