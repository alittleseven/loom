"""规划环（v3.0 §4.1）：与写侧同构——LLM 生成走 edge，机检走 core，写入走 settle。

- plan_vol：生成卷纲（结构化 front matter）→ plan_gates 六道 → 违规附错误反馈
  重生成 ≤2 次 → 耗尽人工改纲（PlanRejected）。
- plan_batch：生成一批章纲卡 → 章纲机检（touch≥1/钩子非空/锚点单调/跨批连续）→
  连读视图（作者批准的对象是条目结转计划，不是文本）。
plan_deviation 埋点：结算时计划 vs 实际的偏差由 pipeline 采集（A4）。
"""
from __future__ import annotations

from dataclasses import dataclass

from loom.core.checks.checks import (
    Issue,
    load_entries,
    load_profile,
    run_plan_gates,
    timeline_anchors,
)
from loom.core.repo.frontmatter import dumps, split
from loom.core.repo.layout import BookRepo
from loom.core.repo.schema import ChapterCardFM, GenreProfileFM, VolOutlineFM
from loom.core.settle.transaction import FileOp, SettleInput
from loom.core.settle.transaction import run as settle_run
from loom.edge import prompts

PLAN_TIER = "review"  # 规划用中档（§5.3）


class PlanRejected(RuntimeError):
    def __init__(self, msg: str, issues: list[Issue] | None = None) -> None:
        super().__init__(msg)
        self.issues = issues or []


def _profile(repo: BookRepo) -> GenreProfileFM:
    profile = load_profile(repo)
    if profile is None:
        raise PlanRejected("题材 profile 缺失（文风/题材/<genre>.md）")
    return profile


def _entries_snapshot(repo: BookRepo, vol_start_ch: int) -> str:
    lines = []
    for e in sorted(load_entries(repo).values(), key=lambda x: x.id):
        if e.status == "active":
            lines.append(f"- {e.id}（{e.kind}/{e.strength}/opened={e.opened_ch}/due={e.due_ch}）")
    return "\n".join(lines) or "（无活跃条目）"


def _rhythm_of(profile: GenreProfileFM) -> dict:
    return {"entry_density": list(profile.entry_density), "climax_gap": profile.climax_gap,
            "deadline_margin": profile.deadline_margin}


def plan_vol(repo: BookRepo, provider, vol: int, *, start_ch: int | None = None) -> VolOutlineFM:
    """生成卷纲并过六道机检；通过后以 vol(NN) 事务写入。"""
    profile = _profile(repo)
    anchors = timeline_anchors(repo)
    _fm_gm, gm_body = (split(repo.port.read_text("大纲/总纲.md"))
                       if repo.port.exists("大纲/总纲.md") else ({}, ""))
    prev_summary = ""
    for v in range(vol - 1, 0, -1):
        rel = f"定稿/卷摘要/vol{v:02d}.md"
        if repo.port.exists(rel):
            _fm, body = split(repo.port.read_text(rel))
            prev_summary = " ".join(body.split())[:300]
            break

    feedback = ""
    for attempt in range(3):
        user = (
            f"【总纲】\n{gm_body.strip()[:2000]}\n\n【条目账本快照（active/overdue）】\n"
            f"{_entries_snapshot(repo, 0)}\n\n【上一卷卷末状态】\n{prev_summary or '（首卷）'}\n\n"
            f"【节奏预算（必须原样采用）】\n{_rhythm_of(profile)}\n\n"
            f"【卷号】{vol}\n【时间线已有锚点】{anchors}\n{feedback}"
        )
        res = provider.complete_structured(tier=PLAN_TIER, schema_name="plan_vol",
                                           system=prompts.PLAN_VOL_SYSTEM, user=user)
        data = dict(res.data)
        data.update({"spec_stage": "plan", "vol": vol, "rhythm": _rhythm_of(profile)})
        try:
            vol_fm = VolOutlineFM.model_validate(data)
        except (ValueError, TypeError) as e:
            feedback = f"上一次生成 schema 不合法：{e}。请修正后重新输出 JSON。"
            continue
        issues = run_plan_gates(vol_fm, load_entries(repo), profile, anchors)
        blocks = [i for i in issues if i.level == "block"]
        if blocks:
            feedback = "上一次生成违反以下机检，必须修正：\n" + "\n".join(
                f"- [{i.rule}] {i.msg}" for i in blocks)
            continue
        rel = f"大纲/卷纲/vol{vol:02d}.md"
        settle_run(repo.port, SettleInput(
            message=f"vol({vol:02d})\n\n条目: -\n",
            files=[FileOp(rel, dumps(vol_fm.model_dump(exclude_none=True),
                                      f"\n{data.get('outline', '')}\n"))],
        ))
        return vol_fm
    raise PlanRejected("卷纲生成 3 次未过 plan_gates（fail-closed，需人工改纲）")


