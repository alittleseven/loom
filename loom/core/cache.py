"""`.cache/index.db`：唯一持久派生物（loom-1 §7）。

SQLite（WAL + busy_timeout）；SCHEMA_VERSION 变更即全量删除重建；
删除后由源文件全量重建，重建结果与原查询一致是硬验收。
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from loom.core.repo.frontmatter import split
from loom.core.repo.schema import EntryFM, SettingFM

SCHEMA_VERSION = "1"
DB_REL = ".cache/index.db"

_SCAN_DIRS = ("大纲/条目", "定稿/设定")


class EntryIndex:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.joinpath(".cache").mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.root / ".cache" / "index.db")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        row = self._db.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone() if self._table_exists("meta") else None
        if row is None or row[0] != SCHEMA_VERSION:
            self._db.executescript(
                "DROP TABLE IF EXISTS meta; DROP TABLE IF EXISTS entries;"
                "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
                "CREATE TABLE entries("
                " id TEXT PRIMARY KEY, kind TEXT, status TEXT,"
                " path TEXT, content_hash TEXT);"
            )
            self._db.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)", (SCHEMA_VERSION,)
            )
            self._db.commit()

    def _table_exists(self, name: str) -> bool:
        row = self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    # ---- 重建 ----

    def rebuild(self, port) -> int:
        """从源文件全量重建索引（确定性：路径排序扫描）。返回条目数。"""
        self._db.execute("DELETE FROM entries")
        n = 0
        for rel in self._scan(port):
            try:
                fm, _body = split(port.read_text(rel))
            except Exception:
                continue  # 解析失败的文件不入索引（doctor 负责报告 orphan）
            parsed: EntryFM | SettingFM | None = None
            try:
                parsed = EntryFM.model_validate(fm)
                kind, status, eid = parsed.kind, parsed.status, parsed.id
            except Exception:
                try:
                    parsed = SettingFM.model_validate(fm)
                    kind, status, eid = f"设定/{parsed.family}", parsed.status, parsed.id
                except Exception:
                    continue
            content_hash = hashlib.sha256(port.read_text(rel).encode("utf-8")).hexdigest()
            self._db.execute(
                "INSERT OR REPLACE INTO entries(id, kind, status, path, content_hash)"
                " VALUES(?,?,?,?,?)",
                (eid, kind, status, rel, content_hash),
            )
            n += 1
        self._db.commit()
        return n

    def _scan(self, port) -> list[str]:
        out: list[str] = []
        for d in _SCAN_DIRS:
            out.extend(rel for rel in port.list_files(d) if rel.endswith(".md"))
        return out

    # ---- 查询 ----

    def get(self, entry_id: str) -> dict | None:
        row = self._db.execute(
            "SELECT id, kind, status, path, content_hash FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        return dict(zip(("id", "kind", "status", "path", "content_hash"), row)) if row else None

    def by_kind(self, kind: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, kind, status, path, content_hash FROM entries"
            " WHERE kind=? ORDER BY id",
            (kind,),
        ).fetchall()
        return [dict(zip(("id", "kind", "status", "path", "content_hash"), r)) for r in rows]

    def all_paths(self) -> set[str]:
        return {r[0] for r in self._db.execute("SELECT path FROM entries")}

    def close(self) -> None:
        self._db.close()

    @classmethod
    def destroy(cls, root: Path | str) -> None:
        db = Path(root) / ".cache" / "index.db"
        if db.exists():
            db.unlink()
