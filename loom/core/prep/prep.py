"""prep 上下文编译器（v3.0 §4.2.2）。

"上下文是编译出来的，不是塞进去的"：
- 槽位固定、编译序稳定 → 批次内前段槽位可命中 prompt 缓存；
- 触发式注入：名册条目带关键词触发器，本章出场才注入（成本 O(本章出场)）；
- 信息差过滤：读者尚不可知的内容绝不进包；
- 预算 ≤5k token（估算器：CJK×1.5 + ASCII/4），超预算按固定优先级截断；
- **确定性**：同书同章重编译 pack 字节一致（快照测试硬验收）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from loom.core.checks.checks import load_entries
from loom.core.repo.frontmatter import split
from loom.core.repo.layout import BookRepo
from loom.core.repo.schema import ChapterCardFM

BUDGET_DEFAULT = 5000
STRENGTH_ORDER = {"high": 0, "mid": 1, "low": 2}


def estimate_tokens(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    ascii_len = len(re.sub(r"[\u4e00-\u9fff\s]", "", text))
    return int(cjk * 1.5 + ascii_len / 4)


@dataclass
class Pack:
    chapter: int
    slots: dict[str, str] = field(default_factory=dict)
    budget: int = BUDGET_DEFAULT

    @property
    def text(self) -> str:
        return "\n\n".join(self.slots[k] for k in sorted(self.slots))

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def _load_active_golden_lines(repo: BookRepo, scenario: str) -> list[str]:
    lines: list[str] = []
    for rel in sorted(repo.port.list_files("文风/金句库")):
        if not rel.endswith(".md"):
            continue
        fm, _ = split(repo.port.read_text(rel))
        if scenario != "default" and str(fm.get("scene", "")) != scenario:
            continue
        for item in fm.get("lines", []) or []:
            if item.get("status") == "active":
                lines.append(str(item.get("text", "")))
    return lines[:3]


def _fact_slices(repo: BookRepo, brief_text: str) -> list[str]:
    """触发式注入。信息差条目永不直接进包（事实走结构化查询，泄密由机检把守）。"""
    injected: list[str] = []
    for rel in sorted(repo.port.list_files("定稿/设定")):
        if not rel.endswith(".md"):
            continue
        fm, body = split(repo.port.read_text(rel))
        if fm.get("family") == "信息差":
            continue
        name = str(fm.get("name") or "")
        triggers = [t for t in (fm.get("triggers", []) or []) if t]
        if not name and not triggers:
            continue
        if any(t in brief_text for t in ([name] if name else []) + triggers):
            head = body.strip().splitlines()[0] if body.strip() else ""
            injected.append(f"{name or rel.stem}：{head}")
    return injected


def _recent_summaries(repo: BookRepo, chapter: int, k: int = 3) -> list[str]:
    out: list[str] = []
    for ch in range(chapter - 1, max(chapter - k - 1, 0), -1):
        rel = f"定稿/摘要/ch{ch:04d}.md"
        if repo.port.exists(rel):
            _fm, body = split(repo.port.read_text(rel))
            out.append(f"第{ch}章摘要：{' '.join(body.split())[:150]}")
    return out


def _entries_top(entries: dict, n: int = 5) -> list[str]:
    active = [e for e in entries.values() if e.status == "active"]
    active.sort(key=lambda e: (STRENGTH_ORDER.get(e.strength, 3),
                               e.due_ch if e.due_ch is not None else 9999, e.id))
    return [f"{e.id}（{e.kind}/{e.strength}，期限章 {e.due_ch or '无'}）" for e in active[:n]]


def _book_map(repo: BookRepo, entries: dict) -> str:
    lines = ["[Book Map·骨架版]"]
    for rel in sorted(repo.port.list_files("大纲/卷纲")):
        if rel.endswith(".md"):
            fm, _ = split(repo.port.read_text(rel))
            lines.append(f"- 卷{fm.get('vol')}：高潮点 {fm.get('climax_chapters', [])}，"
                         f"时间跨度 {fm.get('time_span', {}).get('start', '?')}→{fm.get('time_span', {}).get('end', '?')}")
            break  # 骨架版只挂当前卷（最早卷号，sorted 保证确定性）
    top = _entries_top(entries, 5)
    if top:
        lines.append(f"- 活跃条目 Top：{'；'.join(top)}")
    return "\n".join(lines)


def compile_pack(
    repo: BookRepo,
    chapter: int,
    card: ChapterCardFM | None = None,
    contract: list[str] | None = None,
    *,
    scenario: str = "default",
    budget: int = BUDGET_DEFAULT,
) -> Pack:
    """编译本章 pack。输入只含书仓源文件 + 章纲卡，无时间戳等不稳定因素。"""
    contract = contract or (["本章按章纲卡推进"] if card else [])
    entries = load_entries(repo)

    constitution_rel = "文风/风格宪法.md"
    style_summary = ""
    if repo.port.exists(constitution_rel):
        fm, _ = split(repo.port.read_text(constitution_rel))
        style_summary = "禁用词：" + "、".join(fm.get("banned_words", []) or []) or "（暂无）"

    brief_text = "\n".join([card.time_anchor, *contract] if card else list(contract))
    if card:
        card_file = _card_text(repo, card)
        if card_file:
            _fm_card, card_body = split(card_file)
            brief_text += "\n" + card_body
    facts = _fact_slices(repo, brief_text)

    slots: dict[str, str] = {
        "style": f"[风格段]\n{style_summary}\n同场景金句示例：\n" + "\n".join(
            f"- {ln}" for ln in _load_active_golden_lines(repo, scenario)),
        "contract": "[合同段·本章必须兑现]\n" + "\n".join(f"- {c}" for c in contract),
        "bookmap": _book_map(repo, entries),
        "facts": "[事实切片·本章出场实体]\n" + ("\n".join(f"- {f}" for f in facts) or "- （未命中触发器）"),
        "recent": "[近期段]\n" + ("\n".join(_recent_summaries(repo, chapter)) or "- （开局章）"),
        "entries": "[反复读清单·活跃条目]\n" + ("\n".join(f"- {t}" for t in _entries_top(entries)) or "- （无）"),
        "task": f"[任务]\n撰写第 {chapter} 章正文。遵守合同段全部断言；章末必须有钩子；"
                f"锚点：{card.time_anchor if card else '顺延前章'}；场景数：{card.scenes if card else 2}。",
    }

    pack = Pack(chapter=chapter, slots=slots, budget=budget)
    return _truncate(pack)


def _card_text(repo: BookRepo, card: ChapterCardFM) -> str | None:
    rel = f"大纲/章纲/ch{card.chapter:04d}.md"
    if repo.port.exists(rel):
        return repo.port.read_text(rel)
    return None


_TRUNCATE_ORDER = ("entries", "recent", "facts")  # 超预算时的牺牲序


def _truncate(pack: Pack) -> Pack:
    for key in _TRUNCATE_ORDER:
        if pack.tokens <= pack.budget:
            return pack
        lines = [ln for ln in pack.slots[key].splitlines() if ln.strip()]
        if len(lines) > 2:
            pack.slots[key] = "\n".join(lines[: max(len(lines) // 2, 2)]) + "\n…（预算截断）"
    if pack.tokens > pack.budget:  # 可截断槽位到底仍超预算 → 显式标记（固定槽位不可牺牲）
        pack.slots["task"] += "\n…（预算截断：固定槽位已到底，需人工干预）"
    return pack
