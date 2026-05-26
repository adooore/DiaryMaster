"""飞书用户 open_id 与 DiaryMaster Session 的持久化绑定。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from backend.config import APP_ROOT
from backend.memory import ensure_memory_snapshot, refresh_memory_snapshot
from backend.session_store import Session, store

BINDINGS_PATH = APP_ROOT / "data" / "feishu" / "bindings.json"
_lock = threading.Lock()


def _ensure_dir() -> None:
    """确保 data/feishu 目录存在。"""
    BINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_bindings() -> dict[str, str]:
    """读取 open_id → session_id 映射；损坏或缺失时返回空 dict。"""
    if not BINDINGS_PATH.is_file():
        return {}
    try:
        data = json.loads(BINDINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {
            str(k): str(v)
            for k, v in data.items()
            if k and v
        }
    except (json.JSONDecodeError, OSError):
        return {}


def save_bindings(bindings: dict[str, str]) -> None:
    """覆盖写入 bindings.json。"""
    _ensure_dir()
    BINDINGS_PATH.write_text(
        json.dumps(bindings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def activate_session_for_open_id(open_id: str) -> Session:
    """
    按 open_id 解析 Session：已绑定则 switch_session；否则新建并写入绑定。

    会切换 Web 当前 active Session（与飞书对话共用 store，但不强制与 Web UI 同步）。
    """
    open_id = (open_id or "").strip()
    if not open_id:
        raise ValueError("open_id 为空")

    with _lock:
        bindings = load_bindings()
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
        save_bindings(bindings)
        refresh_memory_snapshot(session.id)
        return session