def check_batch_cards(
    repo: BookRepo, cards: list[ChapterCardFM], batch_start: int, batch_end: int,
) -> list[Issue]:
    """章纲机检：touch≥1（schema 已查）、钩子非空（schema）、锚点单调、跨批连续性。"""
    issues: list[Issue] = []
    anchors = timeline_anchors(repo)
    last_idx = -1
    for card in sorted(cards, key=lambda c: c.chapter):
        idx = anchors.index(card.time_anchor) if card.time_anchor in anchors else None
        if idx is not None:
            if idx < last_idx:
                issues.append(Issue("batch_anchor", "block",
                                    f"ch{card.chapter:04d} 锚点回退：{card.time_anchor}", target=card.time_anchor))
            last_idx = max(last_idx, idx)
    # 跨批连续性：本批内到期/超期的活跃条目必须被 touch
    entries = load_entries(repo)
    touched = {t for c in cards for t in c.touches}
    for e in entries.values():
        due_in_batch = e.status == "active" and e.due_ch is not None and e.due_ch <= batch_end
        if due_in_batch and e.id not in touched:
            issues.append(Issue("batch_continuity", "block",
                                f"{e.id} 将在本批内到期（due={e.due_ch}）但无推进安排", target=e.id))
    return issues


@dataclass
class BatchPlan:
    cards: list[ChapterCardFM]
    readview: str
    issues: list[Issue]


def plan_batch(repo: BookRepo, provider, vol: int, batch_start: int,
               count: int = 8, *, approve: bool = False) -> BatchPlan:
    """生成一批章纲卡 + 连读视图；approve=False 仅提案不写仓（作者批准后 --yes 落库）。"""
    _profile(repo)  # 题材 profile 必须在（rhythm 语义一致性）
    vol_rel = f"大纲/卷纲/vol{vol:02d}.md"
    if not repo.port.exists(vol_rel):
        raise PlanRejected(f"卷纲 {vol_rel} 不存在（先 plan vol）")
    vol_fm_data, vol_body = split(repo.port.read_text(vol_rel))
    vol_fm = VolOutlineFM.model_validate(vol_fm_data)
    batch_end = batch_start + count - 1
    feedback = ""
    for attempt in range(3):
        user = (
            f"【卷纲结构化字段】\n{vol_fm.model_dump_json(exclude_none=True, indent=1)}\n\n"
            f"【卷纲散文】\n{vol_body.strip()[:1500]}\n\n"
            f"【条目账本快照】\n{_entries_snapshot(repo, batch_start)}\n\n"
            f"【本批范围】ch{batch_start:04d} - ch{batch_end:04d}，共 {count} 章\n{feedback}"
        )
        res = provider.complete_structured(tier=PLAN_TIER, schema_name="plan_batch",
                                           system=prompts.PLAN_BATCH_SYSTEM, user=user)
        try:
            cards = [ChapterCardFM.model_validate({**c, "spec_stage": "chapter_card"})
                     for c in res.data.get("cards", [])]
        except Exception as e:
            feedback = f"上一次生成 schema 不合法：{e}"
            continue
        if len(cards) != count:
            feedback = f"需要 {count} 张章纲卡，实得 {len(cards)} 张。"
            continue
        issues = check_batch_cards(repo, cards, batch_start, batch_end)
        if not [i for i in issues if i.level == "block"]:
            return _finalize_batch(repo, cards, batch_start, batch_end, approve)
        feedback = "上一次生成违反章纲机检：\n" + "\n".join(f"- [{i.rule}] {i.msg}" for i in issues)
    raise PlanRejected("章纲卡生成 3 次未过机检（fail-closed）")


def _finalize_batch(repo: BookRepo, cards: list[ChapterCardFM], batch_start: int,
                    batch_end: int, approve: bool) -> BatchPlan:
    """连读视图：8 章『开启→推进→兑付』链路。"""
    entries = load_entries(repo)
    lines = [f"【批次连读视图】ch{batch_start:04d}-{batch_end:04d}"]
    for c in cards:
        acts = []
        for t in c.touches:
            e = entries.get(t)
            act = "兑付" if (e and e.due_ch is not None and e.due_ch <= c.chapter) else "推进"
            acts.append(f"{act}:{t}")
        lines.append(f"- ch{c.chapter:04d} [{c.hook_type}/{c.word_tier}] "
                     f"{'、'.join(acts) or '豁免'}｜{c.time_anchor}")
    readview = "\n".join(lines)
    if not approve:
        return BatchPlan(cards=cards, readview=readview, issues=[])
    files = [FileOp(f"大纲/章纲/ch{c.chapter:04d}.md",
                    dumps(c.model_dump(exclude_none=True), "\n（章纲散文见决策卡提案）\n"))
             for c in cards]
    settle_run(repo.port, SettleInput(
        message=f"batch({batch_start:03d}..{batch_end:03d})\n\n条目: -\n",
        files=files,
    ))
    return BatchPlan(cards=cards, readview=readview, issues=[])
