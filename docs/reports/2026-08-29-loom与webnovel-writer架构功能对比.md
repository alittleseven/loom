# loom 与 webnovel-writer（v6）架构与功能对比

- 日期：2026-08-29
- 对比对象：`projects/loom` @ `f917163`（loom-1 参考实现，约 4.2k 行）× `projects/claude-plugins/webnovel-writer`（上游 lingfengQAQ/webnovel-writer v6.2.1 的本地改造版 v6.3.0，插件包内 Python 生产代码约 5.5 万行、含测试约 8 万行）
- 证据来源：loom 两轮审阅报告 + webnovel-writer 插件源码（README、webnovel.py 命令面、index_manager 15 张表、webnovel-write SKILL 流程、4 个 agent、hooks）

## 一、先说血缘：webnovel-writer 就是 loom 的「v6」

loom 文档里的"v6 书稿 / v6 → loom-1 迁移 / core/legacy【GPL 隔离区】v6 移植零件"指的正是本地这份 webnovel-writer。fantasy01（loom-books）就是从 v6 格式迁入 loom-1 的实测书。所以这不是两个平行产品的对比，而是**同一作者对同一问题的两次作答**：loom 是对 v6 的架构级重写（"参考实现"），v6 的痛点直接铸成了 loom 的红线。

## 二、一句话定位

- **webnovel-writer（v6）**：寄生在 Claude/ZCode 宿主里的**写作插件**——宿主 agent 就是写手大脑，Python 脚本（约 35 个 CLI 子命令、15 张 SQLite 表、RAG/CSV 检索、dashboard）为它供弹药、管状态、做备份。
- **loom**：**独立单机 CLI**——确定性 Python 内核掌管流程与质量门，LLM 降格为六个单发 API 调用点（渲染/双审/scribe/规划），不经任何宿主 agent。

## 三、五个架构分野

### 1. 谁是大脑：宿主智能体 vs 确定性内核

v6 的 `/webnovel-write` 六步（context-agent 研究 → 宿主起草 → reviewer 审查 → 润色 → data-agent 提取落库 → git 备份）中，**起草、润色、裁决都是宿主 agent 的推理行为**，脚本只是工具。loom 把同一流程倒过来：`run_chapter` 流水线是内核代码，渲染/评审是可替换的 HTTP 单发调用，"写作智能"被压缩到 prompt 资产 + 分档路由里。代价是 loom 放弃了 agent 式的灵活发挥；收益是整条流水线**可测试、可重放、可无人值守**（148 项确定性测试、故障注入、cassette 回放——v6 的行为面无法这样测）。

### 2. 真理在哪：多头真理 vs 文件即真相

v6 的状态同时活在 **SQLite 15 张表**（chapters/entities/relationships/state_changes/chase_debt/review_metrics…）+ **state JSON** + **Markdown 设定集** + **RAG 向量/BM25 索引**四处，靠 projection（commit 后投影，支持 retry/replay）维持同步——这正是 loom 方案 §2.2 点名的"角色在 DB 里死了、在 state.json 里活着"的多头真理问题，也是 loom 红线明文禁止带入的模式。loom-1 把正本收敛为**一个 git 仓库的普通文件**，front matter 结构化声明供机检消费，唯一持久派生物 `.cache/index.db` 可删可重建，一致性用"条目三本账 + 每章必须 touch + settle 原子事务"维护。

### 3. 系统如何变聪明：运行时学习 vs 离线进化（方向相反）

- v6 `webnovel-learn`：从当前会话提取成功写法 → 写入 `project_memory.json` → **后续会话直接读它改变行为**。运行时自我修改。
- loom `evolve`：signals 只做旁路采集，分析/提案/盲测/合并全部离线，红线明文"**运行时永不读 signals 调整行为**"；prompt 变更必须过 bench 拒绝式回归 + holdout 盲判 + 作者批准 + 快照可回滚。

