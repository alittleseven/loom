"""P1b 规划环测试：plan vol（六道机检 + 反馈重生成）、plan batch（章纲机检 + 连读视图 + 批准落库）。"""
from __future__ import annotations

import pytest

from loom.core.repo.frontmatter import dumps
from loom.core.repo.layout import init_book
from loom.edge.client.protocol import FakeLLMProvider
from loom.planning import PlanRejected, plan_batch, plan_vol


def _seed(tmp_path):
    book = init_book(tmp_path / "规划书", genre="都市异能")
    port = book.port
    port.write_text("大纲/总纲.md", dumps({}, "# 总纲\n\n主角李浮舟在渡口觉醒借灾能力。\n"))
    for eid, due in (("F-001", 16), ("F-002", 30)):
        port.write_text(f"大纲/条目/伏笔/{eid}.md", dumps(
            {"id": eid, "kind": "伏笔", "strength": "high", "status": "active",
             "opened_ch": 0, "due_ch": due}, f"{eid} 内容。\n"))
    # 种子入定稿（settle 拒绝脏工作区，用底层 plumbing 提交）
    changed = [line[3:] for line in port.status_porcelain()
               if line.startswith(("?? ", " M "))]
    sha = port.commit_tree({rel: port.stage_blob(port.read_text(rel)) for rel in changed},
                           "fix(手改)\n\n条目: +F-001 +F-002\n")
    port.move_ref(sha)
    port.worktree_sync()
    return book


def _vol_payload():
    types = {f"ch{i:04d}": "main" for i in range(1, 21)}
    for i in (3, 11, 19):
        types[f"ch{i:04d}"] = "romance"
    for i in (6, 14, 20):
        types[f"ch{i:04d}"] = "side"
    return {
        "climax_chapters": [5, 13, 20],
        "entry_plan": [{"id": "F-001", "action": "开启", "due_chapter": 16},
                       {"id": "F-002", "action": "开启", "due_chapter": 30}],
        "time_span": {"start": "元启三年春", "end": "元启三年夏"},
        "chapter_types": types,
        "outline": "卷一：李浮舟初掌借灾，卷末对上河祠一脉。",
    }


def test_plan_vol_success(tmp_path):
    book = _seed(tmp_path)
    provider = FakeLLMProvider(scripts={"plan_vol": _vol_payload()})
    vol = plan_vol(book, provider, 1)
    assert vol.vol == 1 and vol.rhythm.climax_gap == 8  # rhythm 来自 profile
    rel = "大纲/卷纲/vol01.md"
    assert book.port.exists(rel)
    assert book.port.status_porcelain() == []          # vol 事务已提交
    assert "vol(01)" in book.port._git.log("-1", "--format=%B")
    assert "卷一" in book.port.read_text(rel)          # 散文段保留


def test_plan_vol_gate_feedback_retry(tmp_path):
    book = _seed(tmp_path)
    calls = {"n": 0}

    def scripted(user):
        calls["n"] += 1
        if calls["n"] == 1:
            bad = _vol_payload()
            bad["climax_chapters"] = [2, 20]  # 间距 18 > 8 → gate3 违例
            return bad
        return _vol_payload()

    plan_vol(book, FakeLLMProvider(scripts={"plan_vol": scripted}), 1)
    assert calls["n"] == 2  # 第一次违例附反馈重生成成功


def test_plan_vol_exhausted_rejects(tmp_path):
    book = _seed(tmp_path)
    bad = _vol_payload()
    bad["entry_plan"] = [{"id": "F-001", "action": "开启", "due_chapter": 16}]  # 密度 1 < 2
    with pytest.raises(PlanRejected, match="plan_gates"):
        plan_vol(book, FakeLLMProvider(scripts={"plan_vol": bad}), 1)


def _cards_payload(chapters=range(1, 9), touches=("F-001", "F-002")):
    return {"cards": [
        {"chapter": ch, "touches": list(touches), "scenes": 2,
         "hook_type": "cliff" if ch % 2 else "reveal", "time_anchor": f"锚点{ch}",
         "word_tier": "standard", "brief": f"第{ch}章要点"}
        for ch in chapters
    ]}


def test_plan_batch_proposal_and_approve(tmp_path):
    book = _seed(tmp_path)
    provider = FakeLLMProvider(scripts={"plan_vol": _vol_payload(),
                                        "plan_batch": _cards_payload()})
    plan_vol(book, provider, 1)
    plan = plan_batch(book, provider, 1, 1, 8, approve=False)
    assert len(plan.cards) == 8
    assert "批次连读视图" in plan.readview and "ch0008" in plan.readview
    assert not book.port.exists("大纲/章纲/ch0001.md")  # 未批准不落仓

    plan2 = plan_batch(book, provider, 1, 1, 8, approve=True)
    assert book.port.exists("大纲/章纲/ch0001.md")
    assert book.port.status_porcelain() == []           # batch 事务已提交
    assert "batch(001..008)" in book.port._git.log("-1", "--format=%B")
    assert "兑付" in plan2.readview or "推进" in plan2.readview


def test_plan_batch_continuity_block(tmp_path):
    book = _seed(tmp_path)
    port = book.port
    port.write_text("大纲/条目/伏笔/F-003.md", dumps(
        {"id": "F-003", "kind": "伏笔", "strength": "mid", "status": "active",
         "opened_ch": 1, "due_ch": 5}, "批内到期。"))  # due=5 ≤ batch_end=8
    sha = port.commit_tree({"大纲/条目/伏笔/F-003.md": port.stage_blob(port.read_text("大纲/条目/伏笔/F-003.md"))},
                           "fix(手改)\n\n条目: +F-003\n")
    port.move_ref(sha)
    port.worktree_sync()
    provider = FakeLLMProvider(scripts={"plan_vol": _vol_payload(),
                                        "plan_batch": _cards_payload()})
    plan_vol(book, provider, 1)
    with pytest.raises(PlanRejected, match="未过机检"):
        plan_batch(book, provider, 1, 1, 8, approve=False)
    # 第二版把 F-003 加进 touches → 通过
    fixed = _cards_payload(touches=("F-001", "F-002", "F-003"))
    plan = plan_batch(book, FakeLLMProvider(scripts={"plan_batch": fixed}), 1, 1, 8, approve=False)
    assert len(plan.cards) == 8
