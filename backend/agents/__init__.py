"""Agent 注册表、工作区解析与会话 scoped 管理。"""

from backend.agents.context import get_active_agent_id, set_active_agent_id
from backend.agents.registry import (
    agent_registry,
    bootstrap_agents,
    get_agent_profile,
    list_agent_summaries,
)
from backend.agents.workspace import get_workspace_root

__all__ = [
    "agent_registry",
    "bootstrap_agents",
    "get_active_agent_id",
    "get_agent_profile",
    "get_workspace_root",
    "list_agent_summaries",
    "set_active_agent_id",
]
