"""Windows 基线测试：>260 字符路径 settle 成功（N4/§5.4 故障注入验收项）。"""
from __future__ import annotations

import os

from loom.core.repo.frontmatter import dumps
from loom.core.repo.layout import init_book
from loom.core.settle.transaction import FileOp, SettleInput, run


def test_settle_beyond_260_char_path(tmp_path):
    deep = tmp_path / ("长" * 120) / "书仓"
    book = init_book(deep, genre="玄幻")
    port = book.port

    long_slug = "角" * 100
    rel = f"定稿/设定/名册/{long_slug}.md"
    abs_len = len(str(port._abs(rel)))
    assert abs_len > 260, f"测试前提不成立：路径仅 {abs_len} 字符"

    content = dumps(
        {"id": "set-ming-ce-900", "family": "名册", "name": long_slug[:10],
         "status": "active", "triggers": [long_slug[:10]]},
        "超长路径设定条目。\n",
    )
    result = run(
        port,
        SettleInput(
            message="ch(001)\n\n条目: +F-001\n",
            files=[FileOp(rel, content)],
            chapter=1,
        ),
    )
    assert result.commit == port.head_commit()
    assert port.read_text(rel) == content  # 写入且可读回（\\?\ 前缀生效）
    assert port.status_porcelain() == []
    assert os.name == "nt"  # 本测试只在 Windows 目标平台运行
