"""Session 级记忆快照：启动/切换时冻结，本会话内不随 memory 工具写盘而更新。"""

from __future__ import annotations

from backend.memory.prompt import build_memory_snapshot, build_system_prompt
from backend.session_store import store

_snapshots: dict[str, str] = {}


def refresh(session_id: str) -> str:
    """从磁盘读取记忆并冻结到该 Session（new_session / 首次激活时调用）。"""
    snapshot = build_memory_snapshot()
    _snapshots[session_id] = snapshot
    return snapshot


def ensure(session_id: str) -> str:
    """返回该 Session 已冻结的快照；未缓存时从磁盘加载并冻结。"""
    if session_id not in _snapshots:
        return refresh(session_id)
    return _snapshots[session_id]


def get(session_id: str | None = None) -> str:
    """读取当前或指定 Session 的记忆快照字符串。"""
    sid = session_id or store.get_session().id
    return ensure(sid)


def drop(session_id: str) -> None:
    """删除 Session 时丢弃其快照缓存。"""
    _snapshots.pop(session_id, None)


def effective_system_prompt(base: str, session_id: str | None = None) -> str:
    """基础规则 + 该 Session 冻结记忆块，作为送入模型的 system prompt。"""
    snapshot = get(session_id)
    return build_system_prompt(base, snapshot or None)
