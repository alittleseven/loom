"""书仓布局、初始化与读写门面（loom-1 §1/§2/§3）。"""
from __future__ import annotations

from pathlib import Path

from loom import SPEC_VERSION
from loom.core.ports import GitRepoPort, RepoPort
from loom.core.repo import lock as repo_lock
from loom.core.repo import ownership
from loom.core.repo.frontmatter import dumps, dumps_json, split
from loom.core.repo.schema import (
    ENTRY_ID_RE,
    BookConfig,
    GenreProfileFM,
)

ROOT_DIRS = (
    "定稿/正文",
    "定稿/摘要",
    "定稿/卷摘要",
    "定稿/设定/名册",
    "定稿/设定/世界观",
    "定稿/设定/信息差",
    "定稿/设定/时间线",
    "定稿/设定/角色",
    "定稿/记忆",
    "大纲/卷纲",
    "大纲/章纲",
    "大纲/条目/伏笔",
    "大纲/条目/悬念",
    "大纲/条目/感情线",
    "文风/金句库",
    "文风/场景技能",
    "文风/题材",
    "演化",
    "工作区",
)

BOOK_GITIGNORE = "工作区/\n.cache/\n.loom/\n*.loom-tmp\n"


class BookFormatError(ValueError):
    """书仓结构或格式非法（fail-closed）。"""


def entry_rel(entry_id: str) -> str:
    """条目 id → 三本账内路径（外部引用只走 id，路径是派生）。"""
    m = ENTRY_ID_RE.match(entry_id)
    if not m:
        raise BookFormatError(f"条目 id 非法：{entry_id!r}")
    from loom.core.repo.schema import KIND_DIR_BY_PREFIX

    return f"大纲/条目/{KIND_DIR_BY_PREFIX[entry_id[0]]}/{entry_id}.md"


class BookRepo:
    """书仓门面：所有文件写入经所有权矩阵 + 写锁约束。"""

    def __init__(self, port: RepoPort) -> None:
        self.port = port
        self._config: BookConfig | None = None

    @classmethod
    def open(cls, root: Path | str, fail_points: tuple[str, ...] = ()) -> BookRepo:
        return cls(GitRepoPort(root, fail_points))

    # ---- 配置 ----

    def load_config(self) -> BookConfig:
        if self._config is None:
            if not self.port.exists("book.yaml"):
                raise BookFormatError("book.yaml 不存在（不是 loom-1 书仓）")
            import yaml

            data = yaml.safe_load(self.port.read_text("book.yaml"))
            if not isinstance(data, dict):
                raise BookFormatError("book.yaml 必须是 YAML 映射")
            if data.get("spec_version") != SPEC_VERSION:
                raise BookFormatError(
                    f"spec_version 不匹配：期望 {SPEC_VERSION}，实得 {data.get('spec_version')!r}"
                )
            self._config = BookConfig.model_validate(data)
        return self._config

    def config_dict(self) -> dict:
        import yaml

        return yaml.safe_load(self.port.read_text("book.yaml")) or {}

    # ---- 读写（过所有权矩阵；作者写受写锁约束）----

    def read_file(self, rel: str) -> str:
        return self.port.read_text(rel)

    def write_file(self, rel: str, content: str, actor: str) -> None:
        ownership.assert_allowed(rel, actor)
        if actor == "author":
            foreign = repo_lock.is_locked_by_other(self.port)
            if foreign is not None:
                raise repo_lock.RepoBusy(foreign)
        self.port.write_text(rel, content)

    def read_fm(self, rel: str) -> tuple[dict, str]:
        return split(self.port.read_text(rel))

    # ---- 条目 ----

    def entry_path(self, entry_id: str) -> str:
        return entry_rel(entry_id)


def init_book(root: Path | str, genre: str) -> BookRepo:
    """loom init：建书仓（git 仓库 + 骨架 + book.yaml + 题材 profile）并做 init 提交。"""
    from git import Repo

    root = Path(root)
    if (root / "book.yaml").exists():
        raise BookFormatError(f"目标已是书仓：{root}")
    root.mkdir(parents=True, exist_ok=True)

    Repo.init(str(root), initial_branch="master")
    probe = GitRepoPort(root)
    probe._git.config("core.longpaths", "true")
    probe._git.config("core.autocrlf", "false")
    probe._git.config("core.quotepath", "false")
    probe._git.config("user.name", "loom")
    probe._git.config("user.email", "loom@local")

    port = GitRepoPort(root)
    import yaml

    port.write_text(
        "book.yaml",
        yaml.safe_dump({"spec_version": SPEC_VERSION, "genre": genre}, allow_unicode=True, sort_keys=False),
    )
    port.write_text(".gitignore", BOOK_GITIGNORE)
    for d in ROOT_DIRS:
        Path(port._abs(f"{d}/.gitkeep")).parent.mkdir(parents=True, exist_ok=True)
        port.write_text(f"{d}/.gitkeep", "")
    port.write_text(
        "大纲/总纲.md",
        "# 总纲\n\n（作者在 LLM 辅助下完成；自由散文，人读，不参与机检。）\n",
    )
    profile = GenreProfileFM(
        spec_stage="genre_profile",
        genre=genre,
        entry_density=(2, 4),
        climax_gap=8,
        deadline_margin=5,
        ratio_redlines={"main": (0.55, 0.85), "romance": (0.1, 0.35), "side": (0.0, 0.3)},
    )
    port.write_text(
        f"文风/题材/{genre}.md",
        dumps(profile.model_dump(exclude_none=True), "\n（题材节奏与写法默认值，作者可改。）\n"),
    )
    port.write_text(
        "定稿/记忆/文体指纹.json",
        dumps_json(
            {"spec_stage": "style_fingerprint", "baseline": None, "rolling": {}, "baseline_range": None}
        ),
    )
    port.write_text("演化/signals.jsonl", "")
    port.write_text("演化/run-ledger.jsonl", "")

    message = "init: loom-1 书仓初始化\n\n条目: -\n"
    files = {rel: port.read_text(rel) for rel in port.list_files(".") if not rel.startswith(".git/")}
    blobs = {rel: port.stage_blob(content) for rel, content in files.items()}
    sha = port.commit_tree(blobs, message)
    port.move_ref(sha)
    port.worktree_sync()

    repo = BookRepo(port)
    repo.load_config()
    return repo
