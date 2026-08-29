# loom（织机 Loom）— 项目级开发约定

> 本文件适用于本项目目录内所有工作。继承全局 `AGENTS.md`，以下规则优先。

## 项目定位

中文网文 AI 写作工具：loom-1 书仓格式的参考实现。单一 Python CLI，命令名 `loom`。个人自用 + 开源（GPL-3.0-or-later），单机优先 Windows。

- 基线方案：`docs/plans/织机Loom-最终方案-v3.0-终审整合版.md`（动工前基线，凡冲突以该文为准）
- 动工前审阅结论：`docs/reports/2026-08-28-织机Loom-v3.0-终审整合版审阅报告.md`（通过；A1–A13 remarks，其中 A1–A3 须在 P0 spec 冻结时一并解决）

## 技术栈

- 语言：Python 3.13 单体 CLI；无服务、无数据库（仅 `.cache` 索引用 SQLite，开 WAL）
- 依赖：pydantic（结构化输出与校验）、GitPython（git 操作）、标准库优先
- 打包：pyproject.toml + setuptools；入口 `loom = loom.cli:main`

## 常用命令（P0 实测）

```powershell
pip install -e ".[dev]"   # 开发安装（pydantic / GitPython / pyyaml + pytest / ruff）
pytest                    # 测试（schema 表驱动 / settle 故障注入 / 长路径 / 配置一致性）
ruff check .              # Lint
loom init <dir> --genre <题材>   # 初始化 loom-1 书仓
loom doctor <dir>                # 书仓体检
```

- loom-1 格式规范（normative）：`docs/plans/loom-1-格式规范-v0.1.md`（P0 冻结：四张 schema + 写侧家族 + 豁免载体 A1 + 配比口径 A3 + run-ledger 落盘 A8 + 只增不改粒度 A11）；工作区技能 `.agents/skills/loom-1-spec` 为其常驻摘要（冲突以本规范为准，spec 变更须同步该技能）
- 模型路由基线：GLM-5.3-Flash（见 `docs/decisions/0001-模型路由基线-GLM-5.3-Flash.md`）

## 目录结构（2026-08-29 审阅后与实现对齐；审阅报告 四.1）

```
loom/                         ← 本仓库（工具本体）
├── AGENTS.md                 # 本文件
├── pyproject.toml
├── loom/                     # Python 包根
│   ├── cli.py                # 唯一入口（已落地：init/doctor/next/plan/batch/bench/
│   │                         #   migrate/evolve/ledger/review/golden/volsummary/enhance）
│   ├── pipeline.py           # 单章写作环：决策卡→prep→渲染→机检→双审→结算→scribe
│   ├── planning.py           # 规划环：plan_vol（六道门）+ plan_batch（章纲卡）
│   ├── staging.py            # 批次状态机 + 七项熔断（AGENTS 规划的 core/staging 并入包根）
│   ├── enhance.py            # P5 CLI 编排：synth 合成压测/packcheck/成本面板
│   ├── core/                 # 确定性内核（零 LLM）
│   │   ├── ports.py          #   RepoPort 协议 + GitRepoPort（长路径/故障注入/WinError5 重试）
│   │   ├── seam.py           #   缝协议版本嗅探（SEAM_VERSION 单一来源）
│   │   ├── config.py         #   环境变量与模型路由链
│   │   ├── cache.py          #   .cache SQLite 索引
│   │   ├── repo/             #   书仓读写、front matter、写入所有权矩阵 + 书仓写锁
│   │   ├── legacy/           #   【GPL 隔离区】v6 移植零件（合同引擎/CSV 检索/…）
│   │   ├── prep/             #   上下文编译器（pack 槽位）+ bookmap（L0 骨架/Book Map）
│   │   ├── checks/           #   机检十项 + plan_gates 六道（零 LLM）
│   │   ├── settle/           #   原子事务 + 哈希防串稿 + run-ledger 落库
│   │   ├── ledger/           #   run-ledger 事件链 + signals 埋点 + 成本电表
│   │   ├── migrate/          #   v6 → loom-1 迁移器
│   │   └── doctor/           #   体检 + 修复卡
│   ├── edge/                 # 智能边缘（全部 LLM 调用；单文件模块）
│   │   ├── client/           #   LLMProvider 协议 + HTTP 实现 + Fake 替身
│   │   ├── prompts.py        #   各档 system/user prompt
│   │   ├── renderer.py       #   渲染（分档 + 机检反馈重渲染）
│   │   ├── reviewers.py      #   事实审 + 编辑审（sha256 令牌绑定）
│   │   └── scribe.py         #   章摘要 + 事实提取 + 指纹 + 金句收割
│   └── evolve/               # 品味闭环（离线，只读 signals）
│       ├── bench.py          #   盲测集执行器 + 路由表
│       └── optimizer.py      #   signals 聚合分析 → 提案 → 快照回滚
├── tests/                    # core 表驱动 / prep 快照 / settle 故障注入 / edge cassette
└── docs/                     # research / reports / plans / decisions
```

