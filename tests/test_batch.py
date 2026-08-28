"""批次连写测试：状态机、七项熔断、三档自治、人验简报、断点恢复。"""
from __future__ import annotations

import pytest

from loom.core.repo.frontmatter import dumps
from loom.staging import (
    BatchState,
    accept_batch,
    arm_batch,
    compute_breakers,
    evaluate_breakers,
    resume_batch,
    run_batch,
)
from tests.test_pipeline import _long_draft, _provider, _seed  # 复用 e2e 素材


def _seed_batch(tmp_path, n=4):
    """搭一个 4 章批次的书仓（章纲卡齐全）。"""
    book = _seed(tmp_path)
    port = book.port
    for ch in range(2, n + 1):
        port.write_text(f"大纲/章纲/ch{ch:04d}.md", dumps(
            {"spec_stage": "chapter_card", "chapter": ch, "touches": ["F-001"], "scenes": 2,
             "hook_type": "cliff", "time_anchor": "元启三年春", "word_tier": "setup"},
            f"第{ch}章要点。\n"))
    # 章纲卡与题材 profile 入定稿
    changed = [line[3:] for line in port.status_porcelain() if line.startswith(("?? ", " M "))]
    sha = port.commit_tree({rel: port.stage_blob(port.read_text(rel)) for rel in changed},
                           "fix(手改)\n\n章纲卡落仓\n")
    port.move_ref(sha)
    port.worktree_sync()
    return book


def test_batch_full_l2(tmp_path):
    book = _seed_batch(tmp_path)
    arm_batch(book, chapters=[1, 2, 3, 4], autonomy="L2")
    report = run_batch(book, _provider())
    assert report.state == BatchState.REVIEW.value
    assert report.done == [1, 2, 3, 4]
    assert book.port.status_porcelain() == []  # 每章独立 commit 后仓库干净
    # 批次人验简报
    assert any("批次人验简报" in b for b in report.brief)
    assert any("成本" in b for b in report.brief)
    # 作者全收
    state = accept_batch(book)
    assert state["state"] == BatchState.ACCEPTED.value


def test_batch_halt_on_pipeline_failure(tmp_path):
    book = _seed_batch(tmp_path)
    # 第一次 run：所有章都渲染坏稿 → 第 1 章就 HALT
    arm_batch(book, chapters=[1, 2], autonomy="L1")
    report = run_batch(book, _provider(manuscript="他顿悟了，系统提示响起。一切平静结束。"))
    assert report.state == BatchState.HALTED.value
    assert report.done == []
    # 断点恢复：换好稿子续跑
    state = resume_batch(book)
    assert state["state"] == BatchState.RUNNING.value
    report2 = run_batch(book, _provider(manuscript=_long_draft()))
    assert report2.state == BatchState.REVIEW.value
    assert report2.done == [1, 2]


def test_batch_requires_cards(tmp_path):
    book = _seed_batch(tmp_path)
    with pytest.raises(ValueError, match="章纲卡缺失"):
        arm_batch(book, chapters=[9])


def test_breakers_metrics_shape(tmp_path):
    book = _seed_batch(tmp_path)
    arm_batch(book, chapters=[1], autonomy="L2")
    run_batch(book, _provider())
    metrics = compute_breakers(book)
    assert {"check_block_rate", "leak_hit", "rhythm_debt", "rerender_rate"} <= set(metrics)
    ev = evaluate_breakers(book)
    assert isinstance(ev["halt"], bool)


def test_batch_arm_rejected_when_locked(tmp_path):
    import subprocess
    import sys

    from loom.core.repo import lock as repo_lock

    book = _seed_batch(tmp_path)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        import json as _json
        book.port.write_text(".loom/lock.json", _json.dumps({"pid": child.pid, "started_at": 0}))
        with pytest.raises(repo_lock.RepoBusy):
            arm_batch(book, chapters=[1])
    finally:
        child.kill()
        child.wait()
