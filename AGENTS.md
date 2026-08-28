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

## 常用命令（规划值，P0 落地后回填实测命令）

```powershell
pip install -e ".[dev]"   # 开发安装
pytest                    # 测试（core 表驱动 / prep 快照 / settle 故障注入 / edge cassette）
ruff check .              # Lint
```

## 目录结构（按 v3.0 方案 §5.1 规划，P0 起逐段填充）

```
loom/                         ← 本仓库（工具本体）
├── AGENTS.md                 # 本文件
├── pyproject.toml
├── loom/                     # Python 包根
│   ├── cli.py                # 唯一入口（init/plan/next/prep/render/check/review/
│   │                         #   settle/batch/evolve/doctor/migrate/ledger/memory）
│   ├── core/                 # 确定性内核（零 LLM）
│   │   ├── repo/             #   书仓读写、front matter、写入所有权矩阵 + 书仓写锁
│   │   ├── legacy/           #   【GPL 隔离区】v6 移植零件（合同引擎/CSV 检索/
│   │   │                     #     写前闸门/时间线校验/记忆四态/run-ledger/RAG 降级链）
│   │   ├── prep/             #   上下文编译器（pack 槽位 + Book Map + L0/L1/L2）
│   │   ├── checks/           #   机检十项 + plan_gates 六道（零 LLM）
│   │   ├── settle/           #   原子事务 + 哈希防串稿 + 批内工件失效锁
│   │   ├── staging/          #   批次状态机 + 七项熔断
│   │   ├── ledger/           #   run-ledger 事件链 + signals 埋点 + 成本电表
│   │   ├── migrate/          #   v6 → loom-1 迁移器
│   │   └── doctor/           #   体检 + 修复卡
│   ├── edge/                 # 智能边缘（全部 LLM 调用）
│   │   ├── client/           #   LLMProvider：路由/重试/记账
│   │   ├── renderer/         #   渲染（分档 + 关键章陪审团）
│   │   ├── reviewers/        #   事实审 + 编辑审（双镜头）
│   │   └── scribe/           #   章摘要 + 事实提取 + 金句收割分类
│   └── evolve/               # 品味闭环（离线，只读 signals）
│       ├── analyzer/         #   signals 聚合分析
│       ├── bench/            #   网文-bench + 盲测集执行器
│       └── optimizer/        #   提案→回归→holdout→人审→快照
├── tests/                    # P0/P1 起：core 表驱动 / prep 快照 / settle 故障注入 / edge cassette
└── docs/                     # research / reports / plans / decisions
```

注意：用户的书（loom-1 书仓）是运行时由 `loom init` 创建的独立 git 仓库，不在本仓库内。

## 架构红线（违反即打回）

- `core/` 零 LLM、确定性；一切 LLM 调用只进 `edge/`；`evolve/` 离线，运行时永不读 signals 调整行为
- `core/legacy/` 只进 v6 移植零件，不做新架构；五路投影/多头真理模式禁止带入
- 可机检的必结构化：机检依赖字段一律 front matter 声明，散文段落仅作人读注解
- 定稿只增不改（适用粒度见审阅报告 A11，P0 spec 定）；settle 原子事务；fail-closed
- 盲测金标准集：只作路由事实源 + 拒绝式约束，永不作 fitness；机检通过率永不作 fitness
- 单书仓单写者：批次运行持锁文件（含 pid）；signals append 由内核独占
- Windows 基线：全链路 UTF-8（文件 I/O 显式 encoding）；git 中文 message 用 `-F` 文件方式；`core.longpaths=true`

## 编码约定

- 结构化输出用紧凑 JSON（不美化）；渲染正文自然语言直出
- 未知字段容错保留写回，不丢单
- SQLite 开 WAL + busy_timeout；原子写对 Windows 瞬时锁错误（WinError 5）自动重试
- 测试策略（N4）：core 表驱动全覆盖；prep 同书同章重编译 pack 字节一致（快照）；settle 故障注入矩阵；edge cassette 录制回放（无 Key 可跑 CI）；CI = Windows 单平台 + 配置-实现一致性检查（book.yaml 无消费点字段报错）

## 文档归档

- 四类子目录语义同全局 AGENTS.md：research / reports / plans / decisions
- 已归档：plans/（v3.0 基线方案）、reports/（2026-08-28 终审审阅报告）

## 注意事项

- `spec_version: loom-1`：书仓格式字段变更走 spec 版本演进，不静默改
- LICENSE（GPL-3.0-or-later 全文）在首次开源发布前补入
- 排期与验收硬门禁见基线方案 §6（P0→P1a→P1b→P2 关键路径；任一 Phase 超估 50% 触发范围重审）
