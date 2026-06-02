"""Session 级记忆快照：按 (agent_id, session_id) 冻结。"""

from __future__ import annotations

from backend.memory.prompt import build_memory_snapshot, build_system_prompt
from backend.session_store import store

_snapshots: dict[tuple[str, str], str] = {}


def _snapshot_key(session_id: str | None = None) -> tuple[str, str]:
    """当前 agent + session 的快照键。"""
    from backend.agents.context import get_active_agent_id

    sid = session_id or store.get_session().id
    return get_active_agent_id(), sid


def refresh(session_id: str) -> str:
    """从磁盘读取记忆并冻结到该 Session（new_session / 首次激活时调用）。"""
    snapshot = build_memory_snapshot()
    _snapshots[_snapshot_key(session_id)] = snapshot
    return snapshot


def ensure(session_id: str) -> str:
    """返回该 Session 已冻结的快照；未缓存时从磁盘加载并冻结。"""
    key = _snapshot_key(session_id)
    if key not in _snapshots:
        return refresh(session_id)
    return _snapshots[key]


def get(session_id: str | None = None) -> str:
    """读取当前或指定 Session 的记忆快照字符串。"""
    sid = session_id or store.get_session().id
    return ensure(sid)


def drop(session_id: str) -> None:
    """删除 Session 时丢弃其快照缓存。"""
    from backend.agents.context import get_active_agent_id

    aid = get_active_agent_id()
    _snapshots.pop((aid, session_id), None)


def effective_system_prompt(base: str, session_id: str | None = None) -> str:
    """基础规则 + 该 Session 冻结记忆块，作为送入模型的 system prompt。"""
    snapshot = get(session_id)
    return build_system_prompt(base, snapshot or None)
