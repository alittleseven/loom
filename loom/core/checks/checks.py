"""机检十项（写侧）+ plan_gates 六道（规划侧）——全部零 LLM（C4：两套措辞分离）。

十项（v3.0 §4.2.4）：禁词/禁句式、泄密扫描、专名一致性、履约 diff、时间线校验、
字数预算、n-gram 复读率、条目形式合法、题材配比、无钩检测。
六道（§4.1）：期限合法、条目密度、爽点间距、时间锚单调、超期兑付覆盖、配比红线。

机检依赖字段一律读 front matter 结构化声明（M2）；散文段落不参与机检。
Issue.detail 即 signals gate_block 的五元组载荷（kind/rule/target/hint）。
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

from loom.core.legacy import contract as contract_engine
from loom.core.repo.frontmatter import split
from loom.core.repo.layout import BookRepo
from loom.core.repo.schema import (
    ChapterCardFM,
    EntryFM,
    GenreProfileFM,
    ManuscriptFM,
    SettingFM,
    VolOutlineFM,
    ratio_from_chapter_types,
)

WORD_TIERS = {"standard": (2600, 3600), "climax": (3400, 4600), "setup": (2400, 3200)}
NGRAM = 7
NGRAM_MAX_RATE = 0.02
HOOK_LEXICON = ("就在这时", "突然", "下一秒", "竟然", "谁也没想", "？", "！", "……", "秘密", "死")
DEFAULT_VOL_CHAPTERS = 40  # 卷章数默认值（start_ch/end_ch 未声明时）
REVEALED_RE = re.compile(r"revealed@(\d+)")


@dataclass
class Issue:
    rule: str
    level: str          # block | warn
    msg: str
    target: str = ""
    hint: str = ""

    def five_tuple(self) -> dict:
        return {"kind": self.level, "rule": self.rule, "target": self.target,
                "msg": self.msg, "hint": self.hint}


@dataclass
class ChapterContext:
    chapter: int
    draft: str                       # 正文 body（不含 front matter）
    manuscript: ManuscriptFM
    card: ChapterCardFM | None = None
    contract: list[str] = field(default_factory=list)
    profile: GenreProfileFM | None = None


# ---- 装载助手 ----

def load_style_constitution(repo: BookRepo) -> dict:
    rel = "文风/风格宪法.md"
    if not repo.port.exists(rel):
        return {}
    fm, _ = split(repo.port.read_text(rel))
    return fm


def load_entries(repo: BookRepo) -> dict[str, EntryFM]:
    out: dict[str, EntryFM] = {}
    for rel in repo.port.list_files("大纲/条目"):
        if not rel.endswith(".md"):
            continue
        try:
            fm, _ = split(repo.port.read_text(rel))
            e = EntryFM.model_validate(fm)
            out[e.id] = e
        except Exception:
            continue  # 非法条目由 doctor 报 orphan
    return out


def load_settings(repo: BookRepo, family: str) -> list[tuple[str, dict]]:
    out = []
    for rel in repo.port.list_files(f"定稿/设定/{family}"):
        if not rel.endswith(".md"):
            continue
        try:
            fm, _ = split(repo.port.read_text(rel))
            SettingFM.model_validate(fm)
            out.append((rel, fm))
        except Exception:
            continue
    return out


def timeline_anchors(repo: BookRepo) -> list[str]:
    """时间线锚点：按章号排序的唯一 book_time 序列（单调性基准）。"""
    pairs: list[tuple[int, str]] = []
    for _rel, fm in load_settings(repo, "时间线"):
        if fm.get("ch") is not None and fm.get("book_time"):
            pairs.append((int(fm["ch"]), str(fm["book_time"])))
    pairs.sort()
    ordered: list[str] = []
    for _ch, t in pairs:
        if t not in ordered:
            ordered.append(t)
    return ordered


def _anchor_index(anchor: str, ordered: list[str]) -> int | None:
    return ordered.index(anchor) if anchor in ordered else None


# ---- 机检十项 ----

def check_banned_words(draft: str, constitution: dict) -> list[Issue]:
    return [
        Issue("banned_word", "block", f"命中禁词：{w}", target=w)
        for w in constitution.get("banned_words", []) if w and w in draft
    ]


def check_banned_patterns(draft: str, constitution: dict) -> list[Issue]:
    issues = []
    for pat in constitution.get("banned_patterns", []):
        try:
            if pat and re.search(pat, draft):
                issues.append(Issue("banned_pattern", "block", f"命中禁句式：{pat}", target=pat))
        except re.error:
            issues.append(Issue("banned_pattern", "warn", f"禁句式正则非法（跳过）：{pat}"))
    return issues


def check_leak(repo: BookRepo, chapter: int, draft: str) -> list[Issue]:
    """泄密扫描：信息差条目（C3 在场列机检的 P1a 形态：可见性驱动）。"""
    issues = []
    for rel, fm in load_settings(repo, "信息差"):
        visibility = str(fm.get("visibility", "hidden"))
        m = REVEALED_RE.match(visibility)
        hidden = visibility == "hidden" or (m and int(m.group(1)) > chapter)
        if not hidden:
            continue
        for kw in fm.get("secret_keywords", []) or []:
            if kw and kw in draft:
                issues.append(Issue("leak", "block", f"泄密：读者尚不可知的『{kw}』出现", target=str(kw), hint=rel))
    return issues


def check_proper_nouns(repo: BookRepo, draft: str) -> list[Issue]:
    """专名一致性：名册名字的未登记变体（漂移检测）。"""
    issues = []
    for rel, fm in load_settings(repo, "名册"):
        name = str(fm.get("name") or "")
        if len(name) < 2:
            continue
        triggers = set(fm.get("triggers", []) or [])
        variants = {name[:-1], name[1:]} - triggers - {name}
        for v in variants:
            if v in draft and name not in draft:
                issues.append(Issue("proper_noun", "warn", f"疑似人名漂移：『{v}』未登记（全名『{name}』未出现）",
                                    target=v, hint=rel))
    return issues


def check_fulfillment(draft: str, assertions: list[str]) -> tuple[list[Issue], dict]:
    """履约 diff：决策卡合同 vs 草稿实际（covered/missed；extra 预留）。"""
    if not assertions:
        return [], {"covered": [], "missed": [], "total": 0}
    items = contract_engine.evaluate(draft, assertions)
    s = contract_engine.summary(items)
    issues = [Issue("fulfillment", "block", f"履约未达成：{raw}", target=raw) for raw in s["missed"]]
    return issues, s


def check_timeline(repo: BookRepo, chapter: int, time_anchor: str) -> list[Issue]:
    ordered = timeline_anchors(repo)
    issues = []
    if time_anchor not in ordered:
        return [Issue("timeline", "warn", f"锚点『{time_anchor}』未入时间线账本（scribe 应补录）", target=time_anchor)]
    idx = _anchor_index(time_anchor, ordered)
    if chapter > 1:
        prev = [t for ch, t in sorted(
            (int(fm["ch"]), str(fm["book_time"]))
            for _r, fm in load_settings(repo, "时间线") if fm.get("ch") and fm.get("book_time")
        ) if ch < chapter]
        if prev:
            idx_prev = _anchor_index(prev[-1], ordered)
            if idx is not None and idx_prev is not None and idx < idx_prev:
                issues.append(Issue("timeline", "block",
                                    f"时间回退：{time_anchor}（序 {idx}）早于前章 {prev[-1]}（序 {idx_prev}）",
                                    target=time_anchor))
    return issues


def _word_tiers(repo: BookRepo, profile: GenreProfileFM | None) -> dict:
    """字数档：默认 WORD_TIERS，可被题材 profile 的 word_tiers 扩展字段覆盖。"""
    extra = (profile.model_extra or {}) if profile else {}
    src = extra.get("word_tiers") or WORD_TIERS
    return {k: tuple(v) for k, v in src.items()}


def load_profile(repo: BookRepo) -> GenreProfileFM | None:

    try:
        genre = repo.load_config().genre
    except Exception:
        return None
    rel = f"文风/题材/{genre}.md"
    if not repo.port.exists(rel):
        return None
    fm, _ = split(repo.port.read_text(rel))
    try:
        return GenreProfileFM.model_validate(fm)
    except Exception:
        return None


def check_word_count(tier: str, word_count: int, tiers: dict | None = None) -> list[Issue]:
    lo, hi = (tiers or WORD_TIERS).get(tier, WORD_TIERS["standard"])
    if not lo <= word_count <= hi:
        return [Issue("word_count", "block", f"字数 {word_count} 超出 {tier} 档预算 {lo}-{hi}")]
    return []


def check_ngram_repetition(draft: str) -> list[Issue]:
    n = NGRAM
    text = re.sub(r"\s", "", draft)
    if len(text) < n * 4:
        return []
    counts: dict[str, int] = {}
    for i in range(len(text) - n + 1):
        g = text[i : i + n]
        counts[g] = counts.get(g, 0) + 1
    repeats = sum(c - 1 for c in counts.values() if c > 1)
    rate = repeats / max(len(text) - n + 1, 1)
    if rate > NGRAM_MAX_RATE:
        worst = max(counts, key=lambda g: counts[g])
        return [Issue("ngram", "block", f"{n}-gram 复读率 {rate:.3f} > {NGRAM_MAX_RATE}",
                      target=worst, hint=f"最高复读 {counts[worst]} 次")]
    return []


def check_entry_form(repo: BookRepo, ctx: ChapterContext, entries: dict[str, EntryFM]) -> list[Issue]:
    issues: list[Issue] = []
    changes = ctx.manuscript.entry_changes
    if not changes:
        waiver = ctx.card.touch_waiver if ctx.card else None
        if waiver is None:
            issues.append(Issue("entry_form", "block",
                                "本章未 touch 任何条目且无豁免（每章必须推进 ≥1 条承诺）"))
        return issues
    for ec in changes:
        e = entries.get(ec.id)
        if e is None:
            issues.append(Issue("entry_form", "block", f"条目 {ec.id} 不存在于三本账", target=ec.id))
        elif e.status == "contradicted":
            issues.append(Issue("entry_form", "block", f"条目 {ec.id} 处于 contradicted 状态，禁止推进", target=ec.id))
    return issues


def check_ratio(repo: BookRepo, chapter: int, touches: list[str]) -> list[Issue]:
    """题材配比（写侧形态）：本章在卷纲标注的章节类型 vs touch 条目构成。

    卷纲声明 romance 章 → 应 touch 感情线（R-）条目；声明 main/climax 章 →
    不应只 touch 感情线。软约束（warn），硬红线在 gate6（卷级）。
    """
    issues: list[Issue] = []
    declared: str | None = None
    for rel in repo.port.list_files("大纲/卷纲"):
        if not rel.endswith(".md"):
            continue
        fm, _ = split(repo.port.read_text(rel))
        types = fm.get("chapter_types", {}) if isinstance(fm, dict) else {}
        got = types.get(f"ch{chapter:04d}")
        if got:
            declared = str(got)
            break
    if declared is None:
        return issues
    has_r = any(t.startswith("R-") for t in touches)
    has_main = any(not t.startswith("R-") for t in touches)
    if declared == "romance" and touches and not has_r:
        issues.append(Issue("ratio", "warn", "卷纲标注本章 romance，但 touch 无感情线条目", target=f"ch{chapter:04d}"))
    if declared in ("main", "climax") and touches and not has_main:
        issues.append(Issue("ratio", "warn", f"卷纲标注本章 {declared}，但只 touch 了感情线", target=f"ch{chapter:04d}"))
    return issues


def check_no_hook(draft: str) -> list[Issue]:
    tail = draft[-300:]
    if not any(k in tail for k in HOOK_LEXICON):
        return [Issue("no_hook", "block", "章末 300 字未检出任何钩子信号（无钩检测）",
                      hint=f"词表：{HOOK_LEXICON[:6]}…")]
    return []


def run_checks(repo: BookRepo, ctx: ChapterContext) -> list[Issue]:
    """执行机检十项，返回全部 issue（含 warn）。"""
    constitution = load_style_constitution(repo)
    entries = load_entries(repo)
    profile = ctx.profile or load_profile(repo)
    tiers = _word_tiers(repo, profile)
    touches = [ec.id for ec in ctx.manuscript.entry_changes]
    issues: list[Issue] = []
    issues += check_banned_words(ctx.draft, constitution)
    issues += check_banned_patterns(ctx.draft, constitution)
    issues += check_leak(repo, ctx.chapter, ctx.draft)
    issues += check_proper_nouns(repo, ctx.draft)
    fulfill_issues, _summary = check_fulfillment(ctx.draft, ctx.contract)
    issues += fulfill_issues
    issues += check_timeline(repo, ctx.chapter, ctx.manuscript.time_anchor)
    tier = ctx.card.word_tier if ctx.card else "standard"
    issues += check_word_count(tier, ctx.manuscript.word_count, tiers)
    issues += check_ngram_repetition(ctx.draft)
    issues += check_entry_form(repo, ctx, entries)
    issues += check_ratio(repo, ctx.chapter, touches)
    issues += check_no_hook(ctx.draft)
    return issues


# ---- plan_gates 六道（规划侧；start_ch/end_ch 为卷纲计划性扩展字段，spec v0.2 预登记）----

def _vol_range(vol: VolOutlineFM) -> tuple[int, int]:
    extra = vol.model_extra or {}
    end = int(extra.get("end_ch", 0))
    start = int(extra.get("start_ch", end - DEFAULT_VOL_CHAPTERS + 1 if end else (vol.vol - 1) * DEFAULT_VOL_CHAPTERS + 1))
    return start, end or start + DEFAULT_VOL_CHAPTERS - 1


def run_plan_gates(
    vol: VolOutlineFM, entries: dict[str, EntryFM], profile: GenreProfileFM,
    ordered_anchors: list[str],
) -> list[Issue]:
    issues: list[Issue] = []
    start_ch, end_ch = _vol_range(vol)
    rhythm = vol.rhythm

    # gate 1 条目期限合法性
    for item in vol.entry_plan:
        if item.action == "开启" and item.due_chapter > end_ch + rhythm.deadline_margin:
            issues.append(Issue("gate1_deadline", "block",
                                f"{item.id} 期限 {item.due_chapter} 超出卷末+K（{end_ch}+{rhythm.deadline_margin}）",
                                target=item.id))

    # gate 2 条目密度预算
    opens = sum(1 for i in vol.entry_plan if i.action == "开启")
    lo, hi = rhythm.entry_density
    if not lo <= opens <= hi:
        issues.append(Issue("gate2_density", "block", f"计划开启 {opens} 条，超出密度预算 {lo}-{hi}"))

    # gate 3 爽点间距
    climaxes = sorted(vol.climax_chapters)
    for a, b in itertools.pairwise(climaxes):
        if b - a > rhythm.climax_gap:
            issues.append(Issue("gate3_climax_gap", "block", f"高潮点 {a}→{b} 间距 {b-a} > {rhythm.climax_gap}"))
    if not climaxes:
        issues.append(Issue("gate3_climax_gap", "warn", "本卷无高潮点标注"))

    # gate 4 时间锚点单调
    i_start = _anchor_index(vol.time_span.start, ordered_anchors)
    i_end = _anchor_index(vol.time_span.end, ordered_anchors)
    if i_start is not None and i_end is not None and i_end < i_start:
        issues.append(Issue("gate4_time", "block", f"卷纲时间跨度回退：{vol.time_span.start} → {vol.time_span.end}"))
    if i_start is None or i_end is None:
        issues.append(Issue("gate4_time", "warn", "时间跨度锚点未全部入时间线账本（可解释降级）"))

    # gate 5 超期兑付覆盖
    overdue = [e.id for e in entries.values()
               if e.status == "active" and e.due_ch is not None and e.due_ch < start_ch]
    covered = {i.id for i in vol.entry_plan if i.action == "兑付"}
    waivers = {w.reason for w in vol.waivers}
    for eid in overdue:
        if eid not in covered and not waivers:
            issues.append(Issue("gate5_overdue", "block", f"超期条目 {eid} 本卷无兑付安排且无豁免", target=eid))

    # gate 6 题材配比红线
    ratio = ratio_from_chapter_types(vol.chapter_types)
    for group, (lo_r, hi_r) in profile.ratio_redlines.items():
        got = ratio.get(group, 0.0)
        if not lo_r <= got <= hi_r:
            issues.append(Issue("gate6_ratio", "block",
                                f"{group} 配比 {got:.2f} 越红线 [{lo_r}, {hi_r}]"))
    return issues