偏差说明：v3.0 方案 §5.1 规划的 `core/staging`（批次）、edge 子包（renderer/reviewers/scribe）
落为包根/单文件模块，功能等价；如需回归规划布局须整体迁移并同步本表，不做双头维护。

注意：用户的书（loom-1 书仓）是运行时由 `loom init` 创建的独立 git 仓库，不在本仓库内。

## 架构红线（违反即打回）

- `core/` 零 LLM、确定性；一切 LLM 调用只进 `edge/`；`evolve/` 离线，运行时永不读 signals 调整行为
- `core/legacy/` 只进 v6 移植零件，不做新架构；五路投影/多头真理模式禁止带入
- 可机检的必结构化：机检依赖字段一律 front matter 声明，散文段落仅作人读注解
- 定稿只增不改（适用粒度见审阅报告 A11，P0 spec 定）；settle 原子事务；fail-closed
- 盲测金标准集：只作路由事实源 + 拒绝式约束，永不作 fitness；机检通过率永不作 fitness
- 单书仓单写者：批次运行（run_batch）全程持锁文件（含 pid，可重入）；每次 settle 事务嵌套进入；signals append 由内核独占
- 所有产物写入过所有权矩阵：运行时走 BookRepo.write_file 或 settle FileOp；evolve/bench/migrate/synth 不得绕行 port 直写（init 自举除外）
- Windows 基线：全链路 UTF-8（文件 I/O 显式 encoding）；git 中文 message 用 `-F` 文件方式；`core.longpaths=true`

## 编码约定

- 结构化输出用紧凑 JSON（不美化）；渲染正文自然语言直出
- 未知字段容错保留写回，不丢单
- SQLite 开 WAL + busy_timeout；原子写（GitRepoPort.write_text 的 os.replace）对 Windows 瞬时锁错误（WinError 5）自动重试——已落地（审阅报告 四.4）
- 测试策略（N4）：core 表驱动全覆盖；prep 同书同章重编译 pack 字节一致（快照）；settle 故障注入矩阵；edge cassette 录制回放（无 Key 可跑 CI）；CI = Windows 单平台 + 配置-实现一致性检查（book.yaml 无消费点字段报错）

## 文档归档

- 四类子目录语义同全局 AGENTS.md：research / reports / plans / decisions
- 已归档：plans/（v3.0 基线方案、loom-1 格式规范 v0.1、ZCode 工具链与环境准备清单）、reports/（2026-08-28 终审审阅报告、2026-08-29 架构与功能逻辑审阅报告）

## 注意事项

- `spec_version: loom-1`：书仓格式字段变更走 spec 版本演进，不静默改
- LICENSE（GPL-3.0-or-later 全文）已补入仓库根目录（2026-08-29，源 gnu.org canonical 文本）
- 排期与验收硬门禁见基线方案 §6（P0→P1a→P1b→P2 关键路径；任一 Phase 超估 50% 触发范围重审）
