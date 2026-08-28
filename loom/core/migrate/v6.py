"""v6 → loom-1 迁移器（v3.0 §4.6 / P2）。

源只读、失败零残留、产出待校对清单；大纲/条目→章纲卡与条目账本的映射单列验收；
迁移产物过 doctor，零孤儿零坏账。

v6 源布局（fantasy01 实测）：
  正文/第NNNN章-标题.md     标题式 Markdown，无 front matter
  设定集/*.md 与 增强设定/  主题卡片（主角卡/女主卡/世界观/力量体系…）
  大纲/总纲.md、第N卷-详细大纲.md、第N卷-节拍表.md、第N卷-时间线.md、
       第N卷-总纲写回.json（含结构化字段）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from loom.core.repo.frontmatter import dumps
from loom.core.repo.layout import init_book
from loom.core.settle.transaction import FileOp

_CH_RE = re.compile(r"^第(\d{3,4})章[-·](.+)\.md$")
_ID_ALLOC = {"伏笔": ("F", 0), "悬念": ("S", 100), "感情线": ("R", 200)}
_SET_TRIGGERS = ("姓名：",)


@dataclass
class MigrationReport:
    chapters: int = 0
    settings: int = 0
    entries: int = 0
    outline_files: int = 0
    todo: list[str] = field(default_factory=list)  # 待校对清单

    def lines(self) -> list[str]:
        head = (f"正文 {self.chapters} 章、设定 {self.settings} 条、"
                f"条目 {self.entries} 条、大纲文件 {self.outline_files} 个")
        out = [head]
        out += [f"[待校对] {t}" for t in self.todo]
        return out


def _alloc_entry_id(kind: str, seq: int) -> str:
    prefix, base = _ID_ALLOC[kind]
    return f"{prefix}-{(base + seq):03d}"


def guess_kind(text: str) -> str:
    """条目类型猜测：感情/关系→感情线；悬念/谜→悬念；其余伏笔。作者校对。"""
    if re.search(r"感情|关系|暧昧|心动", text[:200]):
        return "感情线"
    if re.search(r"悬念|谜团|真相|秘密", text[:200]):
        return "悬念"
    return "伏笔"


def migrate(source: Path | str, target: Path | str, genre: str, *,
            dry_run: bool = False) -> MigrationReport:
    """把 v6 书稿目录迁入 loom-1 书仓。source 全程只读。"""
    src = Path(source)
    report = MigrationReport()
    if dry_run:
        return _dry_run(src, report)
    if Path(target).exists() and (Path(target) / "book.yaml").exists():
        raise FileExistsError(f"目标已是书仓：{target}")
    book = init_book(target, genre=genre)
    port = book.port

    files: list[FileOp] = []

    # ---- 正文（append-only 语义由 loom-1 自身保证）----
    for src_rel in sorted((src / "正文").glob("第*章*.md")):
        m = _CH_RE.match(src_rel.name)
        if not m:
            report.todo.append(f"正文文件名不合规范，未迁移：{src_rel.name}")
            continue
        ch, title = int(m.group(1)), m.group(2).strip()
        raw = src_rel.read_text(encoding="utf-8")
        body = raw.split("\n", 1)[1] if raw.startswith("#") and "\n" in raw else raw
        text = dumps({
            "spec_stage": "manuscript", "chapter": ch, "title": title,
            "time_anchor": f"迁移锚点·ch{ch:04d}",          # 待 scribe/作者校对
            "entry_changes": [],                              # 待校对：账本映射后回填
            "contract_digest": [], "word_count": len(body),
            "migrated_from": "v6",
        }, body if body.startswith("\n") else "\n" + body)
        files.append(FileOp(f"定稿/正文/ch{ch:04d}.md", text))
        report.chapters += 1

    # ---- 设定集 → 设定条目（主题卡片 → 按标题切分的每条一文件）----
    set_dirs = [src / "设定集"]
    set_dirs += [d for d in sorted((src / "设定集").glob("*")) if d.is_dir()] if (src / "设定集").exists() else []
    seq = 0
    for d in set_dirs:
        if not d.is_dir() and d != src / "设定集":
            continue
        for md in sorted(d.glob("*.md")) if d.is_dir() else []:
            rel_fm = _migrate_setting_card(md, files, report)
            seq += rel_fm
    report.settings = seq

    # ---- 大纲：总纲 + 卷纲散文（结构化字段进待校对清单，由 plan 重生成替代）----
    if (src / "大纲" / "总纲.md").exists():
        files.append(FileOp("大纲/总纲.md",
                            (src / "大纲" / "总纲.md").read_text(encoding="utf-8")))
        report.outline_files += 1
    for vol_md in sorted((src / "大纲").glob("第*卷-详细大纲.md")):
        m = re.search(r"第(\d+)卷", vol_md.name)
        vol = int(m.group(1)) if m else 1
        files.append(FileOp(f"大纲/卷纲/vol{vol:02d}.md",
                            dumps({"spec_stage": "plan", "vol": vol,
                                   "climax_chapters": [], "entry_plan": [],
                                   "time_span": {"start": "迁移待校", "end": "迁移待校"},
                                   "chapter_types": {}, "migrated_from": "v6",
                                   "rhythm": {"entry_density": [2, 4], "climax_gap": 8,
                                              "deadline_margin": 5}, "waivers": []},
                                  "\n" + vol_md.read_text(encoding="utf-8") +
                                  "\n\n> [待校对] 结构化字段（高潮点/条目计划/时间锚点/章节类型）"
                                  "未映射——建议运行 loom plan vol 重生成后再人工核对。\n")))
        report.outline_files += 1
        report.todo.append(f"卷{vol} 卷纲结构化字段未映射（front matter 为占位）")

    # ---- 条目账本：从节拍表/大纲抽取伏笔线索（映射单列验收）----
    seq_e = 0
    for beat in sorted((src / "大纲").glob("第*卷-节拍表.md")):
        text = beat.read_text(encoding="utf-8")
        for line in text.splitlines():
            if re.search(r"伏笔|埋下|铺垫", line) and len(line.strip()) > 8:
                seq_e += 1
                eid = _alloc_entry_id("伏笔", seq_e)
                files.append(FileOp(
                    f"大纲/条目/伏笔/{eid}.md",
                    dumps({"id": eid, "kind": "伏笔", "strength": "mid",
                           "status": "tentative", "opened_ch": None,
                           "due_ch": None, "migrated_from": "v6"},
                          f"\n{line.strip()}\n\n> [待校对] 由节拍表自动抽取，需确认开启章/期限章。\n")))
                report.todo.append(f"条目 {eid}：来自 {beat.name}，开启章/期限章待人工确认")
    report.entries = seq_e

    sha_files = {op.rel: port.stage_blob(op.content) for op in files}
    sha = port.commit_tree(sha_files, "init: v6 → loom-1 迁移\n\n条目: -\n")
    port.move_ref(sha)
    port.worktree_sync()

    list_path = "迁移待校对清单.md"
    port.write_text(list_path, "\n".join(report.lines()) + "\n")
    sha2 = port.commit_tree({list_path: port.stage_blob(port.read_text(list_path))},
                            "fix(手改)\n\n迁移待校对清单\n")
    port.move_ref(sha2)
    port.worktree_sync()
    return report


def _migrate_setting_card(md: Path, files: list[FileOp], report: MigrationReport) -> int:
    """一张主题卡（如 主角卡.md）→ 单个设定条目文件（整卡保留，段落级切分交作者）。"""
    text = md.read_text(encoding="utf-8")
    name_m = re.search(r"姓名[：:]\s*(\S+)", text)
    name = name_m.group(1) if name_m else md.stem
    family = "角色" if re.search(r"主角|女主|配角|反派", md.stem) else "世界观"
    triggers = [name] if name else []
    rel = f"定稿/设定/{family}/v6-{md.stem}.md"
    files.append(FileOp(rel, dumps({
        "id": f"set-v6-{md.stem}", "family": family, "name": name,
        "status": "tentative", "triggers": triggers, "migrated_from": "v6",
    }, "\n" + text + "\n\n> [待校对] 触发器关键词仅含名字，建议按别名/称号补充。\n")))
    report.todo.append(f"设定 {md.stem}：触发器待补充（当前仅 {triggers}）")
    return 1


def _dry_run(src: Path, report: MigrationReport) -> MigrationReport:
    report.chapters = len(list(src.glob("正文/第*章*.md")))
    report.outline_files = len(list(src.glob("大纲/*.md")))
    return report
