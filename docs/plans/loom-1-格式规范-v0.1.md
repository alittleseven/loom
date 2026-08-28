# loom-1 书仓格式规范 v0.1（P0 冻结版）

> spec_version: `loom-1`；本文件为格式的规范性定义（normative），实现（本仓库代码）是其参考实现。
> 冻结日期：2026-08-29。冻结范围：目录树、book.yaml v0.1 字段、规划侧四张 schema、写侧 schema 家族（A2）、豁免载体（A1）、章节类型枚举与配比口径（A3）、run-ledger 落盘位置（A8）、只增不改粒度（A11）、commit 机器协议、结算协议、写入所有权矩阵、seam_version。
> 演进规则：任何字段变更走 spec 版本演进（v0.x 增量 → v1.0 首个稳定版），实现按 `spec_version` 嗅探兼容，不静默改。open issues 见文末。

---

## 1. 书仓目录树

一本书 = 一个独立 git 仓库。UTF-8 全链路。

```
book.yaml                 书级配置（§4）
定稿/
  正文/ch0001.md          正文 front matter（§6.1）+ 正文；append-only（§3.5）
  摘要/ch0001.md          本章摘要 ≤150 字 + 承接点（front matter: chapter/word_count）
  卷摘要/vol01.md         L1 卷摘要（front matter: vol/source_chapters[]）
  设定/{名册,世界观,信息差,时间线,角色}/*.md   设定条目，一文件一条（§6.2）
  记忆/文体指纹.json      七维文风基线 + 滚动值（§6.3）
大纲/
  总纲.md                 自由散文（人读）
  卷纲/volNN.md           卷纲（§5.1，plan_gates 六道数据源）
  章纲/chNNNN.md          章纲卡（§5.2）
  条目/{伏笔,悬念,感情线}/<id>.md   三本账（§5.3）
文风/
  风格宪法.md             禁词/禁句式/口癖，每条带出处章号
  金句库/<场景>.md        每场景 ≤20 条（LRU）
  场景技能/<场景>.md      写法要点 + 正反例
  题材/<genre>.md         题材 profile（§6.4）
工作区/                   【gitignored】决策卡/本章材料/草稿/审稿/增强信号缓存
演化/
  signals.jsonl           旁路行为信号（append-only，内核独占写）
  run-ledger.jsonl        生产审计事件链（append-only，入 git）（A8）
  bench/                  bench 报告与进化提案（P4 起使用）
bench/blindset-v1/        盲测金标准集（P1b 起建设）
.cache/                   【gitignored】index.db 唯一持久派生物，可删可重建（§7）
.loom/lock.json           书仓写锁（含 pid，gitignored）（§9）
```

## 2. 通用规则

1. **front matter**：所有结构化 Markdown 文件用 YAML front matter（`---` 包裹）；正文内容跟随其后。JSON 文件（文体指纹）直接 JSON。
2. **容错读写**：读取端对未知字段**保留写回，不丢单**；front matter 解析失败即报错（fail-closed），不做静默猜测。
3. **可机检的必结构化**：机检与 plan_gates 依赖的字段一律为 front matter 结构化声明；散文段落仅作人读注解，不参与机检。
4. **条目稳定 id**：`{类型前缀}-{三位数字}`，前缀 `F`=伏笔、`S`=悬念、`R`=感情线（如 `F-058`）。id 是外部引用的唯一键（为系列书共享设定留句法），文件路径不是键。
5. **只增不改粒度**（A11）：
   - `定稿/正文/`、`定稿/摘要/`、`定稿/卷摘要/`：**文件级 append-only**——已存在章节文件的内容永不修改；修正走显式 `retcon(N)` 事务（见 §8），是唯一合法改写通道且必须在 commit message 留痕；
   - `定稿/设定/`、`定稿/记忆/`：内容**可变**（状态迁移 active→outdated、滚动值更新合法），但每次变更仍须经 settle 事务入 git，不得绕过；
   - 判定实现：settle 对正文/摘要/卷摘要路径执行"目标文件已存在且内容不同 → 拒绝，除非 `retcon=True`"。