这是两套价值观：v6 信任"边写边学"的灵活性，loom 信任"变更可审计"的稳定性（防口味自我强化、防不可回滚的行为漂移）。

### 4. 质量把关：LLM 审查为主 vs 程序化机检为主

v6 也有程序化闸门（write-gate 自然边界、timeline-check 单调校验、anti_ai_force_check），但主体是 **reviewer 子代理的 LLM 逐维度审查**，且"只跑一轮、blocking 定点修复或用户裁决"。loom 把这个思路推到极致：**机检十项 + plan_gates 六道全部零 LLM**（禁词/泄密/履约 diff/时间线/字数/n-gram 复读/条目形式/配比/无钩…），确定性、可重放、近零成本；LLM 双审只管脚本算不了的逻辑矛盾与叙事断裂，且 sha256 绑定被审草稿。再叠加七项熔断（趋势层）与三档自治——这套"机检先行 + LLM 兜底 + 熔断止损"的分层是 v6 没有的。

### 5. 人在哪：每章在环 vs 批末人验

v6 是交互式写作：用户看着 agent 写，blocking 问题用 `AskUserQuestion` 当场裁决。loom 是批次生产：`batch arm/run` 在 L2 自治档下连写 8 章无人值守，人只在批次末看人验简报（摘要链/条目结转/成本账单）后 `accept`。前者适合精雕，后者适合量产，且 loom 用锁 + fail-closed 保证无人值守时的安全边界。

## 四、功能覆盖差异

**v6 有、loom（有意）没有**：
- Dashboard 只读可视化面板（预打包前端）
- RAG 检索（向量 + BM25 降级链）与 9 个题材 CSV 知识库（loom 只移植了 csv_retrieval 到隔离区，pack 用触发式注入替代）
- 实体链接/别名消歧（entity_linker、aliases 表、disambiguation_result）——对人物关系复杂的书是真实能力差
- 追读债/追更力追踪（chase_debt、chapter_reading_power）、行为 evals、参考书拆解 agent、运行时学习（learn）、会话钩子（session_start 注入/guard 写保护）

**loom 有、v6 没有**：
- settle 原子事务（git plumbing 五段式 + 故障注入矩阵 + 幂等 recover）、哈希防串稿、定稿只增不改 + retcon(N) 显式事务
- 机检十项 + plan_gates 六道（确定性）、七项熔断、三档自治、批次状态机
- 成本电表（分档路由 + 逐章 token 账单 + 黄灯）、盲测金标准集 → 模型路由表
- prep 确定性上下文编译器（pack 恒定 ≤5k token，300 章压测硬验收）
- 配置-实现一致性检查、书仓体检 doctor 带修复卡

**loom 已从 v6 继承的**：`core/legacy/` 隔离区现移植了合同引擎（含:禁:字数断言语法）与 CSV 检索两个零件；写前闸门、时间线校验、记忆四态、run-ledger 的思想已用新架构重写落位（checks/settle/staging），不再走隔离区。

## 五、评价

- **规模比约 13:1**（5.5 万行 vs 4.2k 行）。v6 用代码厚度换 agent 灵活性，loom 用架构纪律换确定性与可测试性。loom 砍掉的多数是"重状态、重检索"的能力，替代品（触发式注入、名册触发器、条目账本）在 34→300 章压测下成立；**实体消歧是其中最实的损失**，人物网一复杂建议从 v6 回移植（进隔离区）。
- **两代工具是互补而非替代关系**：v6 适合"作者陪着写"的精雕模式与已有 v6 书稿；loom 适合"批末验收"的量产模式与从零起的新书。v6 → loom-1 迁移器 + fantasy01 实测保证了书稿资产可单向升级。
- **风险提示**：loom 的无人值守质量上限取决于 prompt 资产与盲测路由表的标定成熟度——目前机检/熔断已就位，但 routing_table 依赖作者盲排（ranks.csv）尚未见到实际产出，这是量产模式开动前唯一的空档。
