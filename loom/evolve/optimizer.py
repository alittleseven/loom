"""P4 品味进化闭环（离线）：signals 聚合分析 → 优化提案 → bench 回归（拒绝式约束）
→ holdout 盲判 → 作者批准合并 → 快照可回滚。

红线（v3.0 §4.5）：运行时永不读 signals；机检通过率永不作 fitness；
bench（含盲测风格子集）只作拒绝式约束——不向优化器提供可最大化的标量。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from loom.core import ledger as ledger_mod
from loom.core.repo.layout import BookRepo

SNAPSHOT_REL = "演化/优化快照"
PROPOSALS_REL = "演化/优化提案"


# ---- signals 聚合分析（周报）----

def analyze(repo: BookRepo) -> dict:
    gate_blocks = ledger_mod.read_signals(repo, "gate_block")
    reviews = ledger_mod.read_signals(repo, "review_disposition")
    plans = ledger_mod.read_signals(repo, "plan_deviation")
    settles = ledger_mod.read_signals(repo, "settle_diff")

    rule_counts: dict[str, int] = {}
    for g in gate_blocks:
        rule_counts[g.get("rule", "?")] = rule_counts.get(g.get("rule", "?"), 0) + 1
    chapters = {s.get("chapter") for s in settles}
    deviation_chapters = [p for p in plans if p.get("deviation")]
    return {
        "chapters_observed": len(chapters),
        "gate_blocks_by_rule": dict(sorted(rule_counts.items(), key=lambda kv: -kv[1])),
        "review_block_rate": (sum(1 for r in reviews if r.get("blocked")) /
                              max(len(reviews), 1)),
        "plan_deviation_rate": len(deviation_chapters) / max(len(plans), 1),
        "top_rules": list(dict(sorted(rule_counts.items(), key=lambda kv: -kv[1])).items())[:3],
    }


def weekly_report(repo: BookRepo) -> str:
    a = analyze(repo)
    lines = [f"【signals 周报】观察 {a['chapters_observed']} 章",
             f"机检拦截分布：{a['gate_blocks_by_rule']}",
             f"评审阻断率 {a['review_block_rate']:.2f}（第一优化对象：评审 prompt）",
             f"规划偏差率 {a['plan_deviation_rate']:.2f}（第二优化对象：规划 prompt）"]
    text = "\n".join(lines) + "\n"
    repo.write_file("演化/signals-周报.md", text, actor="core")
    return text


# ---- 优化提案与快照 ----

@dataclass
class Proposal:
    target: str                      # review_prompt | plan_prompt
    change: dict                     # 具体旋钮（如 {system_append: "..."}）
    reason: str
    metrics_before: dict = field(default_factory=dict)


def propose(repo: BookRepo, proposal: Proposal) -> str:
    """把提案落盘待审（作者批准前不生效）。"""
    pid = time.strftime("%Y%m%d-%H%M%S")
    rel = f"{PROPOSALS_REL}/{pid}.json"
    repo.write_file(rel, json.dumps({
        "id": pid, "target": proposal.target, "change": proposal.change,
        "reason": proposal.reason, "status": "proposed",
        "metrics_before": proposal.metrics_before,
    }, ensure_ascii=False, indent=1) + "\n", actor="core")
    return pid


def bench_regression_gate(repo: BookRepo, baseline: dict, candidate: dict) -> bool:
    """拒绝式约束（M5 红线）：候选致任一指标退化 → 拒绝。

    指标：伏笔回收率（越高越好）、设定违例率/机检误报率（越低越好）。
    这里不给优化器任何可最大化的标量——只返回 pass/reject。
    """
    higher_better = ("recall_rate",)
    lower_better = ("violation_rate", "false_positive_rate")
    for k in higher_better:
        if candidate.get(k, baseline.get(k, 0)) < baseline.get(k, 0):
            return False
    for k in lower_better:
        if candidate.get(k, baseline.get(k, 0)) > baseline.get(k, 0):
            return False
    return True


def approve_and_snapshot(repo: BookRepo, proposal_id: str, holdout_blind_ok: bool) -> str:
    """作者批准：holdout 盲判通过 → 写快照（可回滚）→ 提案标记 merged。"""
    if not holdout_blind_ok:
        raise ValueError("holdout 盲判未通过，不得合并（合并决策只依据作者盲判）")
    rel = f"{PROPOSALS_REL}/{proposal_id}.json"
    if not repo.port.exists(rel):
        raise FileNotFoundError(proposal_id)
    data = json.loads(repo.port.read_text(rel))
    data["status"] = "merged"
    data["merged_at"] = time.strftime("%Y-%m-%d")
    snapshot = {
        "proposal": proposal_id, "target": data["target"], "change": data["change"],
        "rollback_hint": f" revert {proposal_id}",
        "snapshot_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    repo.write_file(f"{SNAPSHOT_REL}/{proposal_id}.json",
                    json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", actor="core")
    repo.write_file(rel, json.dumps(data, ensure_ascii=False, indent=1) + "\n", actor="core")
    return f"{SNAPSHOT_REL}/{proposal_id}.json"


def rollback(repo: BookRepo, proposal_id: str) -> None:
    """快照回滚：提案标记 reverted。"""
    rel = f"{PROPOSALS_REL}/{proposal_id}.json"
    if not repo.port.exists(rel):
        raise FileNotFoundError(proposal_id)
    data = json.loads(repo.port.read_text(rel))
    data["status"] = "reverted"
    repo.write_file(rel, json.dumps(data, ensure_ascii=False, indent=1) + "\n", actor="core")