6. **记忆四态**：设定条目与条目账本共用 `active / tentative / outdated / contradicted`；矛盾不入库（先 tentative + 人审）。
7. **seam_version**：`工作区/` 下所有 core↔edge 交换文件带 `seam_version` 字段（当前 `"1"`）；core 读取时嗅探，不匹配显式报 `SeamVersionMismatch`（降级拒绝），不静默错读。
8. **commit message 机器协议**：标题 `ch(NNN)/vol(NN)/retcon(N)/fix(手改)/batch(N..M)` 之一（init 提交为 `init: loom-1 书仓初始化`）；正文行必须含条目结转声明：`条目: +F-058 ~S-031 $R-019`（`+`开启 `~`推进 `$`兑付，可缺省为 `条目: -`，如决策卡豁免章）。

## 3. book.yaml（v0.1 冻结字段）

平铺 ≤15 行。**配置-实现一致性**：每个字段必须有代码消费点，CI 检查无消费者字段直接报错（N1）——因此 v0.1 只冻结当前已消费的字段，规划字段随后续 Phase 落地逐个入册。

| 字段 | 类型 | 消费点（P0） |
|---|---|---|
| `spec_version` | `loom-1` | repo 载入校验 |
| `genre` | str | init 装题材 profile、doctor |

**规划字段（未冻结，随 Phase 启用）**：`autonomy`（L0/L1/L2，P3）、`batch_size`（P3，默认 8）、`pack_budget_tokens`（P1a，默认 5000）、`rhythm_overrides`（P1a：条目密度区间/爽点间距 N/期限余量 K）、`model_routing`（P1a：渲染档/评审档/scribe 档/小档）、`breaker_overrides`（P3）。示例（P1a 后形态）见附录 A。

## 4. 规划侧四张 schema（P0 冻结）

### 4.1 卷纲 `大纲/卷纲/volNN.md`

front matter（plan_gates 六道全部数据源）：

```yaml
---
spec_stage: plan        # 固定值，供嗅探
vol: 1
climax_chapters: [12, 20]          # 高潮点章号列表（gate 3）
entry_plan:                        # 条目计划（gate 1/2/5）
  - {id: F-001, action: 开启, due_chapter: 16}
  - {id: F-000, action: 兑付, due_chapter: 14}   # overdue 条目兑付安排
time_span: {start: "元启三年春", end: "元启三年夏"}   # 时间锚点对（gate 4）
chapter_types: {ch0001: main, ch0002: transition}    # 章节类型标注（§5，gate 6）
rhythm: {entry_density: [2, 4], climax_gap: 8, deadline_margin: 5}  # 节奏预算槽
waivers: []                        # 豁免卡（A1，见下）
---
# 卷一（散文段：卷目标/主线推进/卷末钩子，仅人读）
```

### 4.2 章纲卡 `大纲/章纲/chNNNN.md`

```yaml
---
spec_stage: chapter_card
chapter: 3
touches: [F-001, S-002]   # 本章 touch 的条目 id；与 touch_waiver 二选一（机检：≥1 或显式豁免）
touch_waiver: null        # {reason: str, approved_by: author, source: decision_card|vol_outline}
scenes: 2                 # 场景数 2–3
hook_type: cliff          # 枚举：cliff|reveal|decision|emotion|peace（peace 不得连续两章）
time_anchor: "元启三年春·三日后"
word_tier: standard       # standard|climax|setup（映射渲染档与字数预算）
---
# 散文段（场景要点，仅人读）
```

### 4.3 条目账本 `大纲/条目/{伏笔,悬念,感情线}/<id>.md`

文件名 = 条目 id。front matter：

```yaml
---
id: F-001
kind: 伏笔          # 伏笔|悬念|感情线（目录须一致）
strength: high      # high|mid|low（高强度条目超期产生节奏债）
status: active      # active|tentative|outdated|contradicted|paid（记忆四态 + paid）
opened_ch: 3
due_ch: 16          # 期限章（gate 1）
last_touched_ch: 9
---
# 散文段：条目内容描述（人读）
```

### 4.4 决策卡 `工作区/决策卡/chNNNN.md`（gitignored，临时工件）

