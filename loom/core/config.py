"""运行时配置：.env 加载与模型降级链（ADR-0002）。

依赖最小化：不用 python-dotenv，自带 12 行解析器。
真实环境变量优先于 .env 文件值。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Endpoint:
    name: str        # 端点组名（ocgo/ocgo-ali/ali/glm）
    base_url: str
    api_key: str
    model_id: str
    wire: str        # openai | anthropic


def load_env(*paths: Path | str | None) -> dict[str, str]:
    """依次读取 .env 文件（先到先得，setdefault），真实环境变量最后覆盖。"""
    env: dict[str, str] = {}
    for p in paths:
        if not p:
            continue
        path = Path(p)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    for key, value in os.environ.items():
        if key.startswith("LOOM_"):
            env[key] = value
    return env


def build_chain(env: dict[str, str]) -> list[Endpoint]:
    """按 ADR-0002 顺序装配降级链；未配置 Key 的端点跳过。"""
    chain: list[Endpoint] = []
    ocgo_key = env.get("LOOM_OCGO_API_KEY", "")
    ocgo_base = env.get("LOOM_OCGO_BASE_URL", "")
    if ocgo_key and ocgo_base:
        if env.get("LOOM_OCGO_MODEL_ID"):
            chain.append(Endpoint("ocgo", ocgo_base, ocgo_key, env["LOOM_OCGO_MODEL_ID"], "openai"))
        if env.get("LOOM_OCGO_MODEL_ID2"):
            chain.append(Endpoint("ocgo", ocgo_base, ocgo_key, env["LOOM_OCGO_MODEL_ID2"], "openai"))
        ocgo_ali = env.get("LOOM_OCGO_ALI_BASE_URL", "")
        if ocgo_ali:
            chain.append(Endpoint(
                "ocgo-ali", ocgo_ali, ocgo_key,
                env.get("LOOM_OCGO_ALI_MODEL_ID", "qwen3.8-flash"), "anthropic",
            ))
    if env.get("LOOM_ALI_API_KEY"):
        chain.append(Endpoint(
            "ali", env.get("LOOM_ALI_BASE_URL", ""), env["LOOM_ALI_API_KEY"],
            env.get("LOOM_ALI_MODEL_ID", "qwen3.8-flash"), "openai",
        ))
    if env.get("LOOM_LLM_API_KEY"):
        chain.append(Endpoint(
            "glm", env.get("LOOM_LLM_BASE_URL", ""), env["LOOM_LLM_API_KEY"],
            env.get("LOOM_LLM_MODEL", "glm-5.3-flash"), "openai",
        ))
    return chain


def find_env_files(book_root: Path | None = None) -> list[Path]:
    """.env 查找顺序：书仓根 → 工具仓库根（本仓库）。"""
    candidates: list[Path] = []
    if book_root:
        candidates.append(Path(book_root) / ".env")
    candidates.append(Path(__file__).resolve().parents[2] / ".env")
    return candidates
