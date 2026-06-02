"""飞书机器人配置：凭证仅存于 Agent Profile，环境变量可覆盖 default Agent。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from backend.agents.profile import DEFAULT_AGENT_ID

_ENV_APP_ID = "FEISHU_APP_ID"
_ENV_APP_SECRET = "FEISHU_APP_SECRET"


@dataclass(frozen=True)
class FeishuConfig:
    """飞书应用凭证（App ID + App Secret 即可启用）。"""

    app_id: str
    app_secret: str
    agent_id: str = DEFAULT_AGENT_ID


def get_feishu_config(agent_id: str | None = None) -> FeishuConfig:
    """读取指定 Agent 的飞书凭证；default 在未配置时可读环境变量。"""
    from backend.agents.context import get_active_agent_id
    from backend.agents.registry import agent_registry

    aid = (agent_id or "").strip() or get_active_agent_id()
    profile = agent_registry.get_profile(aid)
    app_id = (profile.feishu_app_id or "").strip()
    app_secret = (profile.feishu_app_secret or "").strip()

    if aid == DEFAULT_AGENT_ID:
        if not app_id:
            app_id = os.environ.get(_ENV_APP_ID, "").strip()
        if not app_secret:
            app_secret = os.environ.get(_ENV_APP_SECRET, "").strip()

    return FeishuConfig(app_id=app_id, app_secret=app_secret, agent_id=aid)


def is_enabled(agent_id: str | None = None) -> bool:
    """指定 Agent 的飞书凭证是否齐全。"""
    cfg = get_feishu_config(agent_id)
    return bool(cfg.app_id and cfg.app_secret)


def list_feishu_enabled_agent_ids() -> list[str]:
    """返回已配置飞书凭证的全部 agent_id。"""
    from backend.agents.registry import agent_registry

    return [
        p.agent_id
        for p in agent_registry.list_profiles()
        if is_enabled(p.agent_id)
    ]
