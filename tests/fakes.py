"""测试替身：InMemoryRepoPort（RepoPort 的内存实现，验证接口可替换性）。"""
from __future__ import annotations

import hashlib

from loom.core.ports import FaultInjected


class InMemoryRepoPort:
    """与 GitRepoPort 同语义的内存实现：文件树 + 提交树快照。

    settle 语义镜像：blob/commit 记账，move_ref 才前移 HEAD，
    worktree_sync 用 HEAD 快照覆盖工作树。
    """

    def __init__(self, fail_points: tuple[str, ...] = ()) -> None:
        self.files: dict[str, str] = {}
        self._blobs: dict[str, str] = {}
        self._trees: dict[str, dict[str, str]] = {}
        self._head: str | None = None
        self._committed: dict[str, str] = {}
        self._fail = set(fail_points)
        self._n = 0

    def _fake_sha(self, prefix: str, data: str) -> str:
        self._n += 1
        return f"{prefix}{hashlib.sha256(data.encode()).hexdigest()[:12]}{self._n:04d}"

    # ---- 文件 ----

    def read_text(self, rel: str) -> str:
        return self.files[rel]

    def exists(self, rel: str) -> bool:
        return rel in self.files

    def list_files(self, rel_dir: str) -> list[str]:
        prefix = "" if rel_dir in (".", "") else rel_dir.rstrip("/") + "/"
        return sorted(r for r in self.files if r.startswith(prefix))

    def write_text(self, rel: str, content: str) -> None:
        self.files[rel] = content

    def delete(self, rel: str) -> None:
        self.files.pop(rel, None)

    # ---- git 状态 ----

    def head_commit(self) -> str | None:
        return self._head

    def status_porcelain(self) -> list[str]:
        lines: list[str] = []
        for rel in sorted(set(self.files) | set(self._committed)):
            in_wt, in_ct = rel in self.files, rel in self._committed
            if in_wt and not in_ct:
                lines.append(f"?? {rel}")
            elif in_ct and not in_wt:
                lines.append(f" D {rel}")
            elif in_wt and in_ct and self.files[rel] != self._committed[rel]:
                lines.append(f" M {rel}")
        return lines

    # ---- plumbing ----

    def stage_blob(self, content: str) -> str:
        sha = self._fake_sha("b", content)
        self._blobs[sha] = content
        return sha

    def commit_tree(self, blobs: dict[str, str | None], message: str) -> str:
        tree = dict(self._committed)
        for rel, sha in blobs.items():
            if sha is None:
                tree.pop(rel, None)
            else:
                tree[rel] = self._blobs[sha]
        sha = self._fake_sha("c", repr(sorted(tree.items())) + message)
        self._trees[sha] = tree
        return sha

    def move_ref(self, sha: str) -> None:
        self._head = sha
        self._committed = dict(self._trees[sha])

    def worktree_sync(self) -> None:
        self.files = dict(self._committed)

    def fail_here(self, point: str) -> None:
        if point in self._fail:
            raise FaultInjected(point)
