"""CSV 知识表检索【v6 移植零件，GPL 隔离区】。

BM25 + CJK bigram，纯标准库。题材知识表（9 张）与模板库的检索机制；
知识表资产本体随迁移器（P2）从 v6 资产迁入（A12）。
"""
from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

_CJK = re.compile(r"[\u4e00-\u9fff]")
_ASCII = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文按二字组（unigram+bigram），ASCII 按小写词。"""
    tokens: list[str] = []
    cjk = "".join(ch for ch in text if _CJK.match(ch))
    for i in range(len(cjk)):
        tokens.append(cjk[i])
        if i + 1 < len(cjk):
            tokens.append(cjk[i : i + 2])
    tokens.extend(w.lower() for w in _ASCII.findall(text))
    return tokens


@dataclass
class KnowledgeTable:
    rows: list[dict] = field(default_factory=list)
    _df: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load_csv(cls, path: Path | str, text_column: str = "正文") -> KnowledgeTable:
        raw = Path(path).read_text(encoding="utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(raw)))
        table = cls(rows=rows)
        for row in rows:
            seen = set(tokenize(str(row.get(text_column, ""))))
            for tok in seen:
                table._df[tok] = table._df.get(tok, 0) + 1
        return table

    def search(self, query: str, k: int = 3) -> list[tuple[dict, float]]:
        n = max(len(self.rows), 1)
        avgdl = 60.0
        q_tokens = set(tokenize(query))
        scored: list[tuple[dict, float]] = []
        for row in self.rows:
            doc = str(row.get("正文", "") or "".join(str(v) for v in row.values()))
            tokens = tokenize(doc)
            if not tokens:
                continue
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            dl = len(tokens)
            score = 0.0
            for qt in q_tokens:
                f = tf.get(qt, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - self._df.get(qt, 0) + 0.5) / (self._df.get(qt, 0) + 0.5))
                score += idf * (f * 2.5) / (f + 1.5 * (1 - 0.75 + 0.75 * dl / avgdl))
            if score > 0:
                scored.append((row, score))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]
