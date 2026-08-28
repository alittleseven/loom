"""渲染器：分档路由 + 机检反馈重渲染；关键章陪审团（P3 批次接入，此处单稿）。"""
from __future__ import annotations

from dataclasses import dataclass

from loom.core.prep.prep import Pack
from loom.edge import prompts
from loom.edge.client.protocol import ProviderResult

REVIEW_TIER = "review"


@dataclass
class RenderResult:
    draft: str
    model: str
    usage_in: int
    usage_out: int


def render_chapter(
    provider, pack: Pack, card_text: str | None, *,
    tier: str = "render", words: int = 3000, feedback: str = "",
) -> RenderResult:
    """渲染是单章成本大头，走裸 API（LLMProvider），不经宿主 agent。"""
    result = provider.complete_text(
        tier=tier, schema_name="manuscript",
        system=prompts.RENDER_SYSTEM,
        user=prompts.render_user(pack.text, card_text, pack.chapter, words, feedback),
    )
    text = str(result.data.get("text", "")).strip()
    if not text:
        raise ValueError("渲染返回空正文")
    return RenderResult(draft=text, model=result.model,
                        usage_in=result.usage_in, usage_out=result.usage_out)


def _usage(res: ProviderResult) -> dict:
    return {"in": res.usage_in, "out": res.usage_out}
