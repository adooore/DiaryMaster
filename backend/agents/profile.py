"""AgentProfile 数据模型与序列化。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
DEFAULT_AGENT_ID = "default"


@dataclass
class AgentProfile:
    """单个 Agent（租户/角色实例）的配置与元数据。"""

    agent_id: str
    display_name: str
    description: str = ""
    role_prompt: str = ""
    created_at: str = ""
    updated_at: str = ""
    enabled: bool = True
    model_id: str | None = None
    thinking_enabled: bool | None = None
    api_key: str | None = None
    api_provider: str | None = "deepseek"
    workspace_mode: str = "dedicated"  # dedicated | shared
    workspace_path: str | None = None
    shared_workspace_ref: str | None = None  # legacy | 其他 agent_id
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    icon: str | None = None
    sort_order: int = 0

    def to_dict(self, *, include_secrets: bool = False) -> dict[str, Any]:
        """转为 JSON 可序列化 dict；默认不含 api_key 明文。"""
        data = asdict(self)
        if not include_secrets:
            data.pop("api_key", None)
            data.pop("feishu_app_secret", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentProfile:
        """从 registry / meta.json 反序列化。"""
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def now_iso() -> str:
    """当前 UTC ISO 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


def validate_agent_id(agent_id: str) -> str:
    """校验 agent_id 格式；非法则抛 ValueError。"""
    aid = (agent_id or "").strip().lower()
    if not aid or not _AGENT_ID_RE.match(aid):
        raise ValueError(
            "agent_id 须以小写字母开头，仅含小写字母、数字、下划线或连字符，最长 32 字符"
        )
    return aid


def slug_from_display_name(name: str) -> str:
    """从显示名生成建议 agent_id（不保证唯一）。"""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    if not base or not base[0].isalpha():
        base = f"agent-{base or 'new'}"
    return base[:32]
