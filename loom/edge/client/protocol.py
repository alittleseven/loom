"""LLMProvider 接口契约（v3.0 §5.2）：edge 全部模型调用的唯一形态。

六类单发结构化请求，无 agentic 循环。换模型 = 换实现/换配置（路由表）。
P0 只冻结协议 + 测试替身；HTTP 实现随 P1a edge 三件套落地。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from loom.core.seam import SEAM_VERSION  # noqa: F401  （缝协议版本单一来源）

# 渲染档/评审档/scribe 档/小档（v3.0 §5.3；路由表随 P1b 盲测定版）
TIERS = ("render", "review", "scribe", "small")


@dataclass
class ProviderResult:
    data: dict[str, Any]
    model: str
    usage_in: int = 0
    usage_out: int = 0
    tier: str = "small"


@runtime_checkable
class LLMProvider(Protocol):
    def complete_structured(
        self, *, tier: str, schema_name: str, system: str, user: str
    ) -> ProviderResult: ...


class ProviderCall:
    """一次调用的留痕（供 evolve 分析与测试断言）。"""

    def __init__(self, tier: str, schema_name: str, system: str, user: str) -> None:
        self.tier = tier
        self.schema_name = schema_name
        self.system = system
        self.user = user


class FakeLLMProvider:
    """LLMProvider 测试替身：按 schema_name 取脚本化响应；记录全部调用。

    scripts: schema_name → dict（响应）或 Callable(user) → dict。
    """

    def __init__(
        self,
        scripts: dict[str, Any] | None = None,
        *,
        model: str = "fake-model",
        usage: tuple[int, int] = (10, 5),
    ) -> None:
        self.scripts = scripts or {}
        self.model = model
        self.usage = usage
        self.calls: list[ProviderCall] = []

    def complete_structured(
        self, *, tier: str, schema_name: str, system: str, user: str
    ) -> ProviderResult:
        if tier not in TIERS:
            raise ValueError(f"未知模型档：{tier!r}")
        self.calls.append(ProviderCall(tier, schema_name, system, user))
        scripted = self.scripts.get(schema_name)
        if callable(scripted):
            data = scripted(user)
        elif isinstance(scripted, dict):
            data = scripted
        else:
            raise KeyError(f"FakeLLMProvider 未配置 schema_name={schema_name!r} 的响应")
        return ProviderResult(
            data=data, model=self.model, usage_in=self.usage[0], usage_out=self.usage[1], tier=tier
        )
