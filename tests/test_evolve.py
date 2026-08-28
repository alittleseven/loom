"""P4 进化层测试：signals 聚合、拒绝式约束（M5 红线）、提案-快照-回滚。"""
from __future__ import annotations

import json

import pytest

from loom.core import ledger as ledger_mod
from loom.core.repo.layout import init_book
from loom.evolve.optimizer import (
    Proposal,
    analyze,
    approve_and_snapshot,
    bench_regression_gate,
    propose,
    rollback,
    weekly_report,
)


def _book_with_signals(tmp_path):
    book = init_book(tmp_path / "进化书", genre="都市异能")
    for ch in range(1, 6):
        ledger_mod.append_signal(book, "gate_block",
                                 {"chapter": ch, "kind": "block", "rule": "no_hook",
                                  "target": "", "msg": "x", "hint": ""})
        ledger_mod.append_signal(book, "review_disposition",
                                 {"chapter": ch, "issues": 1, "blocked": ch % 2 == 1,
                                  "disposition": "adopted"})
        ledger_mod.append_signal(book, "plan_deviation",
                                 {"chapter": ch, "planned": ["F-001"], "actual": ["F-001"],
                                  "deviation": [] if ch < 4 else ["F-002"]})
        ledger_mod.append_signal(book, "settle_diff",
                                 {"chapter": ch, "changed_ratio": 0.0, "autonomy": "L1"})
    return book


def test_analyze_aggregates(tmp_path):
    book = _book_with_signals(tmp_path)
    a = analyze(book)
    assert a["chapters_observed"] == 5
    assert a["gate_blocks_by_rule"]["no_hook"] == 5
    assert a["review_block_rate"] == 0.6
    assert a["plan_deviation_rate"] == 0.4


def test_weekly_report_written(tmp_path):
    book = _book_with_signals(tmp_path)
    text = weekly_report(book)
    assert "signals 周报" in text
    assert book.port.exists("演化/signals-周报.md")


def test_rejective_gate_never_maximizes(tmp_path):
    """bench 只给 pass/reject：退化即拒绝，改善也不给分数。"""
    baseline = {"recall_rate": 0.8, "violation_rate": 0.1}
    assert bench_regression_gate(None, baseline, {"recall_rate": 0.85, "violation_rate": 0.05})
    assert not bench_regression_gate(None, baseline, {"recall_rate": 0.7, "violation_rate": 0.05})
    assert not bench_regression_gate(None, baseline, {"recall_rate": 0.9, "violation_rate": 0.2})
    result = bench_regression_gate(None, baseline, {"recall_rate": 0.9})
    assert isinstance(result, bool)  # 无标量输出


def test_proposal_snapshot_rollback(tmp_path):
    book = _book_with_signals(tmp_path)
    pid = propose(book, Proposal(target="review_prompt",
                                 change={"system_append": "关注承接断裂的具体样例"},
                                 reason="评审阻断率 0.6 偏高",
                                 metrics_before={"review_block_rate": 0.6}))
    rel = f"演化/优化提案/{pid}.json"
    assert json.loads(book.port.read_text(rel))["status"] == "proposed"
    # holdout 盲判不过 → 拒绝合并
    with pytest.raises(ValueError, match="holdout"):
        approve_and_snapshot(book, pid, holdout_blind_ok=False)
    snap_rel = approve_and_snapshot(book, pid, holdout_blind_ok=True)
    assert json.loads(book.port.read_text(rel))["status"] == "merged"
    assert json.loads(book.port.read_text(snap_rel))["proposal"] == pid
    rollback(book, pid)
    assert json.loads(book.port.read_text(rel))["status"] == "reverted"
