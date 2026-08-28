"""HTTPProvider：LLMProvider 的真实实现（ADR-0002 降级链 + 双线格式 + cassette）。

- 传输层可注入（transport 可调用），测试/cassette 回放不依赖真实 Key（N4）。
- openai 线：POST {base}/chat/completions；anthropic 线：POST {base}/messages。
- 语义：单端点 JSON 解析失败重试 1 次（第二次强制 json_object）；网络/HTTP
  错误直接降级下一端点；全链耗尽 → ProviderError（fail-closed）。
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from loom.core.config import Endpoint
from loom.core.seam import SEAM_VERSION  # noqa: F401
from loom.edge.client.protocol import ProviderResult

Transport = Callable[[Endpoint, dict, int], tuple[str, int, int]]


class ProviderError(RuntimeError):
    """降级链全部耗尽。"""


class JsonParseError(ValueError):
    """响应不是合法 JSON 结构化输出。"""


def _default_transport(ep: Endpoint, payload: dict, timeout: int) -> tuple[str, int, int]:
    base = ep.base_url.rstrip("/")
    if ep.wire == "anthropic":
        url = base if base.endswith("/messages") else base + "/messages"
    else:
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if ep.wire == "anthropic":
        headers["x-api-key"] = ep.api_key
        headers["anthropic-version"] = "2023-06-01"
        headers["Authorization"] = f"Bearer {ep.api_key}"
    else:
        headers["Authorization"] = f"Bearer {ep.api_key}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProviderError(f"{ep.name} HTTP {e.code}: {e.read()[:200]!r}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(f"{ep.name} 网络错误：{e}") from e
    if ep.wire == "anthropic":
        text = "".join(c.get("text", "") for c in body.get("content", []))
        usage = body.get("usage", {})
        return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    text = body["choices"][0]["message"]["content"]
    usage = body.get("usage", {})
    return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json(text: str) -> dict:
    """容错解析结构化输出：剥代码围栏、取首个平衡 JSON 对象。"""
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    if start < 0:
        raise JsonParseError(f"响应无 JSON 对象：{text[:80]!r}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError as e:
                    raise JsonParseError(f"JSON 解析失败：{e}（{text[start:start+60]!r}…）") from e
    raise JsonParseError("JSON 对象未闭合")


class HTTPProvider:
    """LLMProvider 真实实现。transport 可注入；cassette 见 CassetteTransport。"""

    def __init__(
        self,
        chain: list[Endpoint],
        *,
        transport: Transport | None = None,
        timeout: int = 300,
    ) -> None:
        if not chain:
            raise ProviderError("模型降级链为空：检查 .env（LOOM_*_API_KEY）")
        self.chain = list(chain)
        self._transport = transport or _default_transport
        self.timeout = timeout

    def complete_structured(
        self, *, tier: str, schema_name: str, system: str, user: str
    ) -> ProviderResult:
        errors: list[str] = []
        for ep in self.chain:
            for force_json in (False, True):
                payload = _payload(ep, system, user, force_json=force_json)
                payload_key = f"{ep.model_id}|{schema_name}|{hashlib.sha256((system + user).encode()).hexdigest()[:16]}"
                try:
                    text, u_in, u_out = self._transport(ep, payload, self.timeout)
                    data = parse_json(text)
                    return ProviderResult(
                        data=data, model=ep.model_id, usage_in=u_in, usage_out=u_out, tier=tier
                    )
                except JsonParseError as e:
                    errors.append(f"{payload_key}: {e}")
                    continue  # 同端点重试一次（force_json）
                except ProviderError as e:
                    errors.append(str(e))
                    break  # 降级下一端点
        raise ProviderError("降级链全部耗尽：\n  " + "\n  ".join(errors))


    def complete_text(
        self, *, tier: str, schema_name: str, system: str, user: str
    ) -> ProviderResult:
        """自然语言直出通道（渲染正文不走 JSON 解析，§5.4 结构化输出用紧凑 JSON 除外）。"""
        errors: list[str] = []
        for ep in self.chain:
            try:
                text, u_in, u_out = self._transport(
                    ep, _payload(ep, system, user, force_json=False), self.timeout
                )
                return ProviderResult(data={"text": text}, model=ep.model_id,
                                      usage_in=u_in, usage_out=u_out, tier=tier)
            except ProviderError as e:
                errors.append(str(e))
        raise ProviderError("降级链全部耗尽：\n  " + "\n  ".join(errors))


def _payload(ep: Endpoint, system: str, user: str, *, force_json: bool) -> dict:
    if ep.wire == "anthropic":
        return {"model": ep.model_id, "system": system, "max_tokens": 8000,
                "messages": [{"role": "user", "content": user}]}
    payload: dict = {
        "model": ep.model_id,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if force_json:
        payload["response_format"] = {"type": "json_object"}
    return payload


# ---- cassette 录制回放（N4：edge 测试无 Key 可跑 CI）----

class Cassette:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict[str, dict] = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def key(self, ep: Endpoint, content: str) -> str:
        raw = f"{ep.wire}|{ep.model_id}|{content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")


def cassette_transport(cassette: Cassette, real: Transport | None = None) -> Transport:
    """录制（有 real）或回放（无 real）模式的传输层。回放 miss 即报错。"""
    def _transport(ep: Endpoint, payload: dict, timeout: int) -> tuple[str, int, int]:
        key = cassette.key(ep, f"{ep.model_id}|{json.dumps(payload, ensure_ascii=False, sort_keys=True)}")
        if key in cassette.data:
            hit = cassette.data[key]
            return hit["text"], hit.get("u_in", 0), hit.get("u_out", 0)
        if real is None:
            raise ProviderError(f"cassette 未命中且无真实传输：{key}")
        # 真实调用需要原始 system/user —— 由 _record_payload 约定带回
        text, u_in, u_out = real(ep, payload, timeout)
        cassette.data[key] = {"text": text, "u_in": u_in, "u_out": u_out}
        return text, u_in, u_out
    return _transport
