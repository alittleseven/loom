"""scribe：章摘要 + 事实提取（10 类事件，A9）+ 文体指纹滚动 + 金句收割（M4 前移）。

落库走第二次独立 commit（scribe(chN) 前缀，loom-1 §8.4）；写入所有权：
摘要/设定/记忆 归 scribe（§9 矩阵）。金句候选 = 改稿 diff>30% 的段，
tentative 入库，作者确认后 active 进 pack 风格段。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass

from loom.core.repo.frontmatter import dumps, dumps_json, split
from loom.core.repo.layout import BookRepo
from loom.core.settle.transaction import FileOp, SettleInput
from loom.core.settle.transaction import run as settle_run
from loom.edge import prompts

FINGERPRINT_REL = "定稿/记忆/文体指纹.json"
GOLDEN_DIFF_RATIO = 0.3


# ---- 文体指纹七维（全部脚本可算，零 LLM）----

def compute_fingerprint(draft: str) -> dict:
    sentences = [s for s in re.split(r"[。！？!?]+", draft) if s.strip()]
    slens = [len(s) for s in sentences] or [0]
    mean_len = sum(slens) / len(slens)
    var = sum((n - mean_len) ** 2 for n in slens) / len(slens)
    paras = [p for p in draft.splitlines() if p.strip()] or [draft]
    lines = [ln for ln in draft.splitlines() if ln.strip()]
    dialogue = sum(1 for ln in lines if re.search(r'[「『"“]', ln))
    chars = re.findall(r"[\u4e00-\u9fff]", draft)
    sensory_words = ("声", "味", "腥", "疼", "冷", "热", "光", "香", "臭", "滑")
    metaphor_words = ("像", "仿佛", "如同", "似的", "宛如")
    n_sent = max(len(sentences), 1)
    return {
        "avg_sentence_len": round(mean_len, 2),
        "sentence_len_var": round(var, 2),
        "dialogue_ratio": round(dialogue / max(len(lines), 1), 3),
        "avg_para_len": round(sum(len(p) for p in paras) / len(paras), 2),
        "ttr": round(len(set(chars)) / max(len(chars), 1), 3),
        "sensory_density": round(sum(draft.count(w) for w in sensory_words) / n_sent, 3),
        "metaphor_density": round(sum(draft.count(w) for w in metaphor_words) / n_sent, 3),
    }


@dataclass
class ScribeResult:
    commit: str
    summary: str
    fingerprint: dict


def scribe_commit(repo: BookRepo, provider, chapter: int, draft: str) -> ScribeResult:
    """结算后的第二次落库：摘要 + 时间线补录 + 指纹滚动。"""
    summary = provider.complete_structured(
        tier="scribe", schema_name="summary",
        system=prompts.SCRIBE_SUMMARY_SYSTEM, user=draft)
    extract = provider.complete_structured(
        tier="scribe", schema_name="extract",
        system=prompts.SCRIBE_EXTRACT_SYSTEM, user=draft)

    files: list[FileOp] = []
    s = summary.data
    files.append(FileOp(
        f"定稿/摘要/ch{chapter:04d}.md",
        dumps({"chapter": chapter, "word_count": len(draft)},
              f"{s.get('summary', '')}\n\n承接点：{s.get('hook_next', '')}\n"),
        actor="scribe",
    ))

    tl = extract.data.get("timeline") or {}
    if tl.get("book_time"):
        files.append(FileOp(
            f"定稿/设定/时间线/ch{chapter:04d}.md",
            dumps({"id": f"set-tl-ch{chapter:04d}", "family": "时间线", "status": "active",
                   "ch": chapter, "book_time": str(tl.get("book_time")),
                   "event": str(tl.get("event", "")),
                   "present": list(tl.get("present", []))}, ""),
            actor="scribe",
        ))

    # 文体指纹滚动值更新（可变文件，A11 允许）
    fp_rel = FINGERPRINT_REL
    if repo.port.exists(fp_rel):
        data = json.loads(repo.port.read_text(fp_rel))
    else:
        data = {"spec_stage": "style_fingerprint", "baseline": None, "rolling": {}, "baseline_range": None}
    data.setdefault("rolling", {})[f"ch{chapter:04d}"] = compute_fingerprint(draft)
    files.append(FileOp(fp_rel, dumps_json(data), actor="scribe"))

    events = (
        {"event": "scribe_call", "chapter": chapter, "kind": "summary",
         "usage": {"in": summary.usage_in, "out": summary.usage_out}},
        {"event": "scribe_call", "chapter": chapter, "kind": "extract",
         "usage": {"in": extract.usage_in, "out": extract.usage_out}},
    )
    result = settle_run(repo.port, SettleInput(
        message=f"scribe({chapter:03d})\n\n摘要与事实提取入账\n",
        files=files, chapter=None, ledger_events=events,
    ))
    return ScribeResult(commit=result.commit, summary=str(s.get("summary", "")),
                        fingerprint=data["rolling"][f"ch{chapter:04d}"])


# ---- 金句收割闭环（diff>30% → tentative → 作者确认 → active）----

def _para_set(text: str) -> dict[str, str]:
    return {hashlib.md5(p.strip().encode()).hexdigest(): p.strip()
            for p in re.split(r"\n+", text) if len(p.strip()) >= 20}


def harvest_candidates(repo: BookRepo, provider, chapter: int, draft: str, final: str) -> int:
    """作者改稿后调用：与旧稿差异 >30%（相似度 <0.7）的段落 → LLM 分类 → tentative 进金句库。"""
    draft_paras = _para_set(draft)
    final_paras = _para_set(final)
    changed: list[str] = []
    for h, para in final_paras.items():
        if h in draft_paras:
            continue  # 未改动
        best = max((difflib.SequenceMatcher(None, para, dp).ratio()
                    for dp in draft_paras.values()), default=0.0)
        if best < 0.7:
            changed.append(para)
    count = 0
    for para in changed[:5]:  # 单章上限 5 条候选
        verdict = provider.complete_structured(
            tier="small", schema_name="golden",
            system=prompts.GOLDEN_CLASSIFY_SYSTEM, user=para)
        if not verdict.data.get("golden"):
            continue
        scene = str(verdict.data.get("scene", "default")) or "default"
        rel = f"文风/金句库/{scene}.md"
        fm, body = (split(repo.port.read_text(rel)) if repo.port.exists(rel)
                    else ({"scene": scene, "lines": []}, ""))
        lines = list(fm.get("lines", []) or [])
        if any(ln.get("text") == para for ln in lines):
            continue
        lines.append({"text": para, "status": "tentative", "source_ch": chapter})
        fm["scene"], fm["lines"] = scene, lines[-20:]  # LRU ≤20
        repo.write_file(rel, dumps(fm, body), actor="scribe")
        count += 1
    return count



def confirm_golden(repo: BookRepo, scene: str, index: int) -> bool:
    """作者确认：tentative → active（作者命令，actor=author）。"""
    rel = f"文风/金句库/{scene}.md"
    if not repo.port.exists(rel):
        return False
    fm, body = split(repo.port.read_text(rel))
    lines = list(fm.get("lines", []) or [])
    if 0 <= index < len(lines) and lines[index].get("status") == "tentative":
        lines[index]["status"] = "active"
        fm["lines"] = lines
        repo.write_file(rel, dumps(fm, body), actor="author")
        return True
    return False
