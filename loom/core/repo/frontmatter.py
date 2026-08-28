"""YAML front matter 容错读写（loom-1 §2.1/§2.2）。

约定：未知字段保留写回不丢单；解析失败 fail-closed 报错；UTF-8 全链路。
"""
from __future__ import annotations

import re
from typing import Any

import yaml

_FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(\r?\n|$)", re.DOTALL)


class FrontMatterError(ValueError):
    """front matter 结构非法（缺闭合、非映射等）。"""


def split(text: str) -> tuple[dict[str, Any], str]:
    """拆分 front matter 与正文。无 front matter 时返回 ({}, 原文)。"""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    data = yaml.safe_load(m.group(1))
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise FrontMatterError("front matter 必须是 YAML 映射")
    return data, text[m.end():]


def dumps(fm: dict[str, Any], body: str) -> str:
    """序列化 front matter + 正文。fm 保持插入序，unicode 直出。"""
    if not fm:
        return body
    y = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{y}---\n{body}"


def dumps_json(data: dict[str, Any]) -> str:
    """JSON 数据文件（如文体指纹）：ensure_ascii=False，缩进 2 供人改。"""
    import json

    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
