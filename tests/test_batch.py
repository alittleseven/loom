"""批次连写测试：状态机、七项熔断、三档自治、人验简报、断点恢复。"""
from __future__ import annotations

import pytest

from loom.core.repo.frontmatter import dumps
from loom.staging import (
    BatchState,
    accept_batch,
    arm_batch,
    compute_breakers,
    evaluate_breakers,
    load_batch_state,
    resume_batch,
    run_batch,
)
from tests.test_pipeline import _long_draft, _provider, _seed  # 复用 e2e 素材


def _seed_batch(tmp_path, n=4):
    """搭一个 4 章批次的书仓（章纲卡齐全）。"""
    book = _seed(tmp_path)
    port = book.port
    for ch in range(2, n + 1):
        port.write_text(f"大纲/章纲/ch{ch:04d}.md", dumps(
            {"spec_stage": "chapter_card", "chapter": ch, "touches": ["F-001"], "scenes": 2,
             "hook_type": "cliff", "time_anchor": "元启三年春", "word_tier": "setup"},
            f"第{ch}章要点。\n"))
    # 章纲卡与题材 profile 入定稿
    changed = [line[3:] for line in port.status_porcelain() if line.startswith(("?? ", " M "))]
    sha = port.commit_tree({rel: port.stage_blob(port.read_text(rel)) for rel in changed},
                           "fix(手改)\n\n章纲卡落仓\n")
    port.move_ref(sha)
    port.worktree_sync()
    return book


def test_batch_full_l2(tmp_path):
    book = _seed_batch(tmp_path)
    arm_batch(book, chapters=[1, 2, 3, 4], autonomy="L2")
    report = run_batch(book, _provider())
    assert report.state == BatchState.REVIEW.value
    assert report.done == [1, 2, 3, 4]
    assert book.port.status_porcelain() == []  # 每章独立 commit 后仓库干净
    # 批次人验简报
    assert any("批次人验简报" in b for b in report.brief)
    assert any("成本" in b for b in report.brief)
    # 作者全收
    state = accept_batch(book)
    assert state["state"] == BatchState.ACCEPTED.value


def test_batch_halt_on_pipeline_failure(tmp_path):
    book = _seed_batch(tmp_path)
    # 第一次 run：所有章都渲染坏稿 → 第 1 章就 HALT
    arm_batch(book, chapters=[1, 2], autonomy="L1")
    report = run_batch(book, _provider(manuscript="他顿悟了，系统提示响起。一切平静结束。"))
    assert report.state == BatchState.HALTED.value
    assert report.done == []
    # 断点恢复：换好稿子续跑
    state = resume_batch(book)
    assert state["state"] == BatchState.RUNNING.value
    report2 = run_batch(book, _provider(manuscript=_long_draft()))
    assert report2.state == BatchState.REVIEW.value
    assert report2.done == [1, 2]


def test_batch_requires_cards(tmp_path):
    book = _seed_batch(tmp_path)
    with pytest.raises(ValueError, match="章纲卡缺失"):
        arm_batch(book, chapters=[9])


def test_breakers_metrics_shape(tmp_path):
    book = _seed_batch(tmp_path)
    arm_batch(book, chapters=[1], autonomy="L2")
    run_batch(book, _provider())
    metrics = compute_breakers(book)
    assert {"check_block_rate", "leak_hit", "rhythm_debt", "rerender_rate"} <= set(metrics)
    ev = evaluate_breakers(book)
    assert isinstance(ev["halt"], bool)


def test_batch_arm_rejected_when_locked(tmp_path):
    import subprocess
    import sys

    from loom.core.repo import lock as repo_lock

    book = _seed_batch(tmp_path)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        import json as _json
        book.port.write_text(".loom/lock.json", _json.dumps({"pid": child.pid, "started_at": 0}))
        with pytest.raises(repo_lock.RepoBusy):
            arm_batch(book, chapters=[1])
    finally:
        child.kill()
        child.wait()


