"""一次性校对脚本：fantasy01 迁移后补全（依据 v6 时间线表 + 设定卡）。

1. 从 大纲/第1卷-时间线.md 回填每章正文 front matter 的 time_anchor；
2. 生成 loom-1 时间线账本（章/book_time/event/present，C3 在场列尽力解析）；
3. 设定触发器补全：从卡片正文抽 ## 名字；删掉误迁移的 README/索引卡。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loom.core.repo.frontmatter import dumps, split
from loom.core.repo.layout import BookRepo
from loom.core.ports import GitRepoPort

ROOT = Path("C:/lgq/ai-workspace/projects/loom-books/fantasy01")
V6 = Path("C:/lgq/workspace/opc_space/projects/webnovel-projects/fantasy01")


def parse_timeline() -> dict[int, dict]:
    """解析 v6 时间线表：{章号: {anchor, event}}。"""
    text = (V6 / "大纲" / "第1卷-时间线.md").read_text(encoding="utf-8")
    out: dict[int, dict] = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*第(\d+)章\s*\|\s*([^|]+?)\s*\|\s*[^|]*\|\s*[^|]*\|\s*[^|]*\|\s*([^|]*?)\s*\|", line)
        if m:
            ch = int(m.group(1))
            out[ch] = {"anchor": m.group(2).strip(), "event": m.group(3).strip()}
    return out


def main() -> None:
    book = BookRepo(GitRepoPort(ROOT))
    port = book.port
    timeline = parse_timeline()
    print(f"解析时间线：{len(timeline)} 章")

    # ---- 1. 回填正文锚点 + 生成时间线账本 ----
    files: list[tuple[str, str]] = []
    for ch, info in sorted(timeline.items()):
        rel = f"定稿/正文/ch{ch:04d}.md"
        if not port.exists(rel):
            continue
        fm, body = split(port.read_text(rel))
        fm["time_anchor"] = info["anchor"]
        files.append((rel, dumps(fm, body)))
        # 在场人物：从事件描述里抽已知角色名
        present = [n for n in ("苏小白", "林知夏", "周建军", "唐小满", "陆广坤", "老六", "熊哥")
                   if n in (info["event"] or "") or (n == "苏小白")]
        files.append((
            f"定稿/设定/时间线/ch{ch:04d}.md",
            dumps({"id": f"set-tl-ch{ch:04d}", "family": "时间线", "status": "active",
                   "ch": ch, "book_time": info["anchor"],
                   "event": info["event"] or f"第{ch}章", "present": present}, ""),
        ))
    # 摘要也要 front matter 一致性（无锚点字段，跳过）

    # ---- 2. 设定触发器补全 ----
    NAME_MAP = {
        "主角卡": ("角色", "苏小白", ["苏小白", "小白"]),
        "女主卡": ("角色", "林知夏", ["林知夏", "知夏"]),
        "配角卡": ("角色", "周建军", ["周建军", "老周", "唐小满", "陆广坤", "老六", "熊哥"]),
        "反派设计": ("角色", "熊哥", ["熊哥", "妖物"]),
        "世界观": ("世界观", "末世", ["末世", "天裂", "灵气"]),
        "力量体系": ("世界观", "力量体系", ["炼气", "灾厄", "熔炉", "吃灾"]),
    }
    for stem, (family, name, triggers) in NAME_MAP.items():
        rel = f"定稿/设定/{family}/v6-{stem}.md"
        if not port.exists(rel):
            continue
        fm, body = split(port.read_text(rel))
        fm["triggers"] = triggers
        fm["status"] = "active"
        body = body.replace("> [待校对] 触发器关键词仅含名字，建议按别名/称号补充。",
                            f"> 触发器已按 v6 卡片补全：{triggers}")
        files.append((rel, dumps(fm, body)))

    # ---- 3. 删掉误迁移的 README/索引卡 ----
    for junk in ("定稿/设定/世界观/v6-README.md", "定稿/设定/世界观/v6-索引.md"):
        if port.exists(junk):
            files.append((junk, None))

    # ---- 4. 补条目账本：从节拍表无法自动定的先立 3 条已知伏笔（status=tentative 待作者确认）----
    known_entries = [
        ("F-001", "天裂的真相：灵气风暴为何而来、熔炉从何而来", 1, 80),
        ("F-002", "存粮倒计时化解后，庇护所补给线的长期隐患", 10, 45),
        ("F-003", "灵气风暴登陆（D-10 倒计时，第45章触发）", 30, 45),
        ("R-001", "苏小白 × 林知夏：书店救援结成的小队羁绊走向", 6, 40),
    ]
    for eid, desc, opened, due in known_entries:
        kind_dir = {"F": "伏笔", "S": "悬念", "R": "感情线"}[eid[0]]
        kind = {"F": "伏笔", "S": "悬念", "R": "感情线"}[eid[0]]
        files.append((
            f"大纲/条目/{kind_dir}/{eid}.md",
            dumps({"id": eid, "kind": kind, "strength": "high" if eid != "R-001" else "mid",
                   "status": "tentative", "opened_ch": opened, "due_ch": due,
                   "last_touched_ch": opened}, f"{desc}\n\n> 待作者确认（依据 v6 节拍表/时间线倒计时事件立账）。\n"),
        ))

    sha_files = {rel: (None if content is None else port.stage_blob(content)) for rel, content in files}
    sha = port.commit_tree(sha_files, "fix(手改)\n\n校对补全：时间线回填+触发器+条目立账\n\n条目: +F-001 +F-002 +F-003 +R-001\n")
    port.move_ref(sha)
    port.worktree_sync()
    print(f"校对提交：{sha[:12]}（{len(files)} 个文件操作）")


if __name__ == "__main__":
    main()
