"""配置-实现一致性（N1）与接口协议替身（P0 验收项）。"""
from __future__ import annotations

from pathlib import Path

import loom
from loom.core.ports import RepoPort
from loom.core.repo.consumption import check_config_consumption
from loom.core.repo.schema import BookConfig
from loom.edge.client.protocol import (
    TIERS,
    FakeLLMProvider,
    LLMProvider,
    ProviderResult,
)
from tests.fakes import InMemoryRepoPort

PKG_DIR = Path(loom.__file__).parent


def test_book_config_fields_all_consumed():
    missing = check_config_consumption(BookConfig.model_fields.keys(), PKG_DIR)
    assert missing == [], f"book.yaml 字段无代码消费点：{missing}"


def test_phantom_field_flagged():
    class FakeConfig(BookConfig):
        phantom_field: str = "x"

    missing = check_config_consumption(FakeConfig.model_fields.keys(), PKG_DIR)
    assert "phantom_field" in missing  # 纸面功能直接报错（N1）


def test_repo_port_double_conformance():
    assert isinstance(InMemoryRepoPort(), RepoPort)  # runtime protocol check


def test_llm_provider_fake_conformance():
    fake = FakeLLMProvider(scripts={"review": {"issues": []}})
    assert isinstance(fake, LLMProvider)
    result = fake.complete_structured(tier="review", schema_name="review", system="s", user="u")
    assert isinstance(result, ProviderResult)
    assert result.data == {"issues": []}
    assert result.usage_in > 0
    assert len(fake.calls) == 1 and fake.calls[0].tier == "review"


def test_llm_provider_rejects_unknown_tier():
    fake = FakeLLMProvider(scripts={"x": {}})
    for tier in TIERS:
        assert tier in ("render", "review", "scribe", "small")
    import pytest

    with pytest.raises(ValueError):
        fake.complete_structured(tier="god", schema_name="x", system="s", user="u")
