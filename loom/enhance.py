"""P5 增强：CLI 编排层——合成压测（300 章 pack 恒定验证）+ 成本面板。

Book Map（L0 骨架/完整版）实现已下沉 core/prep/bookmap.py（第二轮审阅 P2-2，
消除 core → 包根的反向依赖）；本模块只做命令入口编排。
"""
from __future__ import annotations

from loom.core import ledger as ledger_mod
from loom.core.repo.layout import BookRepo


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
    """合成压测书：chapters 章摘要 + 时间线 + 条目 touch（确定性合成，无 LLM）。

    写入经 settle 事务过所有权矩阵（审阅报告 四.3，不绕行 port 直写）。
    """
    port = repo.port
    from loom.core.repo.frontmatter import dumps as fm_dumps
    from loom.core.settle.transaction import FileOp, SettleInput
    from loom.core.settle.transaction import run as settle_run

    files: list[FileOp] = []
    for ch in range(1, chapters + 1):
        files.append(FileOp(f"定稿/摘要/ch{ch:04d}.md",
                            fm_dumps({"chapter": ch, "word_count": 3000},
                                     f"第{ch}章：合成的第{ch}章情节推进，主角应对危机{ch}。承接点{ch}\n")))
        files.append(FileOp(f"定稿/设定/时间线/ch{ch:04d}.md",
                            fm_dumps({"id": f"set-tl-ch{ch:04d}", "family": "时间线", "status": "active",
                                      "ch": ch, "book_time": f"历{ch}", "event": f"事件{ch}",
                                      "present": ["苏小白"]}, "")))
    vols = (chapters + 39) // 40
    for v in range(1, vols + 1):
        files.append(FileOp(f"定稿/卷摘要/vol{v:02d}.md",
                            fm_dumps({"vol": v, "source_chapters": [(v - 1) * 40 + 1, min(v * 40, chapters)]},
                                     f"合成卷{v}摘要\n")))
    from loom.core.repo.frontmatter import dumps as d

    for i in range(1, 31):
        files.append(FileOp(f"大纲/条目/伏笔/F-{i:03d}.md",
                            d({"id": f"F-{i:03d}", "kind": "伏笔", "strength": "high", "status": "active",
                               "opened_ch": (i - 1) * 10 + 1, "due_ch": min((i - 1) * 10 + 30, chapters),
                               "last_touched_ch": min((i - 1) * 10 + 5, chapters)}, f"合成伏笔{i}\n")))
    settle_run(port, SettleInput(message="fix(手改)\n\n合成压测数据\n", files=files))


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
