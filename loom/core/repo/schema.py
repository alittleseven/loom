"""loom-1 全部 schema（规范：docs/plans/loom-1-格式规范-v0.1.md）。

规划侧四张（卷纲/章纲卡/条目账本/决策卡，§4）+ 写侧家族（正文/设定条目/
文体指纹/题材 profile，§6）。全部 extra=allow（容错保留未知字段）。
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---- 条目稳定 id（§2.4）：{F|S|R}-NNN ----

ENTRY_ID_RE = re.compile(r"\A[FSR]-\d{3}\Z")
ENTRY_KIND_BY_PREFIX = {"F": "伏笔", "S": "悬念", "R": "感情线"}
KIND_DIR_BY_PREFIX = {"F": "伏笔", "S": "悬念", "R": "感情线"}
ENTRY_ACTIONS_PLAN = ("开启", "推进", "兑付")
ENTRY_ACTIONS_SIGNS = ("+", "~", "$")

EntryId = str
ChapterType = Literal["main", "romance", "side", "climax", "transition"]
MEMORY_STATUSES = ("active", "tentative", "outdated", "contradicted", "paid")

# A3 配比口径：主线 = main+climax；感情 = romance；支线 = side+transition
RATIO_GROUPS: dict[str, set[str]] = {
    "main": {"main", "climax"},
    "romance": {"romance"},
    "side": {"side", "transition"},
}


def validate_entry_id(value: str) -> str:
    if not ENTRY_ID_RE.match(value):
        raise ValueError(f"条目 id 非法：{value!r}（须为 F-NNN/S-NNN/R-NNN）")
    return value


def ratio_from_chapter_types(chapter_types: dict[str, str]) -> dict[str, float]:
    """卷级配比计算（A3）：按归并组返回占比，空卷返回空表。"""
    total = len(chapter_types)
    if total == 0:
        return {}
    counts = {g: 0 for g in RATIO_GROUPS}
    for t in chapter_types.values():
        group = next((g for g, ts in RATIO_GROUPS.items() if t in ts), None)
        if group is None:
            raise ValueError(f"章节类型非法：{t!r}")
        counts[group] += 1
    return {g: round(n / total, 4) for g, n in counts.items()}


class LoomModel(BaseModel):
    model_config = ConfigDict(extra="allow")  # 容错：未知字段保留写回


# ---- 豁免载体（A1 定案）：不是独立卡型，是三张卡上的字段 ----

class Waiver(LoomModel):
    reason: str = Field(min_length=1)
    approved_by: Literal["author"]  # 只有作者有权豁免
    source: Literal["decision_card", "chapter_card", "vol_outline"]


# ---- book.yaml（§3，v0.1 冻结字段）----

class BookConfig(LoomModel):
    spec_version: Literal["loom-1"]
    genre: str = Field(min_length=1)


# ---- §4.1 卷纲 ----

class EntryPlanItem(LoomModel):
    id: EntryId
    action: Literal["开启", "推进", "兑付"]
    due_chapter: int = Field(ge=1)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return validate_entry_id(v)


class RhythmBudget(LoomModel):
    entry_density: tuple[int, int]  # 本卷计划开启条目数区间（gate 2）
    climax_gap: int = Field(ge=1)   # 高潮点间隔上限（gate 3）
    deadline_margin: int = Field(ge=0)  # 期限章 ≤ 卷末章 + K（gate 1）


class TimeSpan(LoomModel):
    start: str
    end: str


class VolOutlineFM(LoomModel):
    spec_stage: Literal["plan"]
    vol: int = Field(ge=1)
    climax_chapters: list[int] = Field(default_factory=list)
    entry_plan: list[EntryPlanItem] = Field(default_factory=list)
    time_span: TimeSpan
    chapter_types: dict[str, ChapterType] = Field(default_factory=dict)
    rhythm: RhythmBudget
    waivers: list[Waiver] = Field(default_factory=list)  # 计划级豁免（A1，gate 5）

    @field_validator("entry_plan")
    @classmethod
    def _plan_ids(cls, v: list[EntryPlanItem]) -> list[EntryPlanItem]:
        for item in v:
            validate_entry_id(item.id)
        return v


# ---- §4.2 章纲卡 ----

HOOK_TYPES = ("cliff", "reveal", "decision", "emotion", "peace")


class ChapterCardFM(LoomModel):
    spec_stage: Literal["chapter_card"]
    chapter: int = Field(ge=1)
    touches: list[EntryId] = Field(default_factory=list)
    touch_waiver: Waiver | None = None
    scenes: int = Field(ge=2, le=3)
    hook_type: Literal["cliff", "reveal", "decision", "emotion", "peace"]
    time_anchor: str = Field(min_length=1)
    word_tier: Literal["standard", "climax", "setup"]

    @field_validator("touches")
    @classmethod
    def _touch_ids(cls, v: list[str]) -> list[str]:
        for x in v:
            validate_entry_id(x)
        return v

    @model_validator(mode="after")
    def _touch_or_waiver(self) -> ChapterCardFM:
        if not self.touches and self.touch_waiver is None:
            raise ValueError("章纲卡须 touch ≥1 条条目，或持显式豁免 touch_waiver（A1）")
        return self


# ---- §4.3 条目账本 ----

class EntryFM(LoomModel):
    id: EntryId
    kind: Literal["伏笔", "悬念", "感情线"]
    strength: Literal["high", "mid", "low"]
    status: Literal["active", "tentative", "outdated", "contradicted", "paid"]
    opened_ch: int = Field(ge=1)
    due_ch: int | None = None
    last_touched_ch: int | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return validate_entry_id(v)

    @model_validator(mode="after")
    def _kind_matches_prefix(self) -> EntryFM:
        if ENTRY_KIND_BY_PREFIX.get(self.id.split("-")[0]) != self.kind:
            raise ValueError(f"id 前缀与 kind 不一致：{self.id} ↔ {self.kind}")
        return self


# ---- §4.4 决策卡 ----

class DecisionCardFM(LoomModel):
    spec_stage: Literal["decision_card"]
    seam_version: str  # 工作区缝协议版本（§2.7）
    chapter: int = Field(ge=1)
    generated_by: Literal["plan_template", "llm", "author"]
    touch_waiver: Waiver | None = None  # A1
    contract: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)


# ---- §6.1 正文 front matter ----

class EntryChange(LoomModel):
    id: EntryId
    action: Literal["+", "~", "$"]

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return validate_entry_id(v)


class ManuscriptFM(LoomModel):
    spec_stage: Literal["manuscript"]
    chapter: int = Field(ge=1)
    title: str = Field(min_length=1)
    time_anchor: str = Field(min_length=1)
    entry_changes: list[EntryChange] = Field(default_factory=list)
    contract_digest: list[str] = Field(default_factory=list)
    word_count: int = Field(ge=0)


# ---- §6.2 设定条目 ----

class SettingFM(LoomModel):
    id: str = Field(min_length=1)  # set- 前缀语法，跨书引用键
    family: Literal["名册", "世界观", "信息差", "时间线", "角色"]
    name: str | None = None
    status: Literal["active", "tentative", "outdated", "contradicted"] = "active"
    triggers: list[str] = Field(default_factory=list)  # 名册关键词触发器
    # 时间线家族附加（C3 在场列，append-only）：
    ch: int | None = None
    book_time: str | None = None
    event: str | None = None
    present: list[str] = Field(default_factory=list)


# ---- §6.3 文体指纹（七维） ----

STYLE_DIMS = (
    "avg_sentence_len",
    "sentence_len_var",
    "dialogue_ratio",
    "avg_para_len",
    "ttr",
    "sensory_density",
    "metaphor_density",
)


class StyleFingerprint(LoomModel):
    spec_stage: Literal["style_fingerprint"]
    baseline: dict[str, float] | None = None  # 作者认可的前 30 章定基线
    rolling: dict[str, dict[str, float]] = Field(default_factory=dict)
    baseline_range: dict[str, int] | None = None  # {"from_ch": 1, "to_ch": 30}


# ---- §6.4 题材 profile ----

class GenreProfileFM(LoomModel):
    spec_stage: Literal["genre_profile"]
    genre: str = Field(min_length=1)
    entry_density: tuple[int, int]
    climax_gap: int = Field(ge=1)
    deadline_margin: int = Field(ge=0)
    ratio_redlines: dict[str, tuple[float, float]]
    poison_points: dict[str, float] = Field(default_factory=dict)
    pacing_default: str = ""
    tone: str = ""
