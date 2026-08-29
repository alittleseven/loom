"""记忆四态纠错（loom-1 spec v0.2 §6.2 迁移规则）：零 LLM，作者人审驱动。

设定条目（定稿/设定/**.md）与记忆条目（定稿/记忆/**.md）共用四态；
迁移矩阵 fail-closed：非法迁移、未知条目、缺 status/reason 一律拒绝，
工作区原样保留。所有变更走 settle 事务（actor=author，fix(手改) 标题），
随事务落 run-ledger memory_transition 审计事件。
"""
from __future__ import annotations

from dataclasses import dataclass

from loom.core.repo.frontmatter import dumps, split
from loom.core.repo.layout import BookRepo

# 记忆四态迁移矩阵（spec v0.2 成文）：矛盾不入库——contradicted 只能回
# tentative 重走人审；无删除终态——纠错只降级/复活，不物理移除条目。
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "tentative": ("active", "outdated"),
    "active": ("outdated", "contradicted"),
    "outdated": ("active",),
    "contradicted": ("tentative",),
}

MEMORY_DIRS = ("定稿/设定", "定稿/记忆")


class MemoryTransitionError(ValueError):
    """纠错拒绝（非法迁移/未知条目/缺 reason），工作区原样保留。"""


@dataclass
class MemoryEntry:
    rel: str
    fm: dict
    body: str

    @property
    def status(self) -> str:
        return str(self.fm.get("status") or "")

    @property
    def label(self) -> str:
        return str(self.fm.get("id") or self.rel)


def list_entries(repo: BookRepo, status: str | None = None) -> list[MemoryEntry]:
    """列出带 status 字段的设定/记忆条目（零 LLM 只读；无 status 的文件跳过）。"""
    out: list[MemoryEntry] = []
    for d in MEMORY_DIRS:
        for rel in repo.port.list_files(d):
            if not rel.endswith(".md"):
                continue
            fm, body = split(repo.port.read_text(rel))
            if not fm.get("status"):
                continue
            out.append(MemoryEntry(rel=rel, fm=fm, body=body))
    out.sort(key=lambda e: e.rel)
    if status is not None:
        out = [e for e in out if e.status == status]
    return out


def set_status(repo: BookRepo, label: str, new_status: str, reason: str) -> str:
    """作者纠错：迁移矩阵校验 → settle 事务落库（run-ledger 记 memory_transition）。

    label 匹配 front matter `id` 或仓内相对路径。返回 settle commit sha。
    """
    if not (reason or "").strip():
        raise MemoryTransitionError("纠错必须给出 --reason（审计要求）")
    entry = next((e for e in list_entries(repo)
                  if e.label == label or e.rel == label), None)
    if entry is None:
        raise MemoryTransitionError(f"未知条目：{label}（用 loom memory list 查看）")
    old = entry.status
    legal = TRANSITIONS.get(old, ())
    if new_status not in legal:
        raise MemoryTransitionError(
            f"非法迁移：{old} → {new_status}（允许：{'/'.join(legal) or '无'}）")
    entry.fm["status"] = new_status
    from loom.core.settle.transaction import FileOp, SettleInput
    from loom.core.settle.transaction import run as settle_run

    result = settle_run(repo.port, SettleInput(
        message=(f"fix(手改)\n\n记忆纠错：{entry.label} {old} → {new_status}"
                 f"（{reason.strip()}）\n\n条目: -\n"),
        files=[FileOp(entry.rel, dumps(entry.fm, entry.body), actor="author")],
        ledger_events=({"event": "memory_transition", "id": entry.label,
                        "rel": entry.rel, "from": old, "to": new_status,
                        "reason": reason.strip()},),
    ))
    return result.commit
