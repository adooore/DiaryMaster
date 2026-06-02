"""当前请求 / 线程的 active Agent 上下文。"""

from __future__ import annotations

from contextvars import ContextVar

_active_agent_id: ContextVar[str] = ContextVar("active_agent_id", default="")


def get_active_agent_id() -> str:
    """返回当前上下文中的 agent_id；未设置时由 registry 解析。"""
    aid = (_active_agent_id.get() or "").strip()
    if aid:
        return aid
    from backend.agents.registry import agent_registry

    return agent_registry.active_agent_id


def set_active_agent_id(agent_id: str) -> None:
    """设置当前上下文 active agent（Web 请求、飞书 dispatch 等）。"""
    _active_agent_id.set((agent_id or "").strip())
