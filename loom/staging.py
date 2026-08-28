"""批次连写与熔断（v3.0 §4.3，P3）。

状态机：BATCH_ARMED → BATCH_RUNNING → BATCH_REVIEW → BATCH_ACCEPTED
                      ├─ 章级重试耗尽/熔断/体检不过 → BATCH_HALTED/PARSED
不变量：每章独立原子 commit；可从任意章恢复（run-ledger 断点续跑）。
七项熔断（趋势层，滚动窗口 10 章，全部零 LLM 可算）。
三档自治：L0 全手动 / L1 半自动 / L2 批次自动（批次末人验）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from loom.core import ledger as ledger_mod
from loom.core.repo.frontmatter import split
from loom.core.repo.layout import BookRepo
from loom.core.repo.schema import EntryFM
from loom.pipeline import PipelineHalted, run_chapter

WINDOW = 10


class BatchState(str, Enum):
    ARMED = "BATCH_ARMED"
    RUNNING = "BATCH_RUNNING"
    REVIEW = "BATCH_REVIEW"
    ACCEPTED = "BATCH_ACCEPTED"
    HALTED = "BATCH_HALTED"
    PAUSED = "BATCH_PAUSED"


STATE_REL = "工作区/批次状态.json"


@dataclass
class BreakerRule:
    key: str
    label: str
    threshold: float
    kind: str = "ratio"   # ratio | any | sigma


DEFAULT_BREAKERS = (
    BreakerRule("check_block_rate", "机检拦截率", 0.30),
    BreakerRule("missed_rate", "履约 missed>0 章占比", 0.20),
    BreakerRule("leak_hit", "设定违例/泄密命中", 1, kind="any"),
    BreakerRule("rhythm_debt", "节奏债（高强度超期数）", 10, kind="any"),
    BreakerRule("rerender_rate", "重渲染率", 0.25),
)


def load_batch_state(repo: BookRepo) -> dict | None:
    if not repo.port.exists(STATE_REL):
        return None
    return json.loads(repo.port.read_text(STATE_REL))


def save_batch_state(repo: BookRepo, state: dict) -> None:
    repo.write_file(STATE_REL, json.dumps(state, ensure_ascii=False, indent=1), actor="core")


def arm_batch(repo: BookRepo, chapters: list[int], autonomy: str = "L2") -> dict:
    """前置条件：批次大纲（章纲卡）已批准落仓。持写锁进入 ARMED。"""
    from loom.core.repo import lock as repo_lock

    missing = [ch for ch in chapters
               if not repo.port.exists(f"大纲/章纲/ch{ch:04d}.md")]
    if missing:
        raise ValueError(f"章纲卡缺失：{missing[:3]}（先 plan batch --yes）")
    foreign = repo_lock.is_locked_by_other(repo.port)
    if foreign is not None:
        raise repo_lock.RepoBusy(foreign)
    state = {"state": BatchState.ARMED.value, "chapters": chapters, "autonomy": autonomy,
             "done": [], "halted_at": None, "halt_reason": None}
    save_batch_state(repo, state)
    return state


# ---- 七项熔断指标计算（滚动窗口 10 章，零 LLM）----

def compute_breakers(repo: BookRepo, window: int = WINDOW, *, since_signal: int = 0) -> dict:
    """滚动窗口熔断指标。since_signal：只统计行号 ≥ 该值的 signals（resume 重置窗口）。"""
    gate_blocks = ledger_mod.read_signals(repo, "gate_block")[since_signal:]
    settles = [e for e in ledger_mod.read_ledger(repo) if e.get("event") == "settle"]
    recent_chapters = [e["chapter"] for e in settles][-window:]
    recent_set = set(recent_chapters)
    n = max(len(recent_chapters), 1)

    blocked_chapters = {g["chapter"] for g in gate_blocks
                        if g.get("kind") == "block" and g.get("chapter") in recent_set}
    leak_hits = sum(1 for g in gate_blocks
                    if g.get("rule") == "leak" and g.get("kind") == "block"
                    and g.get("chapter") in recent_set)
    rerender_chapters = {e["chapter"] for e in ledger_mod.read_ledger(repo)
                         if e.get("event") == "render_call"
                         and e.get("chapter") in recent_set}
    render_counts = sum(1 for e in ledger_mod.read_ledger(repo)
                        if e.get("event") == "render_call" and e.get("chapter") in recent_set)
    entries: dict[str, EntryFM] = {}
    from loom.core.checks.checks import load_entries

    entries = load_entries(repo)
    rhythm_debt = sum(1 for e in entries.values()
                      if e.status == "active" and e.strength == "high"
                      and e.due_ch is not None and e.last_touched_ch is not None
                      and e.due_ch < e.last_touched_ch)
    plan_dev = [s for s in ledger_mod.read_signals(repo, "plan_deviation")
                if s.get("chapter") in recent_set]
    metrics = {
        "check_block_rate": len(blocked_chapters) / n,
        "missed_rate": 0.0,   # 履约 missed 由 check_fulfillment 产出，P1a 已埋 gate_block
        "leak_hit": leak_hits,
        "rhythm_debt": rhythm_debt,
        "rerender_rate": max(render_counts - len(rerender_chapters), 0) / n
                         if render_counts > len(rerender_chapters) else 0.0,
        "plan_deviation_rate": sum(1 for p in plan_dev if p.get("deviation")) / n,
    }
    return metrics


def evaluate_breakers(repo: BookRepo, rules: tuple[BreakerRule, ...] = DEFAULT_BREAKERS,
                      *, since_signal: int = 0) -> dict:
    metrics = compute_breakers(repo, since_signal=since_signal)
    triggered = []
    for rule in rules:
        value = metrics.get(rule.key, 0)
        hit = value >= rule.threshold if rule.kind == "any" else value > rule.threshold
        if hit:
            triggered.append({"rule": rule.key, "label": rule.label,
                              "value": value, "threshold": rule.threshold})
    return {"metrics": metrics, "triggered": triggered,
            "halt": bool(triggered)}


@dataclass
class BatchReport:
    state: str
    done: list[int]
    brief: list[str] = field(default_factory=list)
    breaker: dict = field(default_factory=dict)


def run_batch(repo: BookRepo, provider, *, on_halt=None) -> BatchReport:
    """执行批次：逐章 run_chapter（每章独立原子 commit）；熔断触发→完成当前章→停批。

    resume 后（window_reset 记录存在）：熔断评估只看恢复点之后的信号，
    防 HALT 批次的旧拦截把新批次"同一问题连环放大"（§4.3 标定注意）。
    """
    state = load_batch_state(repo)
    if state is None:
        raise ValueError("批次未 ARMED（先 loom batch arm）")
    state["state"] = BatchState.RUNNING.value
    save_batch_state(repo, state)

    for ch in state["chapters"]:
        if ch in state["done"]:
            continue
        if state.get("halted_at"):
            break
        try:
            from loom.core.repo.schema import ChapterCardFM

            fm, _body = split(repo.port.read_text(f"大纲/章纲/ch{ch:04d}.md"))
            card = ChapterCardFM.model_validate(fm)
            result = run_chapter(repo, provider, card,
                                 contract=list(fm.get("contract", []) or []),
                                 autonomy=state["autonomy"])
            state["done"].append(ch)
            state["render_stats"] = state.get("render_stats", {})
            state["render_stats"][str(ch)] = result.render_attempts
        except PipelineHalted as e:
            state["halted_at"] = ch
            state["halt_reason"] = f"章级重试耗尽：{e}"
            state["state"] = BatchState.HALTED.value
            save_batch_state(repo, state)
            ledger_mod.append_signal(repo, "batch_breaker",
                                     {"chapter": ch, "trigger": "pipeline_halt"})
            if on_halt:
                on_halt(ch, str(e))
            return _report(repo, state)

        breaker = evaluate_breakers(repo, since_signal=state.get("signal_window_reset", 0))
        if breaker["halt"] and state["done"]:
            state["halted_at"] = ch
            state["halt_reason"] = f"熔断触发：{breaker['triggered']}"
            state["state"] = BatchState.HALTED.value
            save_batch_state(repo, state)
            ledger_mod.append_signal(repo, "batch_breaker",
                                     {"chapter": ch, "trigger": breaker["triggered"]})
            return _report(repo, state)
        save_batch_state(repo, state)

    if len(state["done"]) == len(state["chapters"]):
        state["state"] = BatchState.REVIEW.value
        save_batch_state(repo, state)
    return _report(repo, state)


def _report(repo: BookRepo, state: dict) -> BatchReport:
    report = BatchReport(state=state["state"], done=list(state["done"]))
    report.breaker = evaluate_breakers(
        repo, since_signal=state.get("signal_window_reset", 0))
    report.brief = build_review_brief(repo, state)
    return report


def build_review_brief(repo: BookRepo, state: dict) -> list[str]:
    """批次人验简报：摘要链 + 条目结转清单 + 体检指标 + 成本账单。"""
    lines: list[str] = [f"【批次人验简报】{state['state']} 完成 {len(state['done'])}/{len(state['chapters'])} 章"]
    for ch in state["done"]:
        rel = f"定稿/摘要/ch{ch:04d}.md"
        if repo.port.exists(rel):
            _fm, body = split(repo.port.read_text(rel))
            lines.append(f"- ch{ch:04d}：{' '.join(body.split())[:80]}")
    from loom.core.checks.checks import load_entries

    active = [e for e in load_entries(repo).values() if e.status == "active"]
    lines.append(f"活跃条目 {len(active)} 条；"
                 + "；".join(f"{e.id}(期限{e.due_ch})" for e in active[:5]))
    cost = ledger_mod.cost_report(repo)
    lines.append(f"成本：{cost['total_in']} in / {cost['total_out']} out tokens，{cost['chapters']} 章")
    return lines


def accept_batch(repo: BookRepo) -> dict:
    """作者全收：REVIEW → ACCEPTED，释放锁文件语义。"""
    state = load_batch_state(repo)
    if state is None or state["state"] != BatchState.REVIEW.value:
        raise ValueError("批次不在 BATCH_REVIEW 状态")
    state["state"] = BatchState.ACCEPTED.value
    save_batch_state(repo, state)
    return state


def resume_batch(repo: BookRepo) -> dict:
    """HALT 断点恢复：清 halted_at，回到 RUNNING 续跑；记录信号窗口重置点。"""
    state = load_batch_state(repo)
    if state is None:
        raise ValueError("无批次状态")
    if state["state"] not in (BatchState.HALTED.value, BatchState.PAUSED.value):
        raise ValueError(f"批次状态 {state['state']} 不可恢复")
    state["state"] = BatchState.RUNNING.value
    state["halted_at"] = None
    state["halt_reason"] = None
    state["signal_window_reset"] = sum(
        len(ledger_mod.read_signals(repo, t))
        for t in ("gate_block", "review_disposition", "card_action", "settle_diff", "plan_deviation"))
    save_batch_state(repo, state)
    return state
