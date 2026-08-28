"""loom CLI 唯一入口。

命令面规划（v3.0 方案 §5.1 + 审阅报告 A10）：
init / plan vol / plan batch / next / prep / render / check / review /
settle / batch / evolve / doctor / migrate / ledger / memory

P0 已落地：init / doctor。其余随 Phase 逐命令实现。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _utf8_stdio() -> None:
    """Windows 基线：控制台输出显式 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def cmd_init(args: argparse.Namespace) -> int:
    from loom.core.repo.layout import init_book

    init_book(Path(args.path).absolute(), args.genre)
    print(f"书仓已初始化：{args.path}")
    print(f"  spec_version=loom-1  genre={args.genre}  branch=master")
    print("下一步：完成 大纲/总纲.md 与核心设定，再进规划环（P1b）。")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from loom.core.doctor.doctor import run_doctor
    from loom.core.ports import GitRepoPort

    root = Path(args.path).absolute()
    report = run_doctor(GitRepoPort(root))
    print(f"loom doctor · {root}")
    for line in report.lines():
        print(f"  {line}")
    print(f"结论：{'健康' if report.ok else '存在问题（见上）'}")
    return 0 if report.ok else 1


def cmd_next(args: argparse.Namespace) -> int:
    """单章写作环：决策卡 → prep → 渲染 → 机检 → 双审 → 结算 → scribe。"""
    from loom.core.config import build_chain, find_env_files, load_env
    from loom.core.ports import GitRepoPort
    from loom.core.repo.frontmatter import split
    from loom.core.repo.layout import BookRepo
    from loom.core.repo.schema import ChapterCardFM
    from loom.edge.client.http import HTTPProvider
    from loom.pipeline import run_chapter

    root = Path(args.path).absolute()
    book = BookRepo(GitRepoPort(root))
    env = load_env(*find_env_files(root))
    provider = HTTPProvider(build_chain(env))
    rel = f"大纲/章纲/ch{args.chapter:04d}.md"
    fm, _body = split(book.port.read_text(rel))
    card = ChapterCardFM.model_validate(fm)
    contract = list(fm.get("contract", []) or [])
    result = run_chapter(book, provider, card, contract, autonomy=args.autonomy,
                         words=args.words)
    print(f"第 {result.chapter} 章 settle 完成：{result.commit[:12]}")
    print(f"  scribe：{result.scribe_commit[:12]}  渲染 {result.render_attempts} 次"
          f"  机检 issue {result.check_issues}  评审 issue {result.review_issues}")
    return 0


def _make_provider(root: Path):
    from loom.core.config import build_chain, find_env_files, load_env
    from loom.edge.client.http import HTTPProvider

    env = load_env(*find_env_files(root))
    return HTTPProvider(build_chain(env))


def cmd_plan(args: argparse.Namespace) -> int:
    from loom.core.ports import GitRepoPort
    from loom.core.repo.layout import BookRepo
    from loom.planning import plan_batch, plan_vol

    root = Path(args.path).absolute()
    book = BookRepo(GitRepoPort(root))
    provider = _make_provider(root)
    if args.what == "vol":
        vol = plan_vol(book, provider, args.vol)
        print(f"卷纲 vol{args.vol:02d} 已生成并过六道机检（climax={vol.climax_chapters}）")
        return 0
    plan = plan_batch(book, provider, args.vol, args.start,
                      count=args.count, approve=args.yes)
    print(plan.readview)
    if args.yes:
        print("已批准落仓（batch 事务提交）。")
    else:
        print("\n（以上为提案；确认无误后加 --yes 落仓）")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    from loom.core.ports import GitRepoPort
    from loom.core.repo.layout import BookRepo
    from loom.evolve.bench import load_samples, run_blindset

    root = Path(args.path).absolute()
    book = BookRepo(GitRepoPort(root))
    samples = load_samples(book)
    run_dir = run_blindset(book, {alias: _make_provider(root) for alias in "AB"})
    print(f"盲测运行完成：{run_dir}（{len(samples)} 样本 × 2 匿名候选）")
    print("下一步：作者匿名盲排后填写 ranks.csv，再生成路由表。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    from loom import __version__

    parser = argparse.ArgumentParser(prog="loom", description="织机 Loom —— loom-1 书仓格式参考实现")
    parser.add_argument("--version", action="version", version=f"loom {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="初始化 loom-1 书仓（git 仓库 + 骨架 + book.yaml）")
    p_init.add_argument("path", help="书仓目录（新建）")
    p_init.add_argument("--genre", required=True, help="题材（装入题材 profile）")
    p_init.set_defaults(func=cmd_init)

    p_doctor = sub.add_parser("doctor", help="书仓体检（完整性/写锁/索引/orphan/结算中断）")
    p_doctor.add_argument("path", help="书仓目录")
    p_doctor.set_defaults(func=cmd_doctor)

    p_next = sub.add_parser("next", help="写下一章（单章闭环：渲染→机检→双审→结算→scribe）")
    p_next.add_argument("path", help="书仓目录")
    p_next.add_argument("--chapter", type=int, required=True, help="章号")
    p_next.add_argument("--autonomy", default="L1", choices=["L0", "L1", "L2"], help="自治档")
    p_next.add_argument("--words", type=int, default=3000, help="目标字数")
    p_next.set_defaults(func=cmd_next)

    p_plan = sub.add_parser("plan", help="规划环：plan vol <N> / plan batch --vol N --start M")
    p_plan.add_argument("path", help="书仓目录")
    p_plan.add_argument("what", choices=["vol", "batch"], help="卷纲或批次章纲")
    p_plan.add_argument("--vol", type=int, default=1, help="卷号")
    p_plan.add_argument("--start", type=int, default=1, help="批次起始章号（batch）")
    p_plan.add_argument("--count", type=int, default=8, help="批次章数（batch）")
    p_plan.add_argument("--yes", action="store_true", help="批准落仓（batch）")
    p_plan.set_defaults(func=cmd_plan)

    p_bench = sub.add_parser("bench", help="盲测金标准集执行（匿名候选 × 样本）")
    p_bench.add_argument("path", help="书仓目录")
    p_bench.set_defaults(func=cmd_bench)

    return parser


def main(argv: list[str] | None = None) -> None:
    _utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))
