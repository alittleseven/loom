# loom · 织机 Loom

中文网文 AI 写作工具——让"会遗忘、会幻觉、没有品味的天才写手"（大语言模型）连续工作 300 章不出事的生产系统。

- **形态**：单一 Python CLI（命令 `loom`），单机优先 Windows；个人自用 + 开源（GPL-3.0-or-later）
- **基线方案**：[docs/plans/织机Loom-最终方案-v3.0-终审整合版.md](docs/plans/织机Loom-最终方案-v3.0-终审整合版.md)（版本谱系 v1.0 → v2.0 → v3.0 见该文 §9）
- **动工前审阅**：[docs/reports/2026-08-28-织机Loom-v3.0-终审整合版审阅报告.md](docs/reports/2026-08-28-织机Loom-v3.0-终审整合版审阅报告.md)——结论：通过，可作动工基线；13 项 remarks（A1–A13），无架构级缺陷，A1–A3 须随 P0 spec 冻结解决

## 核心思路（30 秒版）

三层两缝一闭环：确定性内核 `core`（零 LLM：书仓读写 / 上下文编译 / 机检 / 原子结算）+ 智能边缘 `edge`（全部 LLM 调用）+ 离线品味闭环 `evolve`。上下文是编译出来的（每章 ≤5k token 恒定包）；一致性靠结构化条目账本与机检；作者的交互单位是决策卡，不是聊天。

## 当前状态

项目刚完成初始化：目录骨架（按方案 §5.1）+ 基线方案归档 + 动工前审阅报告。代码未启动。

下一步是 **P0：loom-1 spec 冻结（规划侧四张 schema + 写侧 schema 家族）与内核骨架**，实施计划见方案 §6（总计 ≈41–58 人日）。

## 命令面（规划）

`init` / `plan vol` / `plan batch` / `next` / `prep` / `render` / `check` / `review` / `settle` / `batch` / `evolve` / `doctor` / `migrate` / `ledger` / `memory`
