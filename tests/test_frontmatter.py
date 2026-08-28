"""front matter 容错读写测试（loom-1 §2.1/§2.2）。"""
from __future__ import annotations

import pytest

from loom.core.repo.frontmatter import FrontMatterError, dumps, split


def test_roundtrip_unknown_fields_preserved():
    text = "---\nid: F-001\nkind: 伏笔\nfuture_field: {a: 1}\n---\n正文内容\n"
    fm, body = split(text)
    assert fm["future_field"] == {"a": 1}
    out = dumps(fm, body)
    fm2, body2 = split(out)
    assert fm2["id"] == "F-001" and fm2["future_field"] == {"a": 1}
    assert "正文内容" in body2


def test_roundtrip_chinese_and_order():
    fm = {"chapter": 3, "title": "灾从口入", "time_anchor": "元启三年春"}
    body = "李浮舟推开祠堂的门。\n"
    text = dumps(fm, body)
    fm2, body2 = split(text)
    assert fm2 == fm
    assert body2 == body
    assert "灾从口入" in text  # allow_unicode 直出中文


def test_no_front_matter():
    fm, body = split("纯正文，无 front matter。\n")
    assert fm == {} and body.startswith("纯正文")


def test_non_dict_front_matter_fails_closed():
    with pytest.raises(FrontMatterError):
        split("---\n- a\n- b\n---\n正文\n")


def test_crlf_tolerated():
    text = "---\r\nchapter: 1\r\ntitle: 灾\r\n---\r\n正文\r\n"
    fm, body = split(text)
    assert fm["chapter"] == 1 and "正文" in body
