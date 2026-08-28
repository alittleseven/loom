"""盲测金标准集执行器（v3.0 §4.6，P1b）。

三重角色红线：盲测集只作①路由事实源（本执行器）②bench 风格子集=拒绝式约束
（P4）③永不作 fitness。

执行流程：候选模型（匿名 alias A/B/C…）× 每个样本各产出一段续写 →
落盘 bench/blindset-v1/runs/<run_id>/（匿名文件 + blinding_key.json 供作者盲排）。
盲排结果由作者人工填写 ranks.csv 后，build_routing_table 产出路由表。
"""
from __future__ import annotations

import csv
import io
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from loom.core.repo.layout import BookRepo

BLINDSET_REL = "bench/blindset-v1"
ALIASES = "ABCDEFGH"


@dataclass
class BlindsetSample:
    sid: str
    scene: str       # 场景类型（6 类）
    emotion: str     # strong | weak
    context: str     # 前文背景（给模型的输入）
    instruction: str  # 续写指令


def load_samples(repo: BookRepo) -> list[BlindsetSample]:
    rel = f"{BLINDSET_REL}/samples.json"
    if not repo.port.exists(rel):
        raise FileNotFoundError(f"盲测集不存在：{rel}（先运行 loom bench seed）")
    data = json.loads(repo.port.read_text(rel))
    return [BlindsetSample(**item) for item in data["samples"]]


def seed_samples(repo: BookRepo, samples: list[dict]) -> None:
    """冻结样本集（从作者亲笔章节抽样；spec §4.6：24 段 = 6 场景 × 2 情绪 × 2）。"""
    rel = f"{BLINDSET_REL}/samples.json"
    repo.write_file(rel, json.dumps(
        {"version": "v1", "frozen_at": time.strftime("%Y-%m-%d"), "samples": samples},
        ensure_ascii=False, indent=1) + "\n", actor="author")


def run_blindset(repo: BookRepo, provider_factories: dict[str, callable]) -> Path:
    """provider_factories: {alias: provider}——alias 匿名（A/B/C），作者不可见真实模型名。

    每个样本 × 每个候选 → 一段续写 → runs/<run_id>/<alias>/<sid>.md。
    """
    samples = load_samples(repo)
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    run_dir = f"{BLINDSET_REL}/runs/{run_id}"
    for alias, provider in provider_factories.items():
        for s in samples:
            res = provider.complete_text(
                tier="render", schema_name="blindset",
                system="你是中文网文写手。按指令续写，直接输出正文。",
                user=f"【前文背景】\n{s.context}\n\n【指令】\n{s.instruction}")
            rel = f"{run_dir}/{alias}/{s.sid}.md"
            repo.port.write_text(rel, str(res.data.get("text", "")))
    repo.port.write_text(
        f"{run_dir}/blinding_key.json",
        json.dumps({"aliases": {a: getattr(p, "model", "?") for a, p in provider_factories.items()},
                    "note": "盲排期间严禁查看本文件；排名完成后由作者解锁对照"},
                   ensure_ascii=False, indent=1))
    return Path(run_dir)


def build_routing_table(repo: BookRepo, run_dir: str, ranks_csv: str) -> dict:
    """作者盲排 ranks_csv：sid,rank_A,rank_B,...（1 最好）。输出 模型×场景 胜任矩阵与路由表。"""
    reader = csv.DictReader(io.StringIO(ranks_csv))
    aliases = [a for a in (reader.fieldnames or [])[1:] if a.startswith("rank_")]
    wins: dict[str, int] = {a.removeprefix("rank_"): 0 for a in aliases}
    scene_wins: dict[str, dict[str, int]] = {}
    samples = {s.sid: s for s in load_samples(repo)}
    for row in reader:
        sid = row.get("sid", "")
        scene = samples.get(sid).scene if sid in samples else "?"
        scored = sorted(((int(row[a]), a.removeprefix("rank_")) for a in aliases if row.get(a)),
                        key=lambda x: x[0])
        if scored:
            wins[scored[0][1]] = wins.get(scored[0][1], 0) + 1
            scene_wins.setdefault(scene, {})
            scene_wins[scene][scored[0][1]] = scene_wins[scene].get(scored[0][1], 0) + 1
    table = {"winner_overall": max(wins, key=wins.get) if wins else None,
             "wins": wins, "wins_by_scene": scene_wins,
             "note": "各档路由按 wins_by_scene 场景胜任度配置；写入 book.yaml model_routing"}
    repo.port.write_text(f"{run_dir}/routing_table.json",
                         json.dumps(table, ensure_ascii=False, indent=1))
    return table
