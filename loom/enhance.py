"""P5 增强：L0 全书骨架 + Book Map 完整版 + 合成压测（300 章 pack 恒定验证）。"""
from __future__ import annotations

from loom.core import ledger as ledger_mod
from loom.core.checks.checks import load_entries
from loom.core.repo.frontmatter import split
from loom.core.repo.layout import BookRepo


def build_l0_skeleton(repo: BookRepo) -> str:
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
    entries = load_entries(repo)
    top = [e for e in entries.values() if e.status == "active"][:5]
    if top:
        lines.append("活跃承诺：" + "；".join(f"{e.id}/{e.kind}" for e in top))
    return "\n".join(lines[:50])


def book_map_full(repo: BookRepo, chapter: int, entries_top: int = 5) -> str:
    """Book Map 完整版：L0 骨架 + 当前卷定位 + 主要在场人物一行卡。"""
    skeleton = build_l0_skeleton(repo)
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
    entries = load_entries(repo)
    top = [e for e in entries.values() if e.status == "active"][:entries_top]
    if top:
        lines.append("反复读：" + "；".join(f"{e.id}({e.due_ch or '-'})" for e in top))
    return "\n".join(lines)


def cost_dashboard(repo: BookRepo) -> str:
    """成本面板：逐章 token 账单 + 预算黄灯（单章超均值 2×）。"""
    report = ledger_mod.cost_report(repo)
    per = report["per_chapter"]
    if not per:
        return "【成本面板】（暂无账目）"
    avg = (report["total_in"] + report["total_out"]) / max(report["chapters"], 1)
    lines = [f"【成本面板】{report['chapters']} 章，合计 {report['total_in']}in/{report['total_out']}out"]
    for ch in sorted(per):
        total = per[ch]["in"] + per[ch]["out"]
        flag = " ⚠黄灯" if total > avg * 1.5 else ""
        lines.append(f"- ch{ch:03d}: {per[ch]['in']}in {per[ch]['out']}out{flag}")
    return "\n".join(lines)


def synth_book(repo: BookRepo, chapters: int = 300) -> None:
    """合成压测书：chapters 章摘要 + 时间线 + 条目 touch（确定性合成，无 LLM）。"""
    port = repo.port
    from loom.core.repo.frontmatter import dumps as fm_dumps

    files: list[tuple[str, str]] = []
    for ch in range(1, chapters + 1):
        files.append((f"定稿/摘要/ch{ch:04d}.md",
                      fm_dumps({"chapter": ch, "word_count": 3000},
                               f"第{ch}章：合成的第{ch}章情节推进，主角应对危机{ch}。承接点{ch}\n")))
        files.append((f"定稿/设定/时间线/ch{ch:04d}.md",
                      fm_dumps({"id": f"set-tl-ch{ch:04d}", "family": "时间线", "status": "active",
                                "ch": ch, "book_time": f"历{ch}", "event": f"事件{ch}",
                                "present": ["苏小白"]}, "")))
    vols = (chapters + 39) // 40
    for v in range(1, vols + 1):
        files.append((f"定稿/卷摘要/vol{v:02d}.md",
                      fm_dumps({"vol": v, "source_chapters": [(v - 1) * 40 + 1, min(v * 40, chapters)]},
                               f"合成卷{v}摘要\n")))
    from loom.core.repo.frontmatter import dumps as d

    for i in range(1, 31):
        files.append((f"大纲/条目/伏笔/F-{i:03d}.md",
                      d({"id": f"F-{i:03d}", "kind": "伏笔", "strength": "high", "status": "active",
                         "opened_ch": (i - 1) * 10 + 1, "due_ch": min((i - 1) * 10 + 30, chapters),
                         "last_touched_ch": min((i - 1) * 10 + 5, chapters)}, f"合成伏笔{i}\n")))
    sha_files = {rel: port.stage_blob(content) for rel, content in files}
    sha = port.commit_tree(sha_files, "fix(手改)\n\n合成压测数据\n")
    port.move_ref(sha)
    port.worktree_sync()


def pack_constant_check(repo: BookRepo, probe_chapters: tuple[int, int]) -> dict:
    """300 章压测硬验收：早期章与后期章的 pack token 恒定（±20%）。"""
    from loom.core.prep.prep import compile_pack

    sizes = {}
    for ch in probe_chapters:
        pack = compile_pack(repo, ch, None, contract=["含:苏小白"])
        sizes[ch] = pack.tokens
    lo_, hi_ = min(sizes.values()), max(sizes.values())
    drift = (hi_ - lo_) / max(lo_, 1)
    return {"sizes": sizes, "drift": round(drift, 3), "constant": drift <= 0.20}
