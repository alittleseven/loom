"""Book Map（P5）：L0 全书骨架 + 完整版（当前卷定位 + 在场人物 + 反复读清单）。

落位 core/prep（第二轮审阅 P2-2）：pack 的 bookmap 槽位消费方在本包，
实现随之下沉，消除 core → 包根工具模块（loom.enhance）的反向依赖；
loom.enhance 仅保留 CLI 编排（enhance 命令 / 合成压测 / pack 恒定检查）。
"""
from __future__ import annotations

from loom.core.checks.checks import load_entries
from loom.core.repo.frontmatter import split
from loom.core.repo.layout import BookRepo


def build_l0_skeleton(repo: BookRepo, entries: dict | None = None) -> str:
    """L0 全书骨架：全部卷纲结构化字段压缩为 30-50 行全书地图。"""
    lines: list[str] = ["[Book Map·L0 全书骨架]"]
    vol_files = sorted(rel for rel in repo.port.list_files("大纲/卷纲") if rel.endswith(".md"))
    for rel in vol_files:
        fm, _body = split(repo.port.read_text(rel))
        climax = fm.get("climax_chapters", [])
        ts = fm.get("time_span", {})
        opens = [i for i in fm.get("entry_plan", []) if i.get("action") == "开启"]
        pays = [i for i in fm.get("entry_plan", []) if i.get("action") == "兑付"]
        lines.append(
            f"卷{fm.get('vol')}：高潮{climax}｜时间 {ts.get('start', '?')}→{ts.get('end', '?')}"
            f"｜开 {len(opens)} 条｜兑 {len(pays)} 条")
    entries = entries if entries is not None else load_entries(repo)
    top = [e for e in entries.values() if e.status == "active"][:5]
    if top:
        lines.append("活跃承诺：" + "；".join(f"{e.id}/{e.kind}" for e in top))
    return "\n".join(lines[:50])


def book_map_full(repo: BookRepo, chapter: int, entries_top: int = 5,
                  entries: dict | None = None) -> str:
    """Book Map 完整版：L0 骨架 + 当前卷定位 + 主要在场人物一行卡。"""
    skeleton = build_l0_skeleton(repo, entries)
    current = ""
    for rel in sorted(repo.port.list_files("大纲/卷纲")):
        if not rel.endswith(".md"):
            continue
        fm, _ = split(repo.port.read_text(rel))
        extra = fm.get("chapter_types", {})
        keys = sorted(extra)
        if keys and keys[0].startswith("ch") and \
           int(keys[0][2:]) <= chapter <= int(keys[-1][2:]):
            ts = fm.get("time_span", {})
            current = f"当前位置：卷{fm.get('vol')}（{ts.get('start', '?')}→{ts.get('end', '?')}）"
            break
    present: list[str] = []
    for rel in sorted(repo.port.list_files("定稿/设定/时间线")):
        if not rel.endswith(".md"):
            continue
        fm, _ = split(repo.port.read_text(rel))
        if fm.get("ch") == chapter:
            present = list(fm.get("present", []))[:5]
            break
    lines = [skeleton, current or "当前位置：（卷纲未覆盖本章）"]
    if present:
        lines.append(f"在场人物：{'、'.join(present)}")
    entries = entries if entries is not None else load_entries(repo)
    top = [e for e in entries.values() if e.status == "active"][:entries_top]
    if top:
        lines.append("反复读：" + "；".join(f"{e.id}({e.due_ch or '-'})" for e in top))
    return "\n".join(lines)
