"""写入所有权矩阵（M6/N5）与执行点。

矩阵是白名单表：路径前缀 × 允许的 actor。违反即抛 OwnershipViolation。
signals 由内核独占 append（actor="core"）。
"""
from __future__ import annotations

ACTORS = ("settle", "scribe", "prep", "check", "review", "author", "core")

# (路径前缀, 允许 actor 集合)；按声明序匹配，先长后短
_OWNERSHIP: tuple[tuple[str, frozenset[str]], ...] = (
    ("演化/signals.jsonl", frozenset({"core"})),          # 内核独占（§9）
    ("演化/run-ledger.jsonl", frozenset({"settle", "core"})),
    ("定稿/正文/", frozenset({"settle", "author"})),      # author 仅限 retcon 事务（settle 侧校验）
    ("定稿/摘要/", frozenset({"settle", "scribe"})),
    ("定稿/卷摘要/", frozenset({"settle", "scribe"})),
    ("定稿/设定/", frozenset({"settle", "scribe", "author"})),
    ("定稿/记忆/", frozenset({"settle", "scribe", "author"})),
    ("大纲/", frozenset({"settle", "author"})),
    ("文风/", frozenset({"settle", "scribe", "author"})),  # 金句收割归 scribe（M4）
    ("工作区/", frozenset({"settle", "scribe", "prep", "check", "review", "author", "core"})),
    (".loom/", frozenset({"core"})),
)


class OwnershipViolation(PermissionError):
    def __init__(self, rel: str, actor: str) -> None:
        super().__init__(f"actor {actor!r} 无权写入 {rel}（写入所有权矩阵）")
        self.rel = rel
        self.actor = actor


def assert_allowed(rel: str, actor: str) -> None:
    if actor not in ACTORS:
        raise OwnershipViolation(rel, actor)
    for prefix, allowed in _OWNERSHIP:
        if rel.startswith(prefix):
            if actor not in allowed:
                raise OwnershipViolation(rel, actor)
            return
    # 未列入矩阵的路径（如 book.yaml、.gitignore）：初始化与内核可写
    if actor not in {"core", "settle", "author"}:
        raise OwnershipViolation(rel, actor)
