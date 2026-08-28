"""RepoPort：core 全部环境操作（文件系统 + git）的唯一出口。

v3.0 方案 §5.2 接口契约之一。settle 的原子性（git plumbing：blob → 树 →
commit-tree → update-ref → 同步工作树）与故障注入矩阵（N4）都建立在本端口
之上；测试可注入 InMemoryRepoPort 替身（tests/fakes.py）。

故障注入点约定（fail_here 在对应步骤【之前】调用）：
- stage_blobs      blob 尚未写入          → 仓库零痕迹
- build_tree       blob 已入 odb（无引用）→ 仓库零痕迹
- create_commit    树已写入 odb（无引用）  → 仓库零痕迹
- move_ref         commit 已存在但未引用   → 仓库零痕迹（dangling）
- sync_worktree    ref 已前移、工作树未同步 → 可重放恢复（reset --hard HEAD）
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

FAULT_STAGE_BLOBS = "stage_blobs"
FAULT_BUILD_TREE = "build_tree"
FAULT_CREATE_COMMIT = "create_commit"
FAULT_MOVE_REF = "move_ref"
FAULT_SYNC_WORKTREE = "sync_worktree"
FAULT_POINTS = (
    FAULT_STAGE_BLOBS,
    FAULT_BUILD_TREE,
    FAULT_CREATE_COMMIT,
    FAULT_MOVE_REF,
    FAULT_SYNC_WORKTREE,
)


class FaultInjected(Exception):
    """测试注入的故障：模拟在对应步骤前进程被 kill。"""

    def __init__(self, point: str) -> None:
        super().__init__(f"fault injected at {point}")
        self.point = point


@runtime_checkable
class RepoPort(Protocol):
    """书仓环境端口：文件操作 + git plumbing。rel 路径一律 ``/`` 分隔。"""

    def read_text(self, rel: str) -> str: ...
    def exists(self, rel: str) -> bool: ...
    def list_files(self, rel_dir: str) -> list[str]: ...
    def write_text(self, rel: str, content: str) -> None: ...
    def delete(self, rel: str) -> None: ...
    def head_commit(self) -> str | None: ...
    def status_porcelain(self) -> list[str]: ...
    def stage_blob(self, content: str) -> str: ...
    def commit_tree(self, blobs: dict[str, str | None], message: str) -> str: ...
    def move_ref(self, sha: str) -> None: ...
    def worktree_sync(self) -> None: ...
    def fail_here(self, point: str) -> None: ...


def _wpath(p: Path | str) -> str:
    """Windows 长路径安全化：绝对路径加 \\\\?\\ 前缀（>260 字符路径不依赖注册表）。"""
    s = os.path.abspath(str(p))
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        s = "\\\\?\\" + s
    return s


class GitRepoPort:
    """RepoPort 的 git 真实实现（GitPython + 长路径安全的文件操作）。"""

    def __init__(self, root: Path | str, fail_points: tuple[str, ...] = ()) -> None:
        from git import Repo  # 延迟导入：InMemory 替身路径无需装 GitPython 也可读协议

        self.root = Path(root)
        self._repo: Repo = Repo(str(self.root))
        self._git = self._repo.git
        self._fail_points = set(fail_points)

    # ---- 文件操作（全部经 \\\\?\\ 长路径安全化，显式 UTF-8）----

    def _abs(self, rel: str) -> Path:
        return self.root.joinpath(*rel.split("/"))

    def read_text(self, rel: str) -> str:
        with open(_wpath(self._abs(rel)), "r", encoding="utf-8", newline="") as f:
            return f.read()

    def exists(self, rel: str) -> bool:
        return os.path.exists(_wpath(self._abs(rel)))

    def list_files(self, rel_dir: str) -> list[str]:
        base = self._abs(rel_dir)
        if not base.exists():
            return []
        out: list[str] = []
        root_s = str(self.root)
        for dirpath, _dirnames, filenames in os.walk(_wpath(base)):
            dp = dirpath.removeprefix("\\\\?\\")
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dp, fn), root_s)
                out.append(rel.replace("\\", "/"))
        return sorted(out)

    def write_text(self, rel: str, content: str) -> None:
        target = self._abs(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".loom-tmp")
        tmp.write_text(content, encoding="utf-8", newline="")
        os.replace(_wpath(tmp), _wpath(target))

    def delete(self, rel: str) -> None:
        target = self._abs(rel)
        if target.exists():
            os.remove(_wpath(target))

    # ---- git 状态 ----

    def head_commit(self) -> str | None:
        try:
            return str(self._repo.head.commit.hexsha)
        except ValueError:  # unborn HEAD
            return None

    def status_porcelain(self) -> list[str]:
        out = self._git.status("--porcelain")
        return out.splitlines() if out else []

    # ---- settle plumbing ----

    def stage_blob(self, content: str) -> str:
        data = content.encode("utf-8")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".loom-blob") as f:
            f.write(data)
            tmp = f.name
        try:
            return self._git.hash_object("-w", tmp).strip()
        finally:
            os.remove(tmp)

    def commit_tree(self, blobs: dict[str, str | None], message: str) -> str:
        """基于父提交树增量组树并 commit-tree；不触碰工作树与当前 index。

        blobs: rel 路径 → blob sha；值为 None 表示删除该路径。
        """
        parent = self.head_commit()
        with tempfile.TemporaryDirectory(prefix="loom-settle-") as td:
            index_file = str(Path(td) / "index")
            msg_file = Path(td) / "msg"
            msg_file.write_text(message, encoding="utf-8", newline="")
            with self._git.custom_environment(GIT_INDEX_FILE=index_file):
                if parent:
                    tree = self._git.rev_parse(f"{parent}^{{tree}}").strip()
                    self._git.read_tree(tree)
                else:
                    self._git.read_tree("--empty")
                for rel, sha in blobs.items():
                    if sha is None:
                        self._git.update_index("--force-remove", "--", rel)
                    else:
                        # 三参数旧式形态：GitPython 会拆含逗号的单元参数
                        self._git.update_index("--add", "--cacheinfo", "100644", sha, rel)
                new_tree = self._git.write_tree().strip()
            args = ["-F", str(msg_file)]
            if parent:
                args += ["-p", parent]
            return self._git.commit_tree(new_tree, *args).strip()

    def move_ref(self, sha: str) -> None:
        branch = self._git.symbolic_ref("--short", "HEAD").strip()
        self._git.update_ref(f"refs/heads/{branch}", sha)

    def worktree_sync(self) -> None:
        self._git.reset("--hard")

    # ---- 故障注入 ----

    def fail_here(self, point: str) -> None:
        if point in self._fail_points:
            raise FaultInjected(point)
