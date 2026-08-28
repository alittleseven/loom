"""双审（M7 定型的输入构成；令牌绑定防张冠李戴）。

事实审 = 草稿全文 + 合同段 + 活跃条目切片；
编辑审 = 草稿全文 + 风格段 + 前章承接段（各 ≈5.5k）。
与"机检先行"分工：设定违例/泄密/专名已由机检把守，双审只管脚本算不了的
逻辑矛盾、叙事断裂与钩子失效。审稿结果以 sha256 绑定被审草稿（C2）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from loom.core import ledger as ledger_mod
from loom.core.checks.checks import load_entries

REVIEW_TIER = "review"
from loom.core.prep.prep import Pack
from loom.core.repo.layout import BookRepo
from loom.edge import prompts


@dataclass
class ReviewOutcome:
    issues: list[dict] = field(default_factory=list)
    blocked: bool = False
    draft_sha256: str = ""
    model: str = ""
    usage: dict = field(default_factory=dict)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _active_entries_slice(repo: BookRepo, limit: int = 8) -> str:
    entries = load_entries(repo)
    lines = [f"{e.id}（{e.kind}/{e.strength}/期限{e.due_ch}）" for e in entries.values()
             if e.status == "active"][:limit]
    return "\n".join(lines) or "（无活跃条目）"


def _prev_hook(repo: BookRepo, chapter: int) -> str:
    rel = f"定稿/摘要/ch{chapter - 1:04d}.md"
    if chapter > 1 and repo.port.exists(rel):
        from loom.core.repo.frontmatter import split

        _fm, body = split(repo.port.read_text(rel))
        return " ".join(body.split())[:400]
    return "（本章为开局章，无前章承接）"


def _style_seg(pack: Pack) -> str:
    return pack.slots.get("style", "（无风格段）")


def run_reviews(
    repo: BookRepo, provider, chapter: int, draft: str, pack: Pack,
    contract: list[str],
) -> ReviewOutcome:
    contract_seg = "\n".join(f"- {c}" for c in contract) or "- （无）"
    fact_user = (f"【草稿全文】\n{draft}\n\n【合同段】\n{contract_seg}\n\n"
                 f"【活跃条目切片】\n{_active_entries_slice(repo)}")
    edit_user = (f"【草稿全文】\n{draft}\n\n【风格段】\n{_style_seg(pack)}\n\n"
                 f"【前章承接段】\n{_prev_hook(repo, chapter)}")

    fact = provider.complete_structured(tier=REVIEW_TIER, schema_name="review_fact",
                                        system=prompts.FACT_REVIEW_SYSTEM, user=fact_user)
    edit = provider.complete_structured(tier=REVIEW_TIER, schema_name="review_edit",
                                        system=prompts.EDIT_REVIEW_SYSTEM, user=edit_user)
    issues = list(fact.data.get("issues", [])) + list(edit.data.get("issues", []))
    usage = {"in": fact.usage_in + edit.usage_in, "out": fact.usage_out + edit.usage_out}
    ledger_mod.append_signal(repo, "review_disposition", {
        "chapter": chapter, "issues": len(issues),
        "blocked": any(i.get("severity") == "block" for i in issues),
        "disposition": "pending",
    })
    return ReviewOutcome(
        issues=issues,
        blocked=any(i.get("severity") == "block" for i in issues),
        draft_sha256=_sha256(draft),
        model=fact.model,
        usage=usage,
    )
