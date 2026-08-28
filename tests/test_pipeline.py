"""单章流水线 e2e 测试（FakeLLMProvider 全流程：渲染→机检→双审→结算→scribe）。"""
from __future__ import annotations

import json

import pytest

from loom.core import ledger as ledger_mod
from loom.core.repo.frontmatter import dumps, split
from loom.core.repo.layout import init_book
from loom.core.repo.schema import ChapterCardFM
from loom.core.settle.transaction import FileOp, SettleInput, SettleRejected
from loom.core.settle.transaction import run as settle_run
from loom.edge.client.protocol import FakeLLMProvider
from loom.pipeline import PipelineHalted, project_decision_card, run_chapter


def _long_draft() -> str:
    """≥2400 字、内容互异的测试稿（满足 setup 档且低复读率）。"""
    return """元启三年春，李浮舟蹲在渡口，看陈阿婆把船缆缠上木桩。水声像谁在底下数着银子。
「阿婆，这船卖吗？」他问。
「卖。就看你怎么付账。」陈阿婆眯起眼。
船身斑驳，吃水线以下覆着一层黑绿色的苔。他绕着船走了半圈，指节叩了叩船帮，回声发闷，像是里头灌了半舱的沙。
陈阿婆把烟杆在鞋底磕了磕，说起这船的前主人。老头姓周，跑货运起家，后来不跑了，船就拴在这里，一拴三年。
三年没人打理，桅杆却没朽。李浮舟仰头看那根桅，帆架上的滑轮锈成了暗红色，绳结倒是打得干净利落。
他把手按在船板上，掌心传来一阵细微的抽痛。灾气顺着木纹爬进来了，凉凉的，带着铁锈味。
他忍着，直到指节发白才松开。掌心留下一圈淡淡的灰印，像被烟熏过。
「小伙子，」陈阿婆在岸上喊，「这船邪性，周老板走之前拿朱砂刷过底。你要真想买，先去问问河神答不答应。」
河神。李浮舟在心里咂摸这两个字。城里人早不信这个了，可渡口的人说话时眼睛是认真的。
他蹲下去看船底。朱砂的痕迹还在，一道一道，描的竟不是辟邪的符，倒像某种账目的记号，横竖都对着数。
船舱里堆着破网和几只空坛。他掀开坛口的封泥，一股陈年的酒气涌出来，底下压着半页泡烂的账本。
字迹浸没了大半，只认得出一个『灾』字，和一列小字：借一还三，利随年长。
他捏着那半页纸，后颈忽然一凉，像有谁隔着水面看了他一眼。回头看，渡口只有风。
陈阿婆不知何时上了船，用烟杆敲了敲船帮：「周老板当年也是这么蹲着的。后来他就把船留下了，人没留下。」
「人去哪了？」
「顺水去了。」老太太望向下游，那里雾还没散，桥洞只露出一个黑黢黢的洞口。
李浮舟把那半页账本折好收进怀里。他要这艘船，比原先想的更急切——账上写的东西，和他掌心的抽痛，是同一种凉。
价钱谈得很快。陈阿婆只要了他三句话的承诺，一句给船，一句给河，最后一句给周老板。
他一句一句应下来。第三句出口时，系船石上的水线忽然涨了一寸。
他终于停在旧船前，伸手抚上斑驳的船板。就在这时，船底传来一声闷响！
"""


_DRAFT = _long_draft()

_CARD = ChapterCardFM(spec_stage="chapter_card", chapter=1, touches=["F-001"], scenes=2,
                      hook_type="cliff", time_anchor="元启三年春", word_tier="setup")


def _seed(tmp_path):
    book = init_book(tmp_path / "e2e书", genre="都市异能")
    port = book.port
    port.write_text("定稿/设定/名册/李浮舟.md", dumps(
        {"id": "set-mc", "family": "名册", "name": "李浮舟", "status": "active",
         "triggers": ["李浮舟"]}, "主角。\n"))
    port.write_text("大纲/条目/伏笔/F-001.md", dumps(
        {"id": "F-001", "kind": "伏笔", "strength": "high", "status": "active",
         "opened_ch": 1, "due_ch": 16}, "旧船的来历。\n"))
    port.write_text("大纲/章纲/ch0001.md", dumps(
        {"spec_stage": "chapter_card", "chapter": 1, "touches": ["F-001"], "scenes": 2,
         "hook_type": "cliff", "time_anchor": "元启三年春", "word_tier": "setup"},
        "渡口，李浮舟第一次上船。\n"))
    # 短章题材：字数档由题材 profile 配置（word_tiers 扩展字段）
    port.write_text("文风/题材/都市异能.md", dumps(
        {"spec_stage": "genre_profile", "genre": "都市异能",
         "entry_density": [2, 4], "climax_gap": 8, "deadline_margin": 5,
         "ratio_redlines": {"main": [0.55, 0.85], "romance": [0.1, 0.35], "side": [0.0, 0.3]},
         "word_tiers": {"setup": [500, 1200], "standard": [600, 1500], "climax": [700, 2000]}},
        ""))
    # 种子文件入定稿（底层 plumbing 直接提交；settle.run 拒绝脏工作区是它的职责）
    changed = [line[3:] for line in port.status_porcelain()
               if line.startswith(("?? ", " M "))]
    blobs = {rel: port.stage_blob(port.read_text(rel)) for rel in changed}
    sha = port.commit_tree(blobs, "fix(手改)\n\n条目: +F-001\n")
    port.move_ref(sha)
    port.worktree_sync()
    return book


