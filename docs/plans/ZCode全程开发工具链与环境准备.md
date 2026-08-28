# loom · ZCode 全程开发工具链与环境准备

> 2026-08-29。依据基线方案 `织机Loom-最终方案-v3.0-终审整合版.md`（下称 v3.0）整理，目标：**全程在 ZCode 内完成 P0–P5 开发**。
> 结论先行：所需 ZCode 技能与插件**已全部就位，无需新装**；Python 开发环境本次已建好并实测通过；剩余 4 项 Human 行动项见 §6。

---

## 1. 结论摘要

| 状态 | 项 |
|---|---|
| ✅ 已就绪（无需动作） | ZCode 六大工作流技能、Python 3.13.5、git 2.50.1、uv 0.8.8 |
| 🔧 本次已配置 | `.venv` + 全依赖安装实测通过；`pyproject.toml` 补 `pyyaml`；`git core.longpaths=true` |
| ⏳ 待 Human（§6） | GitHub CLI 安装、GitHub 远程仓库、LLM API Key、fantasy01 书稿位置 |
| 📌 P0/P1a 决策点（到时再定，不预装） | loom-1 spec skill 创建、httpx 与 token 计数器选型、.env 路由字段定型 |

## 2. ZCode 技能映射（均已安装于工作区，直接可用）

| 技能 | 用途 | 使用时机 |
|---|---|---|
| `dev-workflow` | 需求澄清 → 实施计划 → 验证交付的完整循环 | **每个 Phase 启动时**（P0–P5） |
| `test-driven-development` | Red-Green-Refactor；对应 v3.0 N4 的 core 表驱动全覆盖 | P0 起，全程 core 开发 |
| `systematic-debugging` | 先根因后修复 | 处理 Windows 编码/长路径/SQLite 锁/settle 故障注入问题时 |
| `code-review` | 正确性/安全/风格审查 | **每个 Phase 硬验收前** + P0 spec 对照评审 |
| `commit-discipline` | Conventional Commits、选择性 stage、UTF-8 `-F` 提交 | 每次提交（全局 AGENTS.md 已强制） |
| `zcode-guide` | 配置/诊断 hooks、自定义命令、MCP、skill 未触发问题 | 按需（如配置自动化钩子时） |
| `project-bootstrap` | 新项目初始化 | 已用完（loom 已初始化），不再需要 |

**唯一建议新增的自定义 skill**：P0 spec 冻结后，用 `skill-creator` 把 loom-1 四张 schema、格式纪律、架构红线做成 `loom-1-spec` 工作区技能——保证后续任何会话写书仓代码时规范常驻上下文，不靠人肉重读方案。时机在 P0，不在现在（spec 未冻结，先建会返工）。

## 3. ZCode 插件与 MCP 评估

| 插件 / MCP | 结论 | 理由 |
|---|---|---|
| `skill-creator`、`zcode-guide` | ✅ 保留 | 见 §2 |
| `webnovel-writer` | ⏸ 条件保留 | 非开发依赖；仅当 fantasy01 书稿由该插件管理时，P1b（plan_gates 回测）与 P2（v6→loom-1 迁移）用 `webnovel-query`/`webnovel-dashboard` 只读提取设定与大纲 |
| `browser-use` / `computer-use` | ❌ 不需要 | loom 是纯 CLI，无 GUI 测试面；盲测集走 API 脚本而非网页 |
| `document-skills`（docx/pdf/pptx/xlsx） | ❌ 不需要 | 全部文档为 Markdown |
| 新增 MCP 服务器 | ❌ 无需 | edge 层按 v3.0 走**裸 API**（不经宿主 agent，也不经 ZCode MCP）；GitHub 操作用 `gh` CLI 更轻 |

**关键定位**：ZCode 在本项目中的角色是**开发环境**（写码/测试/审查/提交），不是运行时的 LLM 承载方——运行时模型调用由 loom 自己的 `edge/` 经 `LLMProvider` 协议直连 API。这决定了 API Key 属于书仓运行环境（`.env`），而非 ZCode 配置。

## 4. Python 依赖与环境（本次实测）

**环境实测记录**（2026-08-29，PyPI 直连，未用镜像）：

| 组件 | 版本 | 验证方式 |
|---|---|---|
| Python | 3.13.5（满足 `requires-python >=3.13`） | venv 创建成功 |
| pydantic | 2.13.5 | smoke import |
| GitPython | 3.1.61 | smoke import |
| pyyaml | 6.0.3 | smoke import（本次新增） |
| pytest | 9.1.1 | `pytest --collect-only` 通过 |
| ruff | 0.16.5 | `ruff --version` |
| loom 包 | editable 安装，`import loom` OK | `uv pip install -e ".[dev]"` |

