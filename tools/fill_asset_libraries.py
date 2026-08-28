"""fantasy01 素材库补全：

1. 迁移 v6 增强设定卡（能力/物品/战力锚点/资源，共 8 张）→ 定稿/设定/世界观/
2. 信息差账本立账（天劫、熔炉会说话、新安城真实意图）→ 泄密扫描生效
3. 文体指纹基线：按规范 §4.4 用前 30 章定基线，并回填 34 章 rolling
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loom.core.ports import GitRepoPort
from loom.core.repo.frontmatter import dumps, dumps_json, split
from loom.core.repo.layout import BookRepo
from loom.core.settle.transaction import FileOp, SettleInput
from loom.core.settle.transaction import run as settle_run
from loom.edge.scribe import compute_fingerprint

ROOT = "C:/lgq/ai-workspace/projects/loom-books/fantasy01"
V6 = Path("C:/lgq/workspace/opc_space/projects/webnovel-projects/fantasy01/设定集/增强设定")

INFO_GAPS = [
    ("set-info-tianjie", "熔炉残响说出『天劫』——灾难与修真界大劫的关联",
     ["天劫", "天劫将至"], 76, "仅苏小白听见（ch76），据点无人知晓"),
    ("set-info-ronglu", "熔炉是有自主意识的『残响』，会与苏小白对话",
     ["熔炉残响", "炉子说话"], 2, "外界只知苏小白能吃灾，不知熔炉有灵"),
    ("set-info-xinancheng", "新安城接近小白城的真实意图：夺取吞灾能力",
     ["新安城", "收编", "使者"], 34, "ch79 使者留话后苏小白起疑；对方仍以为他不知"),
]


def main() -> None:
    book = BookRepo(GitRepoPort(ROOT))
    port = book.port
    files: list[FileOp] = []

    # ---- 1. v6 增强设定卡迁移（family=世界观；力量体系/物品同族）----
    n_cards = 0
    for card in sorted(V6.rglob("*.md")):
        if card.name in ("README.md", "索引.md"):
            continue
        slug = card.stem
        text = card.read_text(encoding="utf-8")
        rel = f"定稿/设定/世界观/v6-{slug}.md"
        files.append(FileOp(rel, dumps({
            "id": f"set-v6z-{slug}", "family": "世界观", "name": slug,
            "status": "active", "triggers": [slug],
            "migrated_from": "v6增强设定",
        }, "\n" + text + "\n")))
        n_cards += 1

    # ---- 2. 信息差账本 ----
    for sid, desc, keywords, revealed_ch, known in INFO_GAPS:
        files.append(FileOp(
            f"定稿/设定/信息差/{sid}.md",
            dumps({"id": sid, "family": "信息差", "status": "active",
                   "visibility": f"revealed@{revealed_ch}",
                   "secret_keywords": keywords, "known_by": ["苏小白"]},
                  f"{desc}\n\n知情范围：{known}\n> 待作者确认（泄密扫描依据）。\n")))

    # ---- 3. 文体指纹基线（前 30 章）+ rolling 回填 ----
    fp_rel = "定稿/记忆/文体指纹.json"
    data = json_load(port.read_text(fp_rel))
    dims_hist: list[dict] = []
    for ch in range(1, 35):
        rel = f"定稿/正文/ch{ch:04d}.md"
        _fm, body = split(port.read_text(rel))
        fp = compute_fingerprint(body)
        data["rolling"][f"ch{ch:04d}"] = fp
        if ch <= 30:
            dims_hist.append(fp)
    baseline = {k: round(sum(d[k] for d in dims_hist) / len(dims_hist), 3)
                for k in dims_hist[0]}
    data["baseline"] = baseline
    data["baseline_range"] = {"from_ch": 1, "to_ch": 30}
    files.append(FileOp(fp_rel, dumps_json(data)))

    result = settle_run(port, SettleInput(
        message=("fix(手改)\n\n素材库补全：v6 增强设定卡 8 张迁入 + 信息差账本 3 条立账\n"
                 "+ 文体指纹基线（前 30 章七维均值）与 34 章 rolling 回填\n\n条目: -\n"),
        files=files))
    print(f"提交：{result.commit[:12]}（{len(files)} 文件）")
    print("基线七维：", baseline)
    print(f"增强卡 {n_cards} 张；信息差 {len(INFO_GAPS)} 条")


def json_load(text: str) -> dict:
    import json
    return json.loads(text)


if __name__ == "__main__":
    main()
