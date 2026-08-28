"""配置-实现一致性检查（N1）：book.yaml 字段无代码消费点即报错。

机制：BookConfig 声明的每个字段必须在 loom/ 包源码（schema.py 定义处除外）
中出现字面量。CI 与 tests/test_consumption.py 调用；无消费者的字段说明是
"纸面功能"，直接报错。
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def check_config_consumption(fields: Iterable[str], pkg_dir: Path) -> list[str]:
    """返回没有代码消费点的字段名列表。pkg_dir = loom/ 包根目录。"""
    sources: list[str] = []
    for p in sorted(pkg_dir.rglob("*.py")):
        if p.name == "schema.py":  # schema 定义处不算消费点
            continue
        sources.append(p.read_text(encoding="utf-8"))
    blob = "\n".join(sources)
    return [f for f in fields if f not in blob]
