"""schema 表驱动测试（loom-1 §4/§5/§6）：豁免载体、id 语法、配比口径、容错。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from loom.core.repo.schema import (
    ChapterCardFM,
    DecisionCardFM,
    EntryFM,
    ManuscriptFM,
    VolOutlineFM,
    Waiver,
    ratio_from_chapter_types,
)

# ---- 条目账本 ----

ENTRY_OK = dict(id="F-001", kind="伏笔", strength="high", status="active", opened_ch=3, due_ch=16)


@pytest.mark.parametrize(
    "patch, expect_ok",
    [
        ({}, True),
        ({"id": "f-001"}, False),          # 必须大写前缀
        ({"id": "F-1"}, False),            # 必须三位数字
        ({"id": "X-001"}, False),          # 未知前缀
        ({"kind": "悬念"}, False),          # id 前缀与 kind 不一致
        ({"status": "paid"}, True),        # paid 合法
        ({"status": "dead"}, False),       # 未知状态
        ({"strength": "super"}, False),
    ],
)
def test_entry_table(patch, expect_ok):
    data = {**ENTRY_OK, **patch}
    if expect_ok:
        assert EntryFM.model_validate(data).id == data["id"]
    else:
        with pytest.raises(ValidationError):
            EntryFM.model_validate(data)


def test_entry_unknown_field_tolerated():
    e = EntryFM.model_validate({**ENTRY_OK, "v6_legacy": 123})
    dumped = e.model_dump()
    assert dumped["v6_legacy"] == 123  # 容错保留写回，不丢单


# ---- 章纲卡：touch ≥1 或显式豁免（A1）----

CARD_OK = dict(
    spec_stage="chapter_card", chapter=3, touches=["F-001"], scenes=2,
    hook_type="cliff", time_anchor="元启三年春", word_tier="standard",
)


def test_chapter_card_touch_ok():
    assert ChapterCardFM.model_validate(CARD_OK).chapter == 3


def test_chapter_card_waiver_requires_author():
    with pytest.raises(ValidationError):
        ChapterCardFM.model_validate({**CARD_OK, "touches": []})  # 无豁免且无 touch
    ok = ChapterCardFM.model_validate(
        {**CARD_OK, "touches": [], "touch_waiver": {"reason": "过渡章", "approved_by": "author", "source": "decision_card"}}
    )
    assert ok.touch_waiver is not None
    with pytest.raises(ValidationError):  # LLM 无权豁免
        ChapterCardFM.model_validate(
            {**CARD_OK, "touches": [], "touch_waiver": {"reason": "x", "approved_by": "llm", "source": "decision_card"}}
        )


def test_chapter_card_scenes_range():
    with pytest.raises(ValidationError):
        ChapterCardFM.model_validate({**CARD_OK, "scenes": 4})


# ---- 决策卡 seam ----

def test_decision_card_seam_field():
    d = DecisionCardFM.model_validate(
        dict(spec_stage="decision_card", seam_version="1", chapter=3,
             generated_by="plan_template", contract=["断言"], options=[])
    )
    assert d.contract == ["断言"]


# ---- 卷纲：条目计划 + 豁免列表（A1/gate 数据源）----

VOL_OK = dict(
    spec_stage="plan", vol=1, climax_chapters=[12],
    entry_plan=[{"id": "F-001", "action": "开启", "due_chapter": 16}],
    time_span={"start": "元启三年春", "end": "元启三年夏"},
    chapter_types={"ch0001": "main", "ch0002": "transition"},
    rhythm={"entry_density": [2, 4], "climax_gap": 8, "deadline_margin": 5},
    waivers=[],
)


def test_vol_outline_ok():
    v = VolOutlineFM.model_validate(VOL_OK)
    assert v.entry_plan[0].id == "F-001"
    with pytest.raises(ValidationError):  # 非法 action
        VolOutlineFM.model_validate({**VOL_OK, "entry_plan": [{"id": "F-001", "action": "跳过", "due_chapter": 16}]})


# ---- 正文 front matter ----

def test_manuscript_entry_change_signs():
    m = ManuscriptFM.model_validate(
        dict(spec_stage="manuscript", chapter=1, title="灾从口入", time_anchor="元启",
             entry_changes=[{"id": "F-001", "action": "+"}], contract_digest=[], word_count=3000)
    )
    assert m.entry_changes[0].action == "+"
    with pytest.raises(ValidationError):
        ManuscriptFM.model_validate(
            dict(spec_stage="manuscript", chapter=1, title="灾从口入", time_anchor="元启",
                 entry_changes=[{"id": "F-001", "action": "开启"}], contract_digest=[], word_count=3000)
        )


# ---- A3 配比口径 ----

def test_ratio_groups():
    types = {f"ch{i:04d}": t for i, t in enumerate(
        ["main", "climax", "main", "romance", "side", "transition", "main", "romance"], start=1)}
    r = ratio_from_chapter_types(types)
    assert r == {"main": 0.5, "romance": 0.25, "side": 0.25}
    assert ratio_from_chapter_types({}) == {}
    with pytest.raises(ValueError):
        ratio_from_chapter_types({"ch0001": "unknown_type"})


def test_waiver_model_direct():
    w = Waiver(reason="双章连发合并钩子", approved_by="author", source="vol_outline")
    assert w.approved_by == "author"
