"""ledger：signals 旁路采集 + run-ledger 审计链 + 成本电表（M3/P1a）。

- signals.jsonl：既有动作的旁路记录（append-only，内核独占，gitignored——
  运行时高频写入不入版本库；evolve 离线只读）。
- run-ledger.jsonl：生产审计事件链（入 git，随 settle 提交；任何一章可回放）。
- 成本电表：从 ledger 事件的 usage 字段逐章聚合。
"""
from __future__ import annotations

import json
import time

from loom.core.repo.layout import BookRepo

SIGNALS_REL = "演化/signals.jsonl"
LEDGER_REL = "演化/run-ledger.jsonl"

SIGNAL_TYPES = (
    "card_action", "settle_diff", "gate_block", "review_disposition",
    "plan_deviation", "batch_breaker", "retcon",
)


def _append(port, rel: str, event: dict) -> None:
    old = port.read_text(rel) if port.exists(rel) else ""
    port.write_text(rel, old + json.dumps(event, ensure_ascii=False) + "\n")


def append_signal(repo: BookRepo, signal_type: str, payload: dict) -> None:
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"未知 signals 类型：{signal_type}")
    _append(repo.port, SIGNALS_REL, {"type": signal_type, "ts": time.time(), **payload})


def read_signals(repo: BookRepo, signal_type: str | None = None) -> list[dict]:
    rel = SIGNALS_REL
    if not repo.port.exists(rel):
        return []
    out = []
    for line in repo.port.read_text(rel).splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if signal_type is None or event.get("type") == signal_type:
            out.append(event)
    return out


def append_ledger_event(repo: BookRepo, event: dict) -> None:
    _append(repo.port, LEDGER_REL, {"ts": time.time(), **event})


def read_ledger(repo: BookRepo) -> list[dict]:
    rel = LEDGER_REL
    if not repo.port.exists(rel):
        return []
    return [json.loads(line) for line in repo.port.read_text(rel).splitlines() if line.strip()]


def cost_report(repo: BookRepo) -> dict:
    """成本电表：逐章 token 聚合（usage 记录在 ledger 事件里）。"""
    per_chapter: dict[int, dict[str, int]] = {}
    for event in read_ledger(repo):
        usage = event.get("usage")
        if not usage:
            continue
        ch = int(event.get("chapter", 0))
        bucket = per_chapter.setdefault(ch, {"in": 0, "out": 0, "calls": 0})
        bucket["in"] += int(usage.get("in", 0))
        bucket["out"] += int(usage.get("out", 0))
        bucket["calls"] += 1
    total_in = sum(b["in"] for b in per_chapter.values())
    total_out = sum(b["out"] for b in per_chapter.values())
    return {"per_chapter": per_chapter, "total_in": total_in, "total_out": total_out,
            "chapters": len(per_chapter)}
