"""卷一卷纲 front matter 补全：全部字段依据 v6 节拍表与时间线（80 章锚点）。

依据：
- start/end：节拍表"章节范围: 第 1-80 章"
- time_span：卷级时间设定"末世第1天清晨 ~ 第36天夜"（= ch1/ch80 锚点）
- climax_chapters：五段危机链节点 + 中段反转(52) + All Is Lost(68) + 卷末兑现(74/77/80)，
  并按节拍内部小高潮加密到间距 ≤8（gate3 节奏预算）
- entry_plan：四条已立账目（F-001/002/003、R-001）的开账/期限章
- chapter_types：按时间线逐章事件标注（感情=人情/情绪章，side=日常/准备/休整，
  climax=危机链峰值），比例经 gate6 红线校验
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loom.core.checks.checks import load_entries, load_profile, run_plan_gates, timeline_anchors
from loom.core.repo.frontmatter import dumps, split
from loom.core.repo.layout import BookRepo
from loom.core.ports import GitRepoPort
from loom.core.repo.schema import VolOutlineFM
from loom.core.settle.transaction import FileOp, SettleInput, run as settle_run

ROOT = "C:/lgq/ai-workspace/projects/loom-books/fantasy01"

CLIMAX_CHAPTERS = [5, 8, 13, 20, 24, 26, 29, 31, 38, 42, 45, 50, 52, 56,
                   59, 62, 68, 70, 74, 77, 80]

ROMANCE = [3, 6, 19, 40, 51, 53, 67, 78]          # 人情/情绪章（末世第1天首夜、救林知夏、
#   林知夏管账、灾前夜·情感线、假胜利欢呼、人心动摇、人心浮动、人心重聚）
SIDE = [2, 11, 14, 15, 16, 22, 27, 28, 32, 33, 39]  # 日常/准备/休整/修行/世界观铺垫
CLIMAX_TYPE = [5, 8, 13, 24, 26, 42, 45, 50, 52, 56, 59, 64, 68, 71, 74, 77, 80]

ENTRY_PLAN = [
    {"id": "F-001", "action": "开启", "due_chapter": 80},   # 天裂真相：卷末"天劫"点亮
    {"id": "F-002", "action": "开启", "due_chapter": 45},   # 补给线：风暴期检验
    {"id": "F-003", "action": "开启", "due_chapter": 45},   # 灵气风暴：ch45 降临
    {"id": "R-001", "action": "开启", "due_chapter": 40},   # 苏小白×林知夏：灾前夜
]


def chapter_types() -> dict[str, str]:
    out: dict[str, str] = {}
    for ch in range(1, 81):
        if ch in CLIMAX_TYPE:
            out[f"ch{ch:04d}"] = "climax"
        elif ch in ROMANCE:
            out[f"ch{ch:04d}"] = "romance"
        elif ch in SIDE:
            out[f"ch{ch:04d}"] = "side"
        else:
            out[f"ch{ch:04d}"] = "main"
    return out


def main() -> None:
    book = BookRepo(GitRepoPort(ROOT))
    port = book.port
    rel = "大纲/卷纲/vol01.md"
    fm, body = split(port.read_text(rel))

    fm.update({
        "start_ch": 1,
        "end_ch": 80,
        "climax_chapters": CLIMAX_CHAPTERS,
        "entry_plan": ENTRY_PLAN,
        "time_span": {"start": "末世第1天 清晨", "end": "末世第36天 夜"},
        "chapter_types": chapter_types(),
    })
    fm.pop("migrated_from", None)
    body = body.replace(
        "> [待校对] 结构化字段（高潮点/条目计划/时间锚点/章节类型）"
        "未映射——建议运行 loom plan vol 重生成后再人工核对。",
        "> 结构化字段已按节拍表（五段危机链/中段反转/卷末兑现）与时间线（80 章锚点）补全；"
        "随写作演进可修订。")

    # 六道机检校验补全结果（R5 阈值回测）
    vol_fm = VolOutlineFM.model_validate(fm)
    issues = run_plan_gates(vol_fm, load_entries(book), load_profile(book), timeline_anchors(book))
    print("plan_gates 校验：")
    for i in issues:
        print(f"  [{i.level}] {i.rule}: {i.msg}")
    if any(i.level == "block" for i in issues):
        raise SystemExit("补全结果未过六道机检，拒绝写入")

    files = [FileOp(rel, dumps(fm, body))]
    settle_run(port, SettleInput(
        message=("vol(01)\n\n卷一卷纲 front matter 补全：依据节拍表（五段危机链/中段反转/\n"
                 "卷末兑现）与时间线（80 章锚点）；高潮点间距与配比经 gate3/gate6 校验\n\n条目: -\n"),
        files=files))
    print("vol(01) 已提交")


if __name__ == "__main__":
    main()
