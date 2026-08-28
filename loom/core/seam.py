"""缝① 工作区文件协议的版本嗅探（loom-1 §2.7）。

core 容错读取 + 版本嗅探：seam_version 缺失视为 v0 遗留（放行），
不匹配时显式报 SeamVersionMismatch（降级拒绝），不静默错读。
"""
from __future__ import annotations

SEAM_VERSION = "1"


class SeamVersionMismatch(ValueError):
    def __init__(self, got: str) -> None:
        super().__init__(f"seam_version 不匹配：期望 {SEAM_VERSION!r}，实得 {got!r}")


def assert_seam(fm: dict) -> None:
    got = fm.get("seam_version")
    if got is not None and got != SEAM_VERSION:
        raise SeamVersionMismatch(str(got))