```yaml
---
spec_stage: decision_card
seam_version: "1"
chapter: 3
generated_by: plan_template   # plan_template(L2 零LLM投影)|llm|author
touch_waiver: null            # A1：豁免作为决策卡字段；每章结算 touch≥1 或持本章豁免
contract:                     # 本章要兑现的可机检断言（settle 履约 diff 数据源）
  - "李浮舟首次使用『借灾』且未失控"
options: []                   # 备选提案
---
# 四段固定：## 盘面 / ## 提案 / ## 合同 / ## 备选
```

**豁免规则（A1 定案）**：豁免**不是独立卡型**，是三张卡上的结构化字段 `touch_waiver`（章纲卡 / 决策卡 / 卷纲 `waivers[]` 计划级豁免）。字段三要素 `reason / approved_by / source` 缺一不可；`approved_by` 只能是 `author`——LLM 与内核无权豁免。机检遇 `touches` 为空时查 `touch_waiver`，两者皆无 → 违例。

## 5. 章节类型枚举与配比口径（A3 定案）

- **枚举写死**：`main`（主线推进）/ `romance`（感情）/ `side`（支线）/ `climax`（高潮）/ `transition`（过渡/日常）。
- **配比归并**：主线 = `main + climax`；感情 = `romance`；支线 = `side + transition`。
- **配比计算口径**：卷级配比 = 卷纲 `chapter_types` 全卷章数按上述归并的占比；gate 6 对照题材 profile 的 `ratio_redlines`（如 `main: [0.55, 0.85]`）。条目账本类型轴（伏笔/悬念/感情线）与配比轴是两套分类，不做互推；感情线条目的开启/推进章应标注 `romance` 型（机检给提示级 warning，不阻断）。

## 6. 写侧 schema 家族（A2 冻结）

### 6.1 正文 front matter `定稿/正文/chNNNN.md`

```yaml
---
spec_stage: manuscript
chapter: 3
title: 灾从口入
time_anchor: "元启三年春·三日后"     # 时间线校验数据源（单调性/区间）
entry_changes:                        # 条目变动声明（与 commit message 条目行一致）
  - {id: F-001, action: "+"}
  - {id: S-002, action: "~"}
contract_digest: ["李浮舟首次使用『借灾』且未失控"]   # 决策卡合同段的结算快照
word_count: 3012                      # 字数预算检查数据源
---
正文……
```

### 6.2 设定条目 `定稿/设定/<家族>/<slug>.md`

家族 = `名册|世界观|信息差|时间线|角色`。front matter：

```yaml
---
id: set-ming-ce-001        # 设定条目 id：set- 前缀 + 家族 slug + 序号；跨书引用走 id
family: 名册
name: 李浮舟
status: active             # 记忆四态
triggers: ["李浮舟", "浮舟"]   # 名册条目关键词触发器（prep 触发式注入数据源；其他家族可为空）
---
# 家族附加字段（可机检字段进 front matter，可选）：
#   信息差：known_by: [...]（谁知情），读者可见性 hidden|revealed@chN
#   时间线：ch: N；book_time: "元启三年春"；event: "一句话事件"；present: [在场人物]（append-only 列，C3）
#   角色：role: 主角|配角|反派；first_ch: N
```

### 6.3 文体指纹 `定稿/记忆/文体指纹.json`

```json
{
  "spec_stage": "style_fingerprint",
  "baseline": {"avg_sentence_len": 18.2, "sentence_len_var": 42.1, "dialogue_ratio": 0.41,
                "avg_para_len": 3.2, "ttr": 0.36, "sensory_density": 0.08, "metaphor_density": 0.03},
  "rolling": {"ch0001": {"...七维同上": 0}, "ch0002": {}},
  "baseline_range": {"from_ch": 1, "to_ch": 30}
}
```

七维定义：平均句长、句长方差、对话占比、平均段长、词汇丰富度（type-token ratio）、感官描写密度、比喻密度。全部脚本可算、零 LLM。

### 6.4 题材 profile `文风/题材/<genre>.md`