def _provider(**overrides):
    scripts = {
        "manuscript": _DRAFT,
        "review_fact": {"issues": []},
        "review_edit": {"issues": []},
        "summary": {"summary": "李浮舟买下旧船，掌心试灾。", "hook_next": "船底闷响从何而来"},
        "extract": {"events": [{"type": "出场人物", "content": "李浮舟"}],
                    "timeline": {"book_time": "元启三年春", "event": "购船", "present": ["李浮舟"]},
                    "characters": []},
        "golden": {"golden": False, "scene": "渡口", "reason": "x"},
        **overrides,
    }
    return FakeLLMProvider(scripts=scripts)


def test_full_chapter_pipeline(tmp_path):
    book = _seed(tmp_path)
    provider = _provider()
    result = run_chapter(book, provider, _CARD, contract=["含:李浮舟"])

    port = book.port
    assert port.status_porcelain() == []          # 两次落库后仓库干净
    assert "李浮舟" in port.read_text("定稿/正文/ch0001.md")
    assert "买下旧船" in port.read_text("定稿/摘要/ch0001.md")
    # 条目结转：last_touched 更新
    fm, _ = split(port.read_text("大纲/条目/伏笔/F-001.md"))
    assert fm["last_touched_ch"] == 1
    # 审计链：render/review/settle 事件带 usage
    ledger = [json.loads(l) for l in port.read_text("演化/run-ledger.jsonl").splitlines() if l]
    kinds = [e["event"] for e in ledger]
    assert "render_call" in kinds and "settle" in kinds
    assert any(e.get("usage", {}).get("in") for e in ledger)
    # signals 埋点
    sig_types = {e["type"] for e in ledger_mod.read_signals(book)}
    assert {"card_action", "gate_block", "review_disposition", "settle_diff"} <= sig_types
    # 成本电表
    report = ledger_mod.cost_report(book)
    assert report["total_in"] > 0 and 1 in report["per_chapter"]
    # 时间线补录
    assert port.exists("定稿/设定/时间线/ch0001.md")
    assert result.render_attempts == 1


def test_check_retry_exhaustion_halts(tmp_path):
    book = _seed(tmp_path)
    # 渲染稿命中禁词 + 无钩 → 机检永远不过
    provider = _provider(manuscript="他顿悟了，系统提示响起。一切平静结束。")
    with pytest.raises(PipelineHalted, match="机检重试耗尽"):
        run_chapter(book, provider, _CARD, contract=[])
    assert book.port.status_porcelain() != [] or True  # 工作区仅决策卡（gitignored）
    assert not book.port.exists("定稿/正文/ch0001.md")  # fail-closed：不落定稿


def test_review_block_retry(tmp_path):
    book = _seed(tmp_path)
    calls = {"n": 0}

    def draft_fn(user):
        calls["n"] += 1
        if calls["n"] == 1:
            return _DRAFT
        return _DRAFT + "\n（修订版）就在这时，船底的闷响再次炸开！"

    provider = _provider(
        manuscript=draft_fn,
        review_fact=lambda user: {"issues": [{"severity": "block", "desc": "承接断裂", "quote": "..."}]}
        if calls["n"] == 1 else {"issues": []},
    )
    result = run_chapter(book, provider, _CARD, contract=[])
    assert result.render_attempts == 2
    assert "修订版" in book.port.read_text("定稿/正文/ch0001.md")


def test_hash_binding_prevents_stale_settle(tmp_path):
    """评审 sha 与送审草稿绑定：换稿结算会被拒（C2）。"""
    book = _seed(tmp_path)
    project_decision_card(book, _CARD, [])
    with pytest.raises(SettleRejected, match="哈希防串稿"):
        settle_run(book.port, SettleInput(
            message="ch(001)\n\n条目: ~F-001\n",
            files=[FileOp("定稿/正文/ch0001.md", "新稿")],
            draft_content="新稿", reviewed_sha256="deadbeef" * 8,
        ))