**本次变更**：`pyproject.toml` dependencies 增加 `pyyaml>=6.0`。理由：loom-1 格式全靠 YAML front matter（book.yaml、卷纲/章纲卡/条目账本/决策卡/定稿 front matter），pydantic 只做校验不解析 YAML——v3.0 §5.1 依赖清单的缺口，P0 repo 读写第一天就要用。

**P1a 决策点**（到时再定，避免预装闲置）：
- **HTTP 客户端**：edge 裸 API 建议用 `httpx`（超时/重试/连接池比 stdlib urllib 省事）；若坚持最小依赖，六类单发结构化请求用 urllib 也可行。
- **token 计数**：pack ≤5k 预算需要一个确定性计数器。建议先用 stdlib 估算（中文 ≈1 字 1.5 token，v3.0 §5.3），盲测后如需精确再引 `tiktoken`。

**明确不引入**（守住"依赖最小化"）：
- cassette 录制回放不引 `vcrpy`——在 `LLMProvider` 协议层自制 JSON cassette（≈50 行），天然无 Key 可跑 CI；
- pid 探活不引 `psutil`——`ctypes` 调 `OpenProcess` 足够；
- CLI 不引 `click`/`typer`——argparse 够用。

**Windows 基线**：`git config --global core.longpaths true` 已设（v3.0 §5.4）；全链路 UTF-8 纪律见项目 AGENTS.md，提交走 `commit-discipline` 技能（`-F` 文件方式）。

## 5. 测试与 CI 基础设施（对照 v3.0 N4）

| N4 要求 | 落地手段 | 新增依赖 |
|---|---|---|
| core 表驱动单元测试 | pytest，P0 起 | 无 |
| prep 确定性快照测试 | pytest + 字节级/槽位容差比较 | 无 |
| settle 故障注入矩阵 | kill 点 × `RepoPort` 测试替身重放 | 无 |
| edge 录制回放（cassette） | `LLMProvider` 协议层自制 cassette | 无 |
| CI = Windows 单平台 + 配置-实现一致性检查 | GitHub Actions `windows-latest`（P0 建 workflow） | 无 |

测试与故障注入全部零新增依赖——这是 v3.0 两个接口协议（`LLMProvider`/`RepoPort`）设计的直接红利。CI 的前置条件是 GitHub 远程仓库（§6 行动项 2）。

## 6. 待 Human 行动项（2026-08-29 更新：4 项已完成）

1. ~~安装 GitHub CLI~~ ✅ 已装；**遗留：`gh auth login` 未执行**（推送前需要，Human 手动做一次浏览器授权）。
2. ~~创建 GitHub 远程仓库~~ ✅ `git@github.com:alittleseven/loom.git`（remote 已配置；push 按 AGENTS.md 红线仍等 Human 指令）。
3. ~~填写 `.env`~~ ✅ Key 已入；`.env.example` 已补 `LOOM_LLM_BASE_URL` 与按档位模型名字段，缺省 `glm-5.3-flash`（ADR-0001）。
4. ~~提供 fantasy01 书稿位置~~ ✅ `C:\lgq\workspace\opc_space\projects\webnovel-projects\fantasy01`（34 章，大纲/正文/设定集齐全）。**P1b 前注意**（审阅报告补记口径）：盲测抽样需区分亲笔稿与 v6 工具协作稿，亲笔稿优先，协作稿可另作对照组。

## 7. ZCode 全程开发工作法（每 Phase 固定循环）

```
① dev-workflow 立项（澄清 Phase 硬验收 → TodoWrite 拆任务）
② test-driven-development 写 core（表驱动；修 bug 先写失败测试）
③ systematic-debugging 处理故障（Windows 编码/路径/锁/事务回滚）
④ code-review 过 Phase 验收（对照 v3.0 §6 硬验收逐条核）
⑤ commit-discipline 提交（Conventional Commits + UTF-8 -F；子仓库提交后主仓库同步指针）
⑥ tools/scripts/check-workspace.ps1 收尾自检（零未提交文件才算完）
```

关键路径 P0 → P1a → P1b → P2 串行推进；P1b 可与 P2 搭接、P3 与 P4 可并行（v3.0 §6）。任一 Phase 超估 50% 触发范围重审（先砍 P5）。
