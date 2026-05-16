"""模型注册表：产品侧 curated 列表（非厂商 GET /models 透传）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

CONTEXT_1M = 1_048_576
MAX_OUTPUT_384K = 393_216


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    provider: str
    langchain_model: str
    api_key_env: str
    context_limit: int
    max_output_tokens: int
    supports_thinking: bool
    is_default: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "context_limit": self.context_limit,
            "max_output_tokens": self.max_output_tokens,
            "supports_thinking": self.supports_thinking,
            "is_default": self.is_default,
        }


MODELS: dict[str, ModelSpec] = {
    "deepseek-v4-flash": ModelSpec(
        id="deepseek-v4-flash",
        label="V4 Flash",
        provider="deepseek",
        langchain_model="deepseek:deepseek-v4-flash",
        api_key_env="DEEPSEEK_API_KEY",
        context_limit=CONTEXT_1M,
        max_output_tokens=MAX_OUTPUT_384K,
        supports_thinking=True,
        is_default=True,
    ),
    "deepseek-v4-pro": ModelSpec(
        id="deepseek-v4-pro",
        label="V4 Pro",
        provider="deepseek",
        langchain_model="deepseek:deepseek-v4-pro",
        api_key_env="DEEPSEEK_API_KEY",
        context_limit=CONTEXT_1M,
        max_output_tokens=MAX_OUTPUT_384K,
        supports_thinking=True,
        is_default=False,
    ),
}


def list_models() -> list[dict[str, Any]]:
    return [m.to_public_dict() for m in MODELS.values()]


def default_model_id() -> str:
    for m in MODELS.values():
        if m.is_default:
            return m.id
    return next(iter(MODELS))


def get_model(model_id: str) -> ModelSpec:
    if model_id not in MODELS:
        raise ValueError(f"未知模型: {model_id}")
    return MODELS[model_id]


def validate_model_id(model_id: str | None) -> str:
    mid = (model_id or "").strip() or default_model_id()
    get_model(mid)
    return mid


def resolve_api_key(spec: ModelSpec) -> str:
    from backend.config import get_api_key

    if spec.api_key_env == "DEEPSEEK_API_KEY":
        key = get_api_key()
        if not key:
            raise RuntimeError("未设置 DEEPSEEK_API_KEY")
        return key
    key = os.environ.get(spec.api_key_env, "").strip()
    if not key:
        raise RuntimeError(f"未设置环境变量 {spec.api_key_env}")
    return key
