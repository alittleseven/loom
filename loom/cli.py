"""loom CLI 唯一入口。

命令面（v3.0 方案 §5.1 + 审阅报告 四.2 消除"功能存在但不可达"）：
已落地：init / doctor / next / plan / batch / bench / migrate / evolve / ledger /
        review / golden（金句收割·确认）/ volsummary（卷摘要）/ enhance（P5 工具）
规划中（随 Phase 补实现）：prep / render / check / settle（能力已并入 next 单章
        闭环）/ memory（记忆四态纠错，待 spec 演进）
"""
from __future__ import annotations

import argparse
import json
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


def cmd_migrate(args: argparse.Namespace) -> int:
    from loom.core.doctor.doctor import run_doctor
    from loom.core.migrate.v6 import migrate
    from loom.core.ports import GitRepoPort

    src, root = Path(args.source).absolute(), Path(args.path).absolute()
    report = migrate(src, root, genre=args.genre)
    print(f"v6 → loom-1 迁移完成：{root}")
    for line in report.lines():
        print(f"  {line}")
    dr = run_doctor(GitRepoPort(root))
    print(f"doctor：{'健康（零孤儿零坏账）' if dr.ok else '存在问题：'}")
    if not dr.ok:
        for line in dr.lines():
            print(f"  {line}")
    return 0 if dr.ok else 1


def cmd_batch(args: argparse.Namespace) -> int:
    from loom.core.ports import GitRepoPort
    from loom.core.repo.layout import BookRepo
    from loom.staging import (
        accept_batch,
        arm_batch,
        resume_batch,
        run_batch,
    )

    root = Path(args.path).absolute()
    book = BookRepo(GitRepoPort(root))
    if args.action == "arm":
        chapters = list(range(args.start, args.start + args.count))
        state = arm_batch(book, chapters=chapters, autonomy=args.autonomy)
        print(f"批次已 ARMED：ch{chapters[0]:04d}-{chapters[-1]:04d}（{args.autonomy}）")
        return 0
    if args.action == "resume":
        state = resume_batch(book)
        print(f"批次已恢复：{state['state']}")
        return 0
    if args.action == "accept":
        state = accept_batch(book)
        print(f"批次已全收：{state['state']}")
        return 0
    # run
    report = run_batch(book, _make_provider(root))
    for line in report.brief:
        print(f"  {line}")
    if report.breaker.get("triggered"):
        print(f"  熔断：{report.breaker['triggered']}")
    print(f"批次结束：{report.state}（完成 {len(report.done)} 章）")
    return 0


def cmd_evolve(args: argparse.Namespace) -> int:
    from loom.core.ports import GitRepoPort
    from loom.core.repo.layout import BookRepo
    from loom.evolve.optimizer import Proposal, analyze, propose, weekly_report

    root = Path(args.path).absolute()
    book = BookRepo(GitRepoPort(root))
    if args.action == "report":
        print(weekly_report(book))
        return 0
    if args.action == "propose":
        a = analyze(book)
        pid = propose(book, Proposal(
            target=args.target,
            change={"system_append": f"近期 {a['top_rules']} 问题集中，优先规避"},
            reason=f"由 signals 周报触发：{a['gate_blocks_by_rule']}",
            metrics_before={"review_block_rate": a["review_block_rate"],
                            "plan_deviation_rate": a["plan_deviation_rate"]}))
        print(f"提案已落盘待审：演化/优化提案/{pid}.json")
        return 0
    print(json.dumps(analyze(book), ensure_ascii=False, indent=1))
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    from loom.core.ports import GitRepoPort
    from loom.core.repo.layout import BookRepo
    from loom.enhance import cost_dashboard

    book = BookRepo(GitRepoPort(Path(args.path).absolute()))
    print(cost_dashboard(book))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """双审（事实审 + 编辑审）指定章的定稿文本；阻断退出码 1。"""
    from loom.core.ports import GitRepoPort
    from loom.core.prep.prep import compile_pack
    from loom.core.repo.layout import BookRepo
    from loom.core.repo.schema import ChapterCardFM
    from loom.edge.reviewers import run_reviews

    root = Path(args.path).absolute()
    book = BookRepo(GitRepoPort(root))
    card_rel = f"大纲/章纲/ch{args.chapter:04d}.md"
    fm, _body = book.read_fm(card_rel)
    card = ChapterCardFM.model_validate(fm)
    contract = list(fm.get("contract", []) or [])
    ms_rel = f"定稿/正文/ch{args.chapter:04d}.md"
    _ms_fm, draft = book.read_fm(ms_rel)
    pack = compile_pack(book, args.chapter, card, contract)
    outcome = run_reviews(book, _make_provider(root), args.chapter, draft, pack, contract)
    print(f"第 {args.chapter} 章双审：{'阻断' if outcome.blocked else '通过'}"
          f"（issue {len(outcome.issues)} 条，模型 {outcome.model}）")
    for i in outcome.issues:
        print(f"  - [{i.get('severity')}] {i.get('desc')}（{i.get('quote', '')}）")
    return 1 if outcome.blocked else 0


