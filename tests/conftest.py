"""pytest fixtures 与 settle 测试素材。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loom.core.repo.frontmatter import dumps
from loom.core.repo.layout import init_book
from loom.core.settle.transaction import FileOp


@pytest.fixture
def book_root(tmp_path: Path) -> Path:
    return tmp_path / "书仓"


@pytest.fixture
def book(book_root: Path):
    return init_book(book_root, genre="都市异能")


def manuscript_ops(ch: int, title: str = "灾从口入", body: str | None = None) -> list[FileOp]:
    """一章结算的最小文件集：正文 + 摘要（含合法 front matter）。"""
    body = body if body is not None else f"第{ch}章正文。李浮舟第一次『借灾』。" * 5
    text = dumps(
        {
            "spec_stage": "manuscript",
            "chapter": ch,
            "title": title,
            "time_anchor": f"元启三年·第{ch}日",
            "entry_changes": [{"id": "F-001", "action": "+"}] if ch == 1 else [{"id": "F-001", "action": "~"}],
            "contract_digest": ["李浮舟首次使用『借灾』且未失控"] if ch == 1 else [],
            "word_count": len(body),
        },
        body + "\n",
    )
    summary = dumps({"chapter": ch, "word_count": len(body)}, f"第{ch}章摘要：李浮舟借灾初试。\n")
    return [
        FileOp(f"定稿/正文/ch{ch:04d}.md", text),
        FileOp(f"定稿/摘要/ch{ch:04d}.md", summary),
    ]


def settle_message(ch: int, retcon: bool = False) -> str:
    """机器协议：ch(NNN)/retcon(NNN) 三位章号；文件名 chNNNN 四位（§1/§2.8）。"""
    if retcon:
        return f"retcon({ch:03d})\n\n条目: ~F-001\n"
    return f"ch({ch:03d})\n\n条目: {'+F-001' if ch == 1 else '~F-001'}\n"