```yaml
---
spec_stage: genre_profile
genre: 都市异能
entry_density: [2, 4]        # 本卷计划开启条目数区间（gate 2）
climax_gap: 8                # 高强度条目/高潮点间隔上限（gate 3）
deadline_margin: 5           # 期限章 ≤ 卷末章 + K（gate 1）
ratio_redlines: {main: [0.55, 0.85], romance: [0.1, 0.35], side: [0.0, 0.3]}   # gate 6
poison_points: {"圣母": 0.9, "降智": 0.9}     # 毒点权重
pacing_default: "三章一小爽，十章一大爽"
tone: 热血
---
# 散文段：题材节奏与写法默认值（人读）
```

## 7. 缓存 `.cache/index.db`

SQLite，WAL + `busy_timeout=5000`。存 `SCHEMA_VERSION`；版本不符即全量删除重建。内容：设定条目与账本条目的 `id → (kind, status, path, content_hash)` 索引。**唯一持久派生物**：删除后由源文件全量重建，重建结果与原查询一致是硬验收。

## 8. 结算协议（settle）

1. 前置校验：正文/摘要 front matter 合法、`entry_changes` 与章纲/决策卡一致、**哈希防串稿**（被审草稿 sha256 == 送审草稿 sha256，防"旧审配新稿"）、append-only 粒度检查（§2.5）。
2. 组装本次事务全部文件写入（正文/摘要/设定更新/账本 touch）。
3. **git plumbing 原子提交**：`hash-object -w` 写 blob → 组树（临时 index）→ `commit-tree`（机器协议 message）→ `update-ref`（**唯一原子点**）→ 同步工作树（reset --hard）。`update-ref` 之前任何一步 kill/异常：仓库零痕迹；之后 kill：工作树短暂落后于 HEAD，重放恢复 = `git reset --hard HEAD`（幂等，doctor 出修复卡）。
4. 结算后动作（P1a 起）：scribe 章摘要/事实提取/金句收割——第二次落库走独立 commit（`scribe(chN)` 前缀，A9 遗留项：10 类事件枚举在 P1a 成文）。
5. run-ledger：每次 settle 全链路事件（计划→渲染→机检→评审→结算）追加至 `演化/run-ledger.jsonl`（入 git，A8）；signals 同目录旁路采集。

## 9. 写入所有权矩阵与书仓写锁（M6/N5）

| 路径 | settle | scribe | prep/check/review | author |
|---|---|---|---|---|
| 定稿/正文/** | ✅（retcon 需显式） | ❌ | ❌ | ✅（仅 retcon(N) 事务） |
| 定稿/摘要/、卷摘要/ | ✅ | ✅ | ❌ | ❌ |
| 定稿/设定/、记忆/ | ✅ | ✅（滚动值） | ❌ | ✅ |
| 大纲/** | ✅（账本 touch） | ❌ | ❌ | ✅ |
| 工作区/** | ✅（清场） | ✅ | ✅（本环节文件） | ✅ |
| 演化/signals.jsonl | 内核独占 append | ❌ | ❌ | ❌ |

书仓写锁 `.loom/lock.json`（`{pid, started_at}`）：批次/settle 运行期间持有；pid 存活检测（Windows ctypes OpenProcess），stale 锁自动接管并告警。锁持有期间作者写命令拒绝（读不受限）——单书仓单写者。

## 10. 开放议题（沿 v3.0 §8，另新增）

- pack 字节级规范化规则（P1a 快照测试时定）；
- scribe 10 类事件枚举（P1a 成文，A9）；
- 跨批次 retcon 影响面分析上限；
- 本版新增：` 章纲卡 hook_type=peace 连续两章` 的机检阈值是否随题材 profile 可配（默认不可，P1a 实测再定）。

## 附录 A：book.yaml P1a 后目标形态（非冻结）

```yaml
spec_version: loom-1
genre: 都市异能
autonomy: L1
batch_size: 8
pack_budget_tokens: 5000
rhythm_overrides: {climax_gap: 6}
model_routing: {render: glm-5.3-flash, review: glm-5.3-flash, scribe: glm-5.3-flash, small: glm-5.3-flash}
breaker_overrides: {}
```
