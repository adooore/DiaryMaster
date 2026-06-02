"""按 Agent 缓存 SessionStore 实例。"""

from __future__ import annotations

import threading

from backend.session_store import SessionStore

_stores: dict[str, SessionStore] = {}
_lock = threading.RLock()


def get_session_store(agent_id: str | None = None) -> SessionStore:
    """返回指定 Agent 的 SessionStore（懒加载）。"""
    from backend.agents.context import get_active_agent_id
    from backend.agents.registry import agent_registry

    aid = (agent_id or "").strip() or get_active_agent_id()
    with _lock:
        if aid not in _stores:
            _stores[aid] = SessionStore(
                sessions_dir=agent_registry.sessions_dir(aid),
                active_id_file=agent_registry.active_session_file(aid),
            )
        return _stores[aid]


def invalidate_session_store(agent_id: str) -> None:
    """切换或删除 Agent 后丢弃缓存的 SessionStore。"""
    with _lock:
        _stores.pop(agent_id, None)
