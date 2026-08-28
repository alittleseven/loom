"""P5 测试：L0 骨架、Book Map 完整版、成本面板、300 章合成压测（pack 恒定）。"""
from __future__ import annotations

from loom.core.repo.frontmatter import dumps
from loom.core.repo.layout import init_book
from loom.enhance import (
    book_map_full,
    build_l0_skeleton,
    cost_dashboard,
    pack_constant_check,
    synth_book,
)


def _seed(tmp_path):
    book = init_book(tmp_path / "压测书", genre="末世求生")
    port = book.port
    port.write_text("定稿/设定/名册/苏小白.md", dumps(
        {"id": "set-mc", "family": "名册", "name": "苏小白", "status": "active",
         "triggers": ["苏小白"]}, "主角。\n"))
    port.write_text("大纲/卷纲/vol01.md", dumps(
        {"spec_stage": "plan", "vol": 1, "climax_chapters": [5, 20],
         "entry_plan": [{"id": "F-001", "action": "开启", "due_chapter": 16}],
         "time_span": {"start": "历1", "end": "历40"},
         "chapter_types": {f"ch{i:04d}": "main" for i in range(1, 41)},
         "rhythm": {"entry_density": [2, 4], "climax_gap": 8, "deadline_margin": 5},
         "waivers": []}, "# 卷一\n"))
    changed = [line[3:] for line in port.status_porcelain() if line.startswith(("?? ", " M "))]
    sha = port.commit_tree({rel: port.stage_blob(port.read_text(rel)) for rel in changed},
                           "fix(手改)\n\n条目: -\n")
    port.move_ref(sha)
    port.worktree_sync()
    return book


def test_l0_skeleton_and_book_map(tmp_path):
    book = _seed(tmp_path)
    skeleton = build_l0_skeleton(book)
    assert "[Book Map·L0 全书骨架]" in skeleton and "卷1" in skeleton
    bm = book_map_full(book, 10)
    assert "当前位置：卷1" in bm
    assert "苏小白" not in bm or "在场人物" in bm  # 章节未在时间线时不虚构


def test_cost_dashboard(tmp_path):
    book = _seed(tmp_path)
    from loom.core import ledger as ledger_mod

    ledger_mod.append_ledger_event(book, {"event": "render_call", "chapter": 1,
                                          "usage": {"in": 5000, "out": 4500}})
    ledger_mod.append_ledger_event(book, {"event": "render_call", "chapter": 2,
                                          "usage": {"in": 5000, "out": 4500}})
    ledger_mod.append_ledger_event(book, {"event": "render_call", "chapter": 3,
                                          "usage": {"in": 20000, "out": 9000}})
    panel = cost_dashboard(book)
    assert "成本面板" in panel and "ch003" in panel and "黄灯" in panel


def test_300_chapter_constant_pack(tmp_path):
    """P5 硬验收：合成 300 章，早期章 vs 后期章 pack 预算漂移 ≤20%（成本不随书膨胀）。"""
    book = _seed(tmp_path)
    synth_book(book, chapters=300)
    assert book.port.exists("定稿/摘要/ch0300.md")
    assert book.port.exists("定稿/卷摘要/vol08.md")
    result = pack_constant_check(book, probe_chapters=(5, 150, 295))
    assert result["constant"], f"pack 漂移 {result['drift']} 超限：{result['sizes']}"
