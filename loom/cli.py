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

    return parser


def main(argv: list[str] | None = None) -> None:
    _utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))
