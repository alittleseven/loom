"""loom doctor：书仓体检（loom-1 §9 / v3.0 §4.6 的 P0 子集）。

P0 检查项：配置、目录结构、写锁、索引一致性、条目 orphan、结算中断修复卡。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from loom.core import cache as cache_mod
from loom.core.ports import RepoPort
from loom.core.repo import lock as repo_lock
from loom.core.repo.frontmatter import split
from loom.core.repo.layout import ROOT_DIRS, BookFormatError, BookRepo
from loom.core.repo.schema import EntryFM, SettingFM

APPEND_ONLY_PREFIXES = ("定稿/正文/", "定稿/摘要/", "定稿/卷摘要/")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    repair: str | None = None  # 修复卡


@dataclass
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def lines(self) -> list[str]:
        out = []
        for c in self.checks:
            mark = "✓" if c.ok else "✗"
            out.append(f"[{mark}] {c.name}" + (f"：{c.detail}" if c.detail else ""))
            if c.repair:
                out.append(f"      修复卡：{c.repair}")
        return out


def run_doctor(port: RepoPort) -> DoctorReport:
    report = DoctorReport()
    book = BookRepo(port)

    # 1. 配置
    try:
        cfg = book.load_config()
        report.checks.append(CheckResult("book.yaml 配置", True, f"genre={cfg.genre}"))
        extra = set(book.config_dict()) - {"spec_version", "genre"}
        if extra:
            report.checks.append(
                CheckResult(
                    "book.yaml 未知字段", False, f"{sorted(extra)}（无代码消费点，防纸面功能）",
                    repair="删除未知字段，或随 spec 演进补消费点",
                )
            )
    except BookFormatError as e:
        report.checks.append(CheckResult("book.yaml 配置", False, str(e)))
        return report

    # 2. 目录结构
    missing = [d for d in ROOT_DIRS if not port.exists(f"{d}/.gitkeep")]
    report.checks.append(
        CheckResult("目录结构", not missing, f"缺失：{missing}" if missing else "19 个目录齐全")
    )

    # 3. 写锁
    foreign = repo_lock.is_locked_by_other(port)
    lock = repo_lock.read_lock(port)
    if foreign is not None:
        report.checks.append(
            CheckResult("书仓写锁", False, f"pid={foreign} 持有中", repair="等待其释放或确认进程死亡后删除 .loom/lock.json")
        )
    elif lock:
        report.checks.append(CheckResult("书仓写锁", True, f"stale 锁（pid={lock.get('pid')} 已消亡），可接管"))
    else:
        report.checks.append(CheckResult("书仓写锁", True, "未持锁"))

    # 4. 结算中断（settle 特征：工作树落后于 HEAD）
    dirty = port.status_porcelain()
    scratch = [l for l in dirty if l.startswith("?? ") and l[3:].startswith("工作区/")]
    real = [l for l in dirty if l not in scratch]
    if real:
        head = port.head_commit()
        recoverable = recoverable_dirty(port, real)
        report.checks.append(
            CheckResult(
                "工作树状态", False, f"{len(real)} 处差异：{real[:3]}",
                repair="git reset --hard HEAD（settle 中断重放恢复）" if recoverable and head else None,
            )
        )
    else:
        note = f"工作区暂存 {len(scratch)} 项（正常）" if scratch else "干净"
        report.checks.append(CheckResult("工作树状态", True, note))

    # 5. 索引一致性（可删重建）
    import sqlite3
    from pathlib import Path

    root = getattr(port, "root", None)
    db_file = Path(root) / ".cache" / "index.db" if root is not None else None
    if db_file is not None and db_file.exists():
        try:
            idx = cache_mod.EntryIndex(root)
            indexed = idx.all_paths()
            idx.close()
            scanned = {rel for rel in _scannable(port)}
            diff = indexed ^ scanned
            report.checks.append(
                CheckResult("索引一致性", not diff, f"差异 {len(diff)} 项" if diff else "索引与源文件一致",
                            repair="删除 .cache/ 后由 loom 重建" if diff else None)
            )
        except sqlite3.Error as e:
            report.checks.append(CheckResult("索引一致性", False, f"SQLite 异常：{e}",
                                              repair="删除 .cache/ 目录"))
    else:
        report.checks.append(CheckResult("索引一致性", True, "无缓存（首次查询时重建）"))

    # 6. 条目 orphan：账本/设定目录里 id 非法或无法解析的 .md
    orphans: list[str] = []
    for rel in _scannable(port):
        try:
            fm, _ = split(port.read_text(rel))
        except Exception:
            orphans.append(rel)
            continue
        try:
            if rel.startswith("大纲/条目/"):
                EntryFM.model_validate(fm)
            else:
                SettingFM.model_validate(fm)
        except Exception:
            orphans.append(rel)
    report.checks.append(
        CheckResult("条目 orphan", not orphans, f"{orphans[:3]}" if orphans else "账本与设定条目全部合法")
    )
    return report


def recoverable_dirty(port: RepoPort, dirty: list[str]) -> bool:
    """settle 中断特征：所有差异都是已跟踪内容的缺失/改写（无未跟踪新文件）。

    未跟踪文件说明存在 settle 之外的写入，reset --hard 会留下它们，不给出自动修复卡。
    """
    return not any(line.startswith("??") for line in dirty)


def _scannable(port: RepoPort) -> list[str]:
    out: list[str] = []
    for d in ("大纲/条目", "定稿/设定"):
        out.extend(rel for rel in port.list_files(d) if rel.endswith(".md"))
    return out
