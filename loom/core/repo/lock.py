"""书仓写锁（N5：单书仓单写者）。

.loom/lock.json = {pid, started_at}。批次/settle 运行期间持有；
pid 存活检测（Windows ctypes OpenProcess），stale 锁自动接管并告警。
锁持有期间（非本进程持有时）作者写命令拒绝。
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.core.ports import RepoPort

LOCK_REL = ".loom/lock.json"


class RepoBusy(RuntimeError):
    """书仓正被其他进程写入（或作者命令撞上批次运行）。"""

    def __init__(self, pid: int) -> None:
        super().__init__(f"书仓正被 pid={pid} 占用（单书仓单写者）")
        self.pid = pid


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock(port: RepoPort) -> dict | None:
    if not port.exists(LOCK_REL):
        return None
    try:
        return json.loads(port.read_text(LOCK_REL))
    except (json.JSONDecodeError, OSError):
        return None


def is_locked_by_other(port: RepoPort) -> int | None:
    """锁被其他存活进程持有时返回其 pid，否则 None（stale 锁由 acquire 接管）。"""
    lock = read_lock(port)
    if not lock:
        return None
    pid = int(lock.get("pid", 0))
    if pid == os.getpid():
        return None  # 本进程自己的锁
    return pid if _pid_alive(pid) else None


def acquire(port: RepoPort) -> None:
    """获取写锁；存活的外来锁 → RepoBusy；stale 锁接管（告警走返回前 print）。"""
    foreign = is_locked_by_other(port)
    if foreign is not None:
        raise RepoBusy(foreign)
    if port.exists(LOCK_REL):
        print("[loom] 检测到 stale 写锁（pid 已不存在），自动接管", file=sys.stderr)
    port.write_text(LOCK_REL, json.dumps({"pid": os.getpid(), "started_at": time.time()}))


def release(port: RepoPort) -> None:
    lock = read_lock(port)
    if lock and int(lock.get("pid", 0)) == os.getpid():
        port.delete(LOCK_REL)
