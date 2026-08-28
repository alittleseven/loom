"""fantasy01 条目结转回填：34 章正文的 entry_changes 依据正文关键词判定。

条目 → 关键词 → 开账章（来自校对脚本立账）：
  F-001 天裂真相/熔炉来历：熔炉、天裂                （开 ch1，期 80）
  F-002 补给线隐患：    存粮、物资、粮食、补给        （开 ch10，期 45）
  F-003 灵气风暴：      灵气风暴、风暴、灵气          （开 ch30，期 45）
  R-001 苏小白×林知夏：  林知夏、知夏                  （开 ch6， 期 40）

正文文件 append-only → 走显式 retcon(001) 事务（正文 body 一字不动，只回填 front matter）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loom.core import ledger as ledger_mod
from loom.core.ports import GitRepoPort
from loom.core.repo.frontmatter import dumps, split
from loom.core.repo.layout import BookRepo
from loom.core.settle.transaction import FileOp, SettleInput
from loom.core.settle.transaction import run as settle_run

ROOT = "C:/lgq/ai-workspace/projects/loom-books/fantasy01"
CHAPTERS = range(1, 35)
RULES = {
    "F-001": {"opened": 1, "keywords": ("熔炉", "天裂")},
    "F-002": {"opened": 10, "keywords": ("存粮", "物资", "粮食", "补给")},
    "F-003": {"opened": 30, "keywords": ("灵气风暴", "风暴", "灵气")},
    "R-001": {"opened": 6, "keywords": ("林知夏", "知夏")},
}


def main() -> None:
    book = BookRepo(GitRepoPort(ROOT))
    port = book.port

    touches: dict[str, list[int]] = {eid: [] for eid in RULES}
    files: list[FileOp] = []

    for ch in CHAPTERS:
        rel = f"定稿/正文/ch{ch:04d}.md"
        fm, body = split(port.read_text(rel))
        changes = []
        for eid, rule in RULES.items():
            if ch < rule["opened"]:
                continue
            if ch == rule["opened"] or any(k in body for k in rule["keywords"]):
                action = "+" if ch == rule["opened"] else "~"
                changes.append({"id": eid, "action": action})
                touches[eid].append(ch)
        fm["entry_changes"] = changes
        files.append(FileOp(rel, dumps(fm, body)))

    # 账本 last_touched 更新（正文判定结果回写三本账）
    for eid, chans in touches.items():
        if not chans:
            continue
        kind_dir = {"F": "伏笔", "S": "悬念", "R": "感情线"}[eid[0]]
        rel = f"大纲/条目/{kind_dir}/{eid}.md"
        fm, body = split(port.read_text(rel))
        fm["last_touched_ch"] = max(chans)
        files.append(FileOp(rel, dumps(fm, body)))

    result = settle_run(port, SettleInput(
        message=("retcon(001)\n\n"
                 "分析：受影响条目 F-001 F-002 F-003 R-001——仅回填 front matter 的\n"
                 "entry_changes 结转声明与账本 last_touched_ch，34 章正文 body 未动一字。\n\n"
                 "条目: +F-001 +F-002 +F-003 +R-001\n"),
        files=files, retcon=1, chapter=1,
    ))
    ledger_mod.append_signal(book, "retcon", {
        "chapter": 1, "reason": "迁移校对：34 章 front matter 条目结转回填",
        "files": len(files), "commit": result.commit,
    })

    print(f"retcon(001) 提交：{result.commit[:12]}（{len(files)} 文件）\n")
    for eid, chans in touches.items():
        opened = RULES[eid]["opened"]
        tail = ",".join(str(c) for c in chans[-6:])
        print(f"{eid}（开{opened}）：{len(chans)} 章 touch，最后 @ {max(chans)}  [{tail}…]")


if __name__ == "__main__":
    main()