def cmd_golden(args: argparse.Namespace) -> int:
    """金句收割闭环：harvest（改稿 diff>30% → tentative）→ confirm（作者确认 active）。"""
    from loom.core.ports import GitRepoPort
    from loom.core.repo.layout import BookRepo
    from loom.edge import scribe as scribe_mod

    root = Path(args.path).absolute()
    book = BookRepo(GitRepoPort(root))
    if args.action == "confirm":
        ok = scribe_mod.confirm_golden(book, args.scene, args.index)
        print("金句已确认 active。" if ok else "未找到该 tentative 金句（检查 --scene/--index）。")
        return 0 if ok else 1
    if args.chapter is None or not args.final:
        raise SystemExit("harvest 需要 --chapter N 与 --final <作者改稿文件>")
    _fm, draft = book.read_fm(f"定稿/正文/ch{args.chapter:04d}.md")
    final = Path(args.final).read_text(encoding="utf-8")
    count = scribe_mod.harvest_candidates(book, _make_provider(root), args.chapter, draft, final)
    print(f"金句收割完成：本章入库 {count} 条候选（tentative，待 confirm）。")
    return 0


def cmd_volsummary(args: argparse.Namespace) -> int:
    """L1 卷摘要：卷末由章摘要合成，scribe(volNN) 事务落库。"""
    from loom.core.ports import GitRepoPort
    from loom.core.repo.layout import BookRepo
    from loom.edge import scribe as scribe_mod

    root = Path(args.path).absolute()
    book = BookRepo(GitRepoPort(root))
    commit = scribe_mod.build_vol_summary(book, _make_provider(root),
                                          args.vol, (args.start, args.end))
    print(f"卷摘要 vol{args.vol:02d} 已落库：{commit[:12]}")
    return 0


