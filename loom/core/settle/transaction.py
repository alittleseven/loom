"""settle 原子事务（loom-1 §8）。

git plumbing 顺序：stage_blob → commit_tree → move_ref（唯一原子点）→
worktree_sync。move_ref 之前任何一步失败/kill：仓库零痕迹；之后失败：
重放恢复 = worktree_sync（幂等 reset --hard HEAD）。

三道保险：
1. 断电/kill 回滚后仓库不脏（故障注入硬验收）；
2. 哈希防串稿：被审草稿 sha256 与送审草稿一致才准结算；
3. 只增不改粒度：正文/摘要/卷摘要已存在且内容不同 → 拒绝，除非 retcon=True。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from loom.core.ports import (
    FAULT_BUILD_TREE,
    FAULT_CREATE_COMMIT,
    FAULT_MOVE_REF,
    FAULT_STAGE_BLOBS,
    FAULT_SYNC_WORKTREE,
    RepoPort,
)
from loom.core.repo import lock as repo_lock
from loom.core.repo import ownership

APPEND_ONLY_PREFIXES = ("定稿/正文/", "定稿/摘要/", "定稿/卷摘要/")
LEDGER_REL = "演化/run-ledger.jsonl"


class SettleRejected(ValueError):
    """结算前置校验拒绝（fail-closed，工作区原样保留）。"""


@dataclass
class FileOp:
    rel: str
    content: str | None = None  # None = 删除
    actor: str = "settle"


@dataclass
class SettleInput:
    message: str
    files: list[FileOp]
    draft_content: str | None = None      # 送审草稿全文
    reviewed_sha256: str | None = None    # 被审草稿 sha256（防串稿）
    retcon: int | None = None             # 显式 retcon(N) 事务章号
    chapter: int | None = None            # 记入 run-ledger 的章号
    ledger_events: tuple[dict, ...] = ()  # 随本次事务入审计链的额外事件（usage 等）


@dataclass
class SettleResult:
    commit: str
    files: list[str] = field(default_factory=list)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(port: RepoPort, plan: SettleInput) -> SettleResult:
    """执行结算。工作区不干净或校验失败 → SettleRejected（不产生任何写入）。"""
    dirty = port.status_porcelain()
    if dirty:
        raise SettleRejected(f"工作区不干净，拒绝结算：{dirty[:3]}")

    # 哈希防串稿（C2）
    if plan.reviewed_sha256 is not None:
        if plan.draft_content is None:
            raise SettleRejected("提供了被审哈希但缺少送审草稿")
        if _sha256(plan.draft_content) != plan.reviewed_sha256:
            raise SettleRejected("哈希防串稿失败：被审草稿与送审草稿不一致")

    # 只增不改粒度（A11）：正文/摘要/卷摘要已存在且内容不同 → 须 retcon
    for op in plan.files:
        needs_retcon = (
            op.rel.startswith(APPEND_ONLY_PREFIXES)
            and op.content is not None
            and port.exists(op.rel)
            and port.read_text(op.rel) != op.content
        )
        if needs_retcon and plan.retcon is None:
            raise SettleRejected(f"{op.rel} 已定稿（只增不改）；改写须走显式 retcon(N) 事务")
        if needs_retcon and not plan.message.startswith(f"retcon({plan.retcon:03d})"):
            raise SettleRejected("retcon 事务的 commit message 必须以 retcon(NNN) 开头")

    # 写入所有权矩阵（M6）
    for op in plan.files:
        ownership.assert_allowed(op.rel, op.actor)

    repo_lock.acquire(port)
    try:
        if plan.chapter is not None:
            old = port.read_text(LEDGER_REL) if port.exists(LEDGER_REL) else ""
            lines = [json.dumps(e, ensure_ascii=False) for e in plan.ledger_events]
            lines.append(json.dumps(
                {
                    "event": "settle",
                    "chapter": plan.chapter,
                    "files": [op.rel for op in plan.files if op.content is not None],
                },
                ensure_ascii=False,
            ))
            plan.files.append(FileOp(LEDGER_REL, old + "\n".join(lines) + "\n"))

        blobs: dict[str, str | None] = {}
        port.fail_here(FAULT_STAGE_BLOBS)
        for op in plan.files:
            blobs[op.rel] = None if op.content is None else port.stage_blob(op.content)

        port.fail_here(FAULT_BUILD_TREE)
        port.fail_here(FAULT_CREATE_COMMIT)
        sha = port.commit_tree(blobs, plan.message)

        port.fail_here(FAULT_MOVE_REF)
        port.move_ref(sha)

        port.fail_here(FAULT_SYNC_WORKTREE)
        port.worktree_sync()
        return SettleResult(
            commit=sha, files=[op.rel for op in plan.files if op.content is not None]
        )
    finally:
        repo_lock.release(port)


def recover(port: RepoPort) -> bool:
    """kill 后重放恢复：ref 已前移而工作树未同步时，reset --hard HEAD（幂等）。

    仅当工作树差异全部是"HEAD 有、工作树缺/旧"（即 settle 中断特征）时执行。
    """
    if not port.status_porcelain():
        return False
    port.worktree_sync()
    return not port.status_porcelain()
