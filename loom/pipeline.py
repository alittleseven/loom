"""单章写作环流水线（v3.0 §4.2）：决策卡 → 上下文编译 → 渲染 → 机检 → 双审 → 结算。

fail-closed：机检重试 ≤2、评审阻断重渲染 ≤1，耗尽即 PipelineHalted（工作区原样保留）。
结算两次落库：settle（正文+条目 touch+审计链）→ scribe（摘要+时间线+指纹）。
signals 埋点随各环节同步（M3）：card_action / gate_block / review_disposition / settle_diff。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from loom.core import ledger as ledger_mod
from loom.core.checks.checks import (
    ChapterContext,
    Issue,
    load_entries,
    run_checks,
)
from loom.core.prep.prep import compile_pack
from loom.core.repo.frontmatter import dumps, split
from loom.core.repo.layout import BookRepo, entry_rel
from loom.core.repo.schema import ChapterCardFM, ManuscriptFM
from loom.core.settle.transaction import FileOp, SettleInput
from loom.core.settle.transaction import run as settle_run
from loom.edge import prompts
from loom.edge import scribe as scribe_mod
from loom.edge.renderer import render_chapter
from loom.edge.reviewers import run_reviews

SEAM_VERSION = "1"
MANUSCRIPT_BODY_LIMIT = 20000


class PipelineHalted(RuntimeError):
    def __init__(self, msg: str, issues: list[Issue] | None = None) -> None:
        super().__init__(msg)
        self.issues = issues or []


@dataclass
class ChapterResult:
    chapter: int
    commit: str
    scribe_commit: str
    model: str
    render_attempts: int
    check_issues: int
    review_issues: int
    usage: dict = field(default_factory=dict)


def project_decision_card(repo: BookRepo, card: ChapterCardFM, contract: list[str]) -> str:
    """L2 档：决策卡由章纲卡模板化投影（零 LLM，§4.1）。写入工作区（缝协议带版本）。"""
    fm = {
        "spec_stage": "decision_card", "seam_version": SEAM_VERSION,
        "chapter": card.chapter, "generated_by": "plan_template",
        "touch_waiver": None, "contract": contract, "options": [],
    }
    body = (
        f"## 盘面\n（由 pack 呈现：活跃条目/时间线/近期剧情）\n\n"
        f"## 提案\n场景数 {card.scenes}；锚点 {card.time_anchor}；"
        f"touch {'、'.join(card.touches) or '（豁免章）'}\n\n"
        f"## 合同\n" + "\n".join(f"- {c}" for c in contract) + "\n\n"
        "## 备选\n（无）\n"
    )
    text = dumps(fm, body)
    repo.write_file(f"工作区/决策卡/ch{card.chapter:04d}.md", text, actor="prep")
    return text


def _card_body(repo: BookRepo, chapter: int) -> str | None:
    rel = f"大纲/章纲/ch{chapter:04d}.md"
    if repo.port.exists(rel):
        _fm, body = split(repo.port.read_text(rel))
        return body
    return None


def _entry_ops(repo: BookRepo, card: ChapterCardFM, chapter: int) -> tuple[list[FileOp], list[str]]:
    """条目结转：last_touched_ch 更新；到期条目兑付（$）；signs 供 commit 协议行。"""
    ops: list[FileOp] = []
    signs: list[str] = []
    entries = load_entries(repo)
    for eid in card.touches:
        e = entries.get(eid)
        if e is None:
            continue
        rel = entry_rel(eid)
        fm, body = split(repo.port.read_text(rel))
        fm["last_touched_ch"] = chapter
        action = "$" if (e.due_ch is not None and e.due_ch <= chapter) else "~"
        if action == "$":
            fm["status"] = "paid"
        signs.append(f"{action}{eid}")
        ops.append(FileOp(rel, dumps(fm, body)))
    return ops, signs


def run_chapter(
    repo: BookRepo, provider, card: ChapterCardFM, contract: list[str], *,
    autonomy: str = "L1", words: int = 3000,
) -> ChapterResult:
    chapter = card.chapter
    ledger_mod.append_signal(repo, "card_action",
                             {"chapter": chapter, "action": "auto_project",
                              "generated_by": "plan_template", "autonomy": autonomy})
    project_decision_card(repo, card, contract)
    pack = compile_pack(repo, chapter, card, contract)
    card_text = _card_body(repo, chapter)
    entry_ops, signs = _entry_ops(repo, card, chapter)

    def build_ms(draft: str) -> ManuscriptFM:
        changes = [{"id": op.rel.split("/")[-1][:-3], "action": s[0]}
                   for op, s in zip(entry_ops, signs)]
        return ManuscriptFM(
            spec_stage="manuscript", chapter=chapter, title=f"第{chapter}章",
            time_anchor=card.time_anchor, entry_changes=changes,
            contract_digest=contract, word_count=len(draft),
        )

    def checks_for(draft: str) -> list[Issue]:
        return run_checks(repo, ChapterContext(
            chapter=chapter, draft=draft, manuscript=build_ms(draft),
            card=card, contract=contract,
        ))

    # ---- 渲染 + 机检（重试 ≤2；附错误反馈）----
    rr = None
    issues: list[Issue] = []
    feedback = ""
    for attempt in range(3):
        rr = render_chapter(provider, pack, card_text, words=words, feedback=feedback)
        issues = checks_for(rr.draft)
        blocks = [i for i in issues if i.level == "block"]
        if not blocks:
            break
        feedback = prompts.check_feedback(blocks)
    else:
        for i in issues:
            ledger_mod.append_signal(repo, "gate_block", {"chapter": chapter, **i.five_tuple()})
        raise PipelineHalted(f"第 {chapter} 章机检重试耗尽（fail-closed）", issues)

    for i in issues:  # 全量埋点（含 warn；作者可在 P4 标误报）
        ledger_mod.append_signal(repo, "gate_block", {"chapter": chapter, **i.five_tuple()})

    # ---- 双审（阻断 → 重渲染 ≤1 次）----
    total_renders = attempt + 1
    outcome = run_reviews(repo, provider, chapter, rr.draft, pack, contract)
    if outcome.blocked:
        total_renders += 1
        review_feedback = "\n".join(f"- {i.get('desc')}（{i.get('quote', '')}）"
                                    for i in outcome.issues if i.get("severity") == "block")
        rr = render_chapter(provider, pack, card_text, words=words,
                            feedback=f"评审阻断，必须修正：\n{review_feedback}")
        issues = checks_for(rr.draft)
        if any(i.level == "block" for i in issues):
            raise PipelineHalted(f"第 {chapter} 章评审阻断后重渲染仍机检失败", issues)
        outcome = run_reviews(repo, provider, chapter, rr.draft, pack, contract)
        if outcome.blocked:
            raise PipelineHalted(f"第 {chapter} 章评审阻断，重渲染 1 次后仍阻断", )

    # ---- 结算（正文 + 条目 touch + 审计链；哈希防串稿绑定）----
    body = rr.draft[:MANUSCRIPT_BODY_LIMIT]
    ms = build_ms(body)
    entry_line = " ".join(signs) if signs else "-"
    files = [FileOp(f"定稿/正文/ch{chapter:04d}.md", dumps(ms.model_dump(exclude_none=True), body + "\n")),
             *entry_ops]
    result = settle_run(repo.port, SettleInput(
        message=f"ch({chapter:03d})\n\n条目: {entry_line}\n",
        files=files,
        draft_content=body,
        reviewed_sha256=outcome.draft_sha256,
        chapter=chapter,
        ledger_events=(
            {"event": "render_call", "chapter": chapter, "model": rr.model,
             "usage": {"in": rr.usage_in, "out": rr.usage_out}},
            {"event": "review_call", "chapter": chapter, "usage": outcome.usage},
        ),
    ))

    # ---- scribe 第二次落库 ----
    sc = scribe_mod.scribe_commit(repo, provider, chapter, body)
    ledger_mod.append_signal(repo, "settle_diff",
                             {"chapter": chapter, "changed_ratio": 0.0, "autonomy": autonomy})
    planned = list(card.touches)
    actual = [ec.id for ec in ms.entry_changes]
    ledger_mod.append_signal(repo, "plan_deviation", {
        "chapter": chapter, "planned": planned, "actual": actual,
        "deviation": sorted(set(planned) ^ set(actual)),
    })

    return ChapterResult(
        chapter=chapter, commit=result.commit, scribe_commit=sc.commit,
        model=rr.model, render_attempts=total_renders,
        check_issues=len(issues), review_issues=len(outcome.issues),
        usage={"render": {"in": rr.usage_in, "out": rr.usage_out},
               "review": outcome.usage,
               "scribe": {"summary": None, "extract": None}},
    )
