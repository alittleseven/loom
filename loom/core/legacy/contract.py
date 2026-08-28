"""合同引擎【v6 移植零件，GPL 隔离区】。

断言微型语法（全部零 LLM 可执行，N2：拒绝占位符 query）：
- `含:关键词`          —— 草稿必须包含（可逗号分隔多个，全部须命中）
- `禁:关键词`          —— 草稿禁止包含
- `字数:2600-3600`     —— 字数区间
- 无前缀的纯文本        —— 按 must_contain 处理
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PLACEHOLDER_RE = re.compile(r"\{[^}]*\}|占位|待补|TBD|章纲目标")


class ContractPlaceholderError(ValueError):
    """合同含占位符（N2 工程坑直传：拒绝渲染成 prompt 的假合同）。"""


@dataclass
class ContractItem:
    raw: str
    kind: str          # contain | forbid | words
    value: str | tuple[int, int]
    ok: bool | None = None
    detail: str = ""


def parse_assertion(raw: str) -> ContractItem:
    text = raw.strip()
    if not text:
        raise ContractPlaceholderError("空合同断言")
    if _PLACEHOLDER_RE.search(text):
        raise ContractPlaceholderError(f"合同含占位符，拒绝执行：{raw!r}")
    if text.startswith("含:"):
        return ContractItem(raw, "contain", text[2:].strip())
    if text.startswith("禁:"):
        return ContractItem(raw, "forbid", text[2:].strip())
    m = re.fullmatch(r"字数[:：](\d+)\s*-\s*(\d+)", text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            raise ContractPlaceholderError(f"字数区间颠倒：{raw!r}")
        return ContractItem(raw, "words", (lo, hi))
    return ContractItem(raw, "contain", text)


def evaluate(draft: str, assertions: list[str]) -> list[ContractItem]:
    """执行合同；返回逐条结果。断言本身非法 → 异常（fail-closed）。"""
    items = [parse_assertion(a) for a in assertions]
    for item in items:
        if item.kind == "contain":
            missing = [kw for kw in str(item.value).split("，") if kw and kw not in draft and kw not in draft.replace(",", "，")]
            item.ok = not missing
            item.detail = f"未命中：{missing}" if missing else "全部命中"
        elif item.kind == "forbid":
            hits = [kw for kw in str(item.value).split("，") if kw and kw in draft]
            item.ok = not hits
            item.detail = f"命中禁项：{hits}" if hits else "未出现"
        else:  # words
            lo, hi = item.value
            n = len(draft)
            item.ok = lo <= n <= hi
            item.detail = f"实际 {n} 字，预算 {lo}-{hi}"
    return items


def summary(items: list[ContractItem]) -> dict:
    covered = [i.raw for i in items if i.ok]
    missed = [i.raw for i in items if not i.ok]
    return {"covered": covered, "missed": missed, "total": len(items)}
