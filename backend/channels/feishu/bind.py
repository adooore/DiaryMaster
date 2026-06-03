"""飞书用户 open_id 与 Agent Session 的持久化绑定。"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.memory import ensure_memory_snapshot, refresh_memory_snapshot
from backend.session_store import Session, store

_lock = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bindings_path(agent_id: str | None = None) -> Path:
    """返回指定 Agent 的 bindings.json 路径。"""
    from backend.agents.context import get_active_agent_id
    from backend.agents.registry import agent_registry

    aid = (agent_id or "").strip() or get_active_agent_id()
    return agent_registry.feishu_dir(aid) / "bindings.json"


def _parse_binding_value(raw: Any) -> str | None:
    """从 string 或 {active_session_id} 对象解析 session_id。"""
    if isinstance(raw, str):
        sid = raw.strip()
        return sid or None
    if isinstance(raw, dict):
        sid = (raw.get("active_session_id") or "").strip()
        return sid or None
    return None


def _load_bindings_raw(agent_id: str | None = None) -> dict[str, Any]:
    """读取 bindings.json 原始结构。"""
    path = _bindings_path(agent_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def _save_bindings_raw(data: dict[str, Any], agent_id: str | None = None) -> None:
    """写入 bindings.json。"""
    path = _bindings_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_bindings(agent_id: str | None = None) -> dict[str, str]:
    """读取 open_id → session_id 映射（兼容旧 string 格式）。"""
    raw = _load_bindings_raw(agent_id)
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not key:
            continue
        sid = _parse_binding_value(value)
        if sid:
            out[str(key)] = sid
    return out


def get_active_session_id(open_id: str, agent_id: str | None = None) -> str | None:
    """读取飞书用户当前绑定的 session_id。"""
    open_id = (open_id or "").strip()
    if not open_id:
        return None
    return load_bindings(agent_id).get(open_id)


def set_active_session(
    open_id: str,
    session_id: str,
    agent_id: str | None = None,
) -> None:
    """切换飞书用户绑定 Session 并持久化。"""
    open_id = (open_id or "").strip()
    sid = (session_id or "").strip()
    if not open_id or not sid:
        raise ValueError("open_id 或 session_id 为空")
    store.get_session_by_id(sid)

    with _lock:
        raw = _load_bindings_raw(agent_id)
        raw[open_id] = {
            "active_session_id": sid,
            "updated_at": _now_iso(),
        }
        _save_bindings_raw(raw, agent_id)
        store.switch_session(sid)


def create_and_bind_session(open_id: str, agent_id: str | None = None) -> Session:
    """新建 Session 并设为该飞书用户的当前会话。"""
    open_id = (open_id or "").strip()
    if not open_id:
        raise ValueError("open_id 为空")

    with _lock:
        session = store.new_session()
        raw = _load_bindings_raw(agent_id)
        raw[open_id] = {
            "active_session_id": session.id,
            "updated_at": _now_iso(),
        }
        _save_bindings_raw(raw, agent_id)
        refresh_memory_snapshot(session.id)
        return session


def activate_session_for_open_id(open_id: str, agent_id: str | None = None) -> Session:
    """
    按 open_id 解析 Session：已绑定则 switch_session；否则新建并写入绑定。

    需在调用前 set_active_agent_id，以便 store 指向正确 Agent 的 Session 库。
    """
    open_id = (open_id or "").strip()
    if not open_id:
        raise ValueError("open_id 为空")

    with _lock:
        sid = get_active_session_id(open_id, agent_id)
        if sid:
            try:
                store.switch_session(sid)
                ensure_memory_snapshot(sid)
                return store.get_session()
            except ValueError:
                raw = _load_bindings_raw(agent_id)
                raw.pop(open_id, None)
                _save_bindings_raw(raw, agent_id)

        return create_and_bind_session(open_id, agent_id)