def test_signal_window_reset_per_type(tmp_path):
    """审阅报告 B：resume 窗口重置按类型记录 offset，新信号不被旧 offset 屏蔽。"""
    from loom.core import ledger as ledger_mod
    from loom.staging import _signal_offsets

    book = _seed_batch(tmp_path)
    ledger_mod.append_ledger_event(book, {"event": "settle", "chapter": 1})
    ledger_mod.append_signal(book, "gate_block", {"chapter": 1, "kind": "block", "rule": "x"})
    ledger_mod.append_signal(book, "plan_deviation", {"chapter": 1, "deviation": ["F-001"]})
    ledger_mod.append_signal(book, "plan_deviation", {"chapter": 1, "deviation": []})
    m0 = compute_breakers(book)
    # rate 按章计（n=1）：同章两条 plan_deviation（一真一空）→ 该章记 1
    assert m0["check_block_rate"] == 1.0 and m0["plan_deviation_rate"] == 1.0

    offsets = _signal_offsets(book)
    assert offsets["gate_block"] == 1 and offsets["plan_deviation"] == 2
    m1 = compute_breakers(book, since_signal=offsets)  # 重置后旧信号不可见
    assert m1["check_block_rate"] == 0.0 and m1["plan_deviation_rate"] == 0.0

    # 新信号恢复可见（旧实现按跨类总和切 gate_block，会把新信号一并屏蔽）
    ledger_mod.append_signal(book, "gate_block", {"chapter": 1, "kind": "block", "rule": "leak"})
    m2 = compute_breakers(book, since_signal=offsets)
    assert m2["check_block_rate"] == 1.0 and m2["leak_hit"] == 1
    # 旧版 int offset 兼容读取（按 gate_block 单类型解释）
    assert compute_breakers(book, since_signal=1)["check_block_rate"] == 1.0


def test_resume_records_per_type_offsets(tmp_path):
    import json as _json

    from loom.staging import STATE_REL

    book = _seed_batch(tmp_path)
    book.port.write_text(STATE_REL, _json.dumps(
        {"state": "BATCH_PAUSED", "chapters": [1], "done": [], "autonomy": "L2",
         "halted_at": None, "halt_reason": None}))
    state = resume_batch(book)
    assert isinstance(state["signal_window_reset"], dict)
    assert {"gate_block", "plan_deviation", "review_disposition",
            "card_action", "settle_diff", "fulfillment_missed"} == set(state["signal_window_reset"])


def test_missed_rate_breaker_counts_fulfillment_missed(tmp_path):
    """审阅报告 C-missed：missed_rate 由 fulfillment_missed 信号驱动，不再恒零。"""
    from loom.core import ledger as ledger_mod

    book = _seed_batch(tmp_path)
    ledger_mod.append_ledger_event(book, {"event": "settle", "chapter": 1})
    assert compute_breakers(book)["missed_rate"] == 0.0
    ledger_mod.append_signal(book, "fulfillment_missed", {"chapter": 1, "missed": ["含:李浮舟"]})
    assert compute_breakers(book)["missed_rate"] == 1.0
    ev = evaluate_breakers(book)
    assert any(t["rule"] == "missed_rate" for t in ev["triggered"])


def test_rerender_rate_counts_review_rerender(tmp_path):
    """审阅报告 C-rerender：每次渲染 attempt 入账，重渲染率不再恒零。"""
    from loom.pipeline import run_chapter
    from tests.test_pipeline import _CARD

    book = _seed_batch(tmp_path)
    calls = {"n": 0}

    def draft_fn(user):
        calls["n"] += 1
        return _long_draft()

    provider = _provider(
        manuscript=draft_fn,
        review_fact=lambda user: {"issues": [{"severity": "block", "desc": "x", "quote": "..."}]}
        if calls["n"] == 1 else {"issues": []},
    )
    run_chapter(book, provider, _CARD, contract=[])
    assert compute_breakers(book)["rerender_rate"] == 1.0  # 2 次渲染 - 1 章


def test_run_batch_holds_lock_and_catches_settle_rejected(tmp_path, monkeypatch):
    """审阅报告 G：批次运行全程持锁；结算前置失败转 HALTED（可恢复），不裸 traceback。"""
    import loom.staging as staging_mod
    from loom.core.repo import lock as repo_lock
    from loom.core.settle.transaction import SettleRejected

    book = _seed_batch(tmp_path)
    arm_batch(book, chapters=[1, 2], autonomy="L2")

    seen = {}

    def exploding_run_chapter(repo, provider, card, contract, **kw):
        seen["lock_held"] = repo_lock.read_lock(repo.port) is not None
        raise SettleRejected("工作区不干净，拒绝结算：模拟中途写入")

    monkeypatch.setattr(staging_mod, "run_chapter", exploding_run_chapter)
    report = run_batch(book, _provider())
    assert report.state == BatchState.HALTED.value
    assert seen["lock_held"] is True                     # 运行期间持锁
    assert not book.port.exists(".loom/lock.json")       # 结束后释放
    state = load_batch_state(book)
    assert "结算被拒" in state["halt_reason"]
    assert resume_batch(book)["state"] == BatchState.RUNNING.value  # 可恢复
