"""edge 客户端测试：降级链装配、双线格式、cassette、容错 JSON。"""
from __future__ import annotations

import json

import pytest

from loom.core.config import build_chain, load_env
from loom.edge.client.http import (
    HTTPProvider,
    JsonParseError,
    ProviderError,
    Cassette,
    cassette_transport,
    parse_json,
)


def _env(tmp_path, **overrides):
    lines = {
        "LOOM_OCGO_API_KEY": "k1",
        "LOOM_OCGO_BASE_URL": "https://x/v1/chat/completions",
        "LOOM_OCGO_MODEL_ID": "glm-5.3-flash",
        "LOOM_OCGO_MODEL_ID2": "deepseek-v4-flash",
        "LOOM_OCGO_ALI_BASE_URL": "https://x/v1/messages",
        "LOOM_OCGO_ALI_MODEL_ID": "qwen3.8-flash",
        "LOOM_ALI_BASE_URL": "https://ali/compatible-mode/v1",
        "LOOM_ALI_API_KEY": "k2",
        "LOOM_ALI_MODEL_ID": "qwen3.8-flash",
        "LOOM_LLM_API_KEY": "k3",
        "LOOM_LLM_BASE_URL": "https://glm/v4",
        "LOOM_LLM_MODEL": "glm-5.3-flash",
        **overrides,
    }
    p = tmp_path / ".env"
    p.write_text("\n".join(f"{k}={v}" for k, v in lines.items()), encoding="utf-8")
    return load_env(p)


def test_build_chain_full_order(tmp_path):
    chain = build_chain(_env(tmp_path))
    assert [ep.name for ep in chain] == ["ocgo", "ocgo", "ocgo-ali", "ali", "glm"]
    assert [ep.model_id for ep in chain] == [
        "glm-5.3-flash", "deepseek-v4-flash", "qwen3.8-flash", "qwen3.8-flash", "glm-5.3-flash"]
    assert [ep.wire for ep in chain] == ["openai", "openai", "anthropic", "openai", "openai"]


def test_build_chain_partial(tmp_path):
    chain = build_chain(_env(tmp_path, **{"LOOM_OCGO_API_KEY": ""}))
    assert [ep.name for ep in chain] == ["ali", "glm"]
    assert build_chain({}) == []


def test_load_env_comments_and_quotes(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# 注释\nA="带引号"\n\nB = 空格值 \n', encoding="utf-8")
    env = load_env(p)
    assert env["A"] == "带引号" and env["B"] == "空格值"


def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('好的，以下是结果：{"a": {"b": 2}} 谢谢') == {"a": {"b": 2}}
    with pytest.raises(JsonParseError):
        parse_json("没有对象")
    with pytest.raises(JsonParseError):
        parse_json('{"a": ')


def _fake_transport(responses):  # 按 endpoint.name+model 顺序出队
    calls = []

    def transport(ep, payload, timeout):
        calls.append((ep.name, ep.model_id, payload))
        action = responses.pop(0)
        if isinstance(action, Exception):
            raise action
        return action
    return transport, calls


def test_http_provider_success_and_payload_shape(tmp_path):
    env = _env(tmp_path)
    transport, calls = _fake_transport([(json.dumps({"x": 1}), 100, 20)])
    provider = HTTPProvider(build_chain(env), transport=transport)
    result = provider.complete_structured(tier="review", schema_name="r", system="s", user="u")
    assert result.data == {"x": 1} and result.model == "glm-5.3-flash" and result.usage_in == 100
    ep, payload = calls[0][0], calls[0][2]
    assert payload["messages"][0]["role"] == "system"


def test_http_provider_fallback_chain(tmp_path):
    env = _env(tmp_path)
    transport, calls = _fake_transport([
        ProviderError("ocgo down"),
        ProviderError("ocgo down"),
        ProviderError("ocgo down"),
        (json.dumps({"from": "ali"}), 1, 1),
    ])
    provider = HTTPProvider(build_chain(env), transport=transport)
    result = provider.complete_structured(tier="small", schema_name="s", system="", user="u")
    assert result.data == {"from": "ali"} and result.model == "qwen3.8-flash"
    assert len(calls) == 4  # 三次降级后命中 ali


def test_http_provider_json_retry_then_next(tmp_path):
    env = _env(tmp_path)
    transport, _calls = _fake_transport([
        ("不是json", 1, 1),  # 第一次：解析失败
        ('```json\n{"ok": true}\n```', 1, 1),  # 同端点强制 json 重试成功
    ])
    provider = HTTPProvider(build_chain(env), transport=transport)
    assert provider.complete_structured(tier="small", schema_name="s", system="", user="u").data == {"ok": True}


def test_http_provider_exhausted_fails_closed(tmp_path):
    env = _env(tmp_path)
    transport, _ = _fake_transport([ProviderError("down")] * 10)
    provider = HTTPProvider(build_chain(env), transport=transport)
    with pytest.raises(ProviderError, match="降级链全部耗尽"):
        provider.complete_structured(tier="small", schema_name="s", system="", user="u")


def test_http_provider_empty_chain_fails(tmp_path):
    with pytest.raises(ProviderError, match="降级链为空"):
        HTTPProvider([])


def test_anthropic_wire_payload(tmp_path):
    env = _env(tmp_path)
    transport, calls = _fake_transport([
        ProviderError("1 down"), ProviderError("2 down"), ProviderError("3 down"),
        (json.dumps({"q": 1}), 1, 1),
    ])
    HTTPProvider(build_chain(env), transport=transport).complete_structured(
        tier="small", schema_name="s", system="sys", user="usr")
    third = calls[2]  # ocgo-ali（anthropic 线）
    assert third[2]["system"] == "sys" and third[2]["messages"][0]["content"] == "usr"
    assert "response_format" not in third[2]


def test_cassette_record_and_replay(tmp_path):
    env = _env(tmp_path, **{"LOOM_OCGO_MODEL_ID2": "", "LOOM_OCGO_ALI_BASE_URL": "",
                            "LOOM_ALI_API_KEY": "", "LOOM_LLM_API_KEY": ""})
    chain = build_chain(env)
    real, _ = _fake_transport([(json.dumps({"n": 42}), 7, 3)])
    cas = Cassette(tmp_path / "cas.json")

    provider = HTTPProvider(chain, transport=cassette_transport(cas, real=real))
    r1 = provider.complete_structured(tier="small", schema_name="s", system="sys", user="usr")
    assert r1.data == {"n": 42} and r1.usage_in == 7
    cas.save()

    # 回放：无真实传输也能命中
    cas2 = Cassette(tmp_path / "cas.json")
    provider2 = HTTPProvider(chain, transport=cassette_transport(cas2))
    r2 = provider2.complete_structured(tier="small", schema_name="s", system="sys", user="usr")
    assert r2.data == {"n": 42} and r2.usage_in == 7

    # miss 且无 real → fail-closed
    with pytest.raises(ProviderError):
        provider2.complete_structured(tier="small", schema_name="s", system="sys", user="别的提问")
