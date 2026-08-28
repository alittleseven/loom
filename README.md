# loom · 织机 Loom

中文网文 AI 写作工具——让"会遗忘、会幻觉、没有品味的天才写手"（大语言模型）连续工作 300 章不出事的生产系统。

- **形态**：单一 Python CLI（命令 `loom`），单机优先 Windows；个人自用 + 开源（GPL-3.0-or-later）
- **基线方案**：[docs/plans/织机Loom-最终方案-v3.0-终审整合版.md](docs/plans/织机Loom-最终方案-v3.0-终审整合版.md)（版本谱系 v1.0 → v2.0 → v3.0 见该文 §9）
- **格式规范**：[docs/plans/loom-1-格式规范-v0.1.md](docs/plans/loom-1-格式规范-v0.1.md)（P0 冻结，normative）
- **动工前审阅**：[docs/reports/2026-08-28-织机Loom-v3.0-终审整合版审阅报告.md](docs/reports/2026-08-28-织机Loom-v3.0-终审整合版审阅报告.md)（通过；A1–A13 已在 P0 落实）

## 核心思路（30 秒版）

三层两缝一闭环：确定性内核 `core`（零 LLM：书仓读写 / 上下文编译 / 机检 / 原子结算）+ 智能边缘 `edge`（全部 LLM 调用）+ 离线品味闭环 `evolve`。上下文是编译出来的（每章 ≤5k token 恒定包）；一致性靠结构化条目账本与机检；作者的交互单位是决策卡，不是聊天。

## 当前状态（P0–P5 全部落地）

| Phase | 内容 | 状态 |
|---|---|---|
| P0 | loom-1 spec 冻结 + settle 原子事务（故障注入验收）+ 写锁/所有权矩阵 + cache 可删重建 + doctor | ✅ |
| P1a | 单章闭环：prep 编译器（快照确定性）+ 渲染/双审/scribe + 机检十项 + 金句收割 + signals 埋点 | ✅ |
| P1b | 规划环 plan vol/batch（plan_gates 六道 + 反馈重生成）+ 盲测集执行器 + L1 卷摘要 | ✅ |
| P2 | v6→loom-1 迁移器（源只读/零残留/待校对清单），fantasy01 34 章冒烟通过 | ✅ |
| P3 | 批次状态机 + 七项熔断 + 三档自治 + 人验简报 + 断点恢复 | ✅ |
| P4 | signals 聚合周报 + bench 拒绝式约束（永不作 fitness）+ 提案-快照-回滚 | ✅ |
| P5 | L0 骨架 + Book Map 完整版 + 成本面板 + 300 章合成压测（pack 恒定）| ✅ |

模型路由（ADR-0002）：OCGO glm-5.3-flash → deepseek-v4-flash → OCGO messages qwen3.8-flash → Ali Token Plan qwen3.8-flash → GLM 兜底，失败自动降级，cassette 回放使 CI 无 Key 可跑。

## 快速上手

```powershell
pip install -e ".[dev]"          # 安装（Python ≥3.13）
copy .env.example .env           # 填入 API Key（严禁提交）
pytest                           # 126 项测试
ruff check .                     # Lint

loom init 我的书 --genre 都市异能   # 建书仓
loom plan 我的书 vol                # 生成卷纲（过六道机检）
loom plan 我的书 batch --vol 1 --start 1 --yes   # 生成并批准 8 章章纲
loom next 我的书 --chapter 1        # 写第 1 章（渲染→机检→双审→结算→scribe）
loom doctor 我的书                  # 体检
loom migrate 旧书目录 新书仓 --genre 末世求生     # v6 迁移
```

## 命令面

`init` / `plan vol|batch` / `next` / `batch`（P3 状态机）/ `evolve`（P4 提案-快照）/ `bench` / `doctor` / `migrate` / `ledger` / `memory`（随用随补）

## 红线（违反即打回）

- `core/` 零 LLM；`evolve/` 离线，运行时永不读 signals
- 盲测金标准集：只作路由事实源 + 拒绝式约束，**永不作 fitness**；机检通过率永不作 fitness
- 定稿只增不改（改写走显式 `retcon(N)`）；settle 原子事务；fail-closed
- 单书仓单写者；真实密钥永不入库（`.env` 已 gitignore）