def cmd_enhance(args: argparse.Namespace) -> int:
    """P5 工具入口：l0 全书骨架 / bookmap 完整版 / synth 合成压测 / packcheck 恒定检查。"""
    from loom.core.ports import GitRepoPort
    from loom.core.repo.layout import BookRepo
    from loom.enhance import (
        book_map_full,
        build_l0_skeleton,
        pack_constant_check,
        synth_book,
    )

    root = Path(args.path).absolute()
    book = BookRepo(GitRepoPort(root))
    if args.action == "l0":
        print(build_l0_skeleton(book))
        return 0
    if args.action == "bookmap":
        print(book_map_full(book, args.chapter))
        return 0
    if args.action == "synth":
        if not args.yes:
            print("synth 将向书仓提交合成压测数据（不可逆 commit），确认请加 --yes。")
            return 1
        synth_book(book, chapters=args.chapters)
        print(f"合成压测书已提交：{args.chapters} 章。")
        return 0
    result = pack_constant_check(book, probe_chapters=(args.from_ch, args.to_ch))
    status = "恒定" if result["constant"] else "超限"
    print(f"pack 恒定检查：{result['sizes']}，漂移 {result['drift']}——{status}。")
    return 0 if result["constant"] else 1


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

    p_mig = sub.add_parser("migrate", help="v6 书稿 → loom-1 书仓迁移（源只读）")
    p_mig.add_argument("source", help="v6 书稿目录（只读）")
    p_mig.add_argument("path", help="目标书仓目录（新建）")
    p_mig.add_argument("--genre", required=True, help="题材")
    p_mig.set_defaults(func=cmd_migrate)

    p_batch = sub.add_parser("batch", help="批次连写：arm/run/resume/accept")
    p_batch.add_argument("path", help="书仓目录")
    p_batch.add_argument("action", choices=["arm", "run", "resume", "accept"])
    p_batch.add_argument("--start", type=int, default=1, help="起始章（arm）")
    p_batch.add_argument("--count", type=int, default=8, help="章数（arm）")
    p_batch.add_argument("--autonomy", default="L2", choices=["L0", "L1", "L2"], help="自治档")
    p_batch.set_defaults(func=cmd_batch)

    p_evolve = sub.add_parser("evolve", help="品味闭环（离线）：report/propose/analyze")
    p_evolve.add_argument("path", help="书仓目录")
    p_evolve.add_argument("action", choices=["report", "propose", "analyze"])
    p_evolve.add_argument("--target", default="review_prompt", help="提案对象")
    p_evolve.set_defaults(func=cmd_evolve)

    p_ledger = sub.add_parser("ledger", help="成本电表面板")
    p_ledger.add_argument("path", help="书仓目录")
    p_ledger.set_defaults(func=cmd_ledger)

    p_review = sub.add_parser("review", help="双审（事实审+编辑审）指定章定稿；阻断退出码 1")
    p_review.add_argument("path", help="书仓目录")
    p_review.add_argument("--chapter", type=int, required=True, help="章号")
    p_review.set_defaults(func=cmd_review)

    p_golden = sub.add_parser("golden", help="金句收割闭环：harvest / confirm")
    p_golden.add_argument("path", help="书仓目录")
    p_golden.add_argument("action", choices=["harvest", "confirm"])
    p_golden.add_argument("--chapter", type=int, help="章号（harvest）")
    p_golden.add_argument("--final", help="作者改稿后的定稿文本文件（harvest）")
    p_golden.add_argument("--scene", help="场景名（confirm）")
    p_golden.add_argument("--index", type=int, help="候选序号（confirm）")
    p_golden.set_defaults(func=cmd_golden)

    p_vol = sub.add_parser("volsummary", help="L1 卷摘要合成（scribe(volNN) 事务落库）")
    p_vol.add_argument("path", help="书仓目录")
    p_vol.add_argument("--vol", type=int, required=True, help="卷号")
    p_vol.add_argument("--start", type=int, required=True, help="起始章")
    p_vol.add_argument("--end", type=int, required=True, help="结束章")
    p_vol.set_defaults(func=cmd_volsummary)

    p_enh = sub.add_parser("enhance", help="P5 工具：l0 / bookmap / synth / packcheck")
    p_enh.add_argument("path", help="书仓目录")
    p_enh.add_argument("action", choices=["l0", "bookmap", "synth", "packcheck"])
    p_enh.add_argument("--chapter", type=int, help="章号（bookmap）")
    p_enh.add_argument("--chapters", type=int, default=300, help="合成章数（synth）")
    p_enh.add_argument("--from", dest="from_ch", type=int, default=1, help="起始探测章（packcheck）")
    p_enh.add_argument("--to", dest="to_ch", type=int, default=300, help="结束探测章（packcheck）")
    p_enh.add_argument("--yes", action="store_true", help="确认提交合成数据（synth）")
    p_enh.set_defaults(func=cmd_enhance)

    return parser


def main(argv: list[str] | None = None) -> None:
    _utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))
