"""飞书用户 open_id 与 Agent Session 的持久化绑定。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from backend.memory import ensure_memory_snapshot, refresh_memory_snapshot
from backend.session_store import Session, store

_lock = threading.Lock()


def _bindings_path(agent_id: str | None = None) -> Path:
    """返回指定 Agent 的 bindings.json 路径。"""
    from backend.agents.context import get_active_agent_id
    from backend.agents.registry import agent_registry

    aid = (agent_id or "").strip() or get_active_agent_id()
    return agent_registry.feishu_dir(aid) / "bindings.json"


def load_bindings(agent_id: str | None = None) -> dict[str, str]:
    """读取 open_id → session_id 映射；损坏或缺失时返回空 dict。"""
    path = _bindings_path(agent_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {
            str(k): str(v)
            for k, v in data.items()
            if k and v
        }
    except (json.JSONDecodeError, OSError):
        return {}


def save_bindings(bindings: dict[str, str], agent_id: str | None = None) -> None:
    """覆盖写入指定 Agent 的 bindings.json。"""
    path = _bindings_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bindings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def activate_session_for_open_id(open_id: str, agent_id: str | None = None) -> Session:
    """
    按 open_id 解析 Session：已绑定则 switch_session；否则新建并写入绑定。

    需在调用前 set_active_agent_id，以便 store 指向正确 Agent 的 Session 库。
    """
    open_id = (open_id or "").strip()
    if not open_id:
        raise ValueError("open_id 为空")

    with _lock:
        bindings = load_bindings(agent_id)
        sid = bindings.get(open_id)
        if sid:
            try:
                store.switch_session(sid)
                ensure_memory_snapshot(sid)
                return store.get_session()
            except ValueError:
                bindings.pop(open_id, None)

        session = store.new_session()
        bindings[open_id] = session.id
        save_bindings(bindings, agent_id)
        refresh_memory_snapshot(session.id)
        return session
