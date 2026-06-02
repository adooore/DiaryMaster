"""飞书渠道活动记录（按 Agent：data/agents/{id}/feishu/activity.json）。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def _empty_state() -> dict[str, Any]:
    """返回空活动状态。"""
    return {
        "agent_id": "",
        "total_requests": 0,
        "last_at": None,
        "last_event_type": "",
        "last_schema": "",
        "last_message_preview": "",
        "last_dispatch_status": "",
        "last_dispatch_detail": "",
        "last_http_status": 0,
        "ws_status": "stopped",
        "ws_detail": "",
        "ws_updated_at": None,
    }


def _activity_path(agent_id: str) -> Path:
    """返回指定 Agent 的 activity.json 路径。"""
    from backend.agents.registry import agent_registry

    aid = (agent_id or "").strip()
    if not aid:
        raise ValueError("agent_id 为空")
    return agent_registry.feishu_dir(aid) / "activity.json"


def _load(agent_id: str) -> dict[str, Any]:
    """读取 Agent 的 activity.json。"""
    path = _activity_path(agent_id)
    if not path.is_file():
        state = _empty_state()
        state["agent_id"] = agent_id
        return state
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            merged = {**_empty_state(), **data}
            merged["agent_id"] = agent_id
            return merged
    except (json.JSONDecodeError, OSError):
        pass
    state = _empty_state()
    state["agent_id"] = agent_id
    return state


def _save(agent_id: str, data: dict[str, Any]) -> None:
    """写入 Agent 的 activity.json。"""
    path = _activity_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["agent_id"] = agent_id
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record_webhook_request(
    payload: dict[str, Any],
    *,
    agent_id: str,
    http_status: int = 200,
    is_challenge: bool = False,
) -> None:
    """记录一次 webhook / 长连接事件（不含 challenge 的计数增量）。"""
    aid = (agent_id or "").strip()
    if not aid:
        return
    header = payload.get("header") or {}
    event = payload.get("event") or {}
    event_type = (
        header.get("event_type")
        or (event.get("type") if isinstance(event, dict) else "")
        or payload.get("type")
        or ""
    )
    schema = str(payload.get("schema") or ("2.0" if header else "1.0"))
    preview = ""
    if isinstance(event, dict):
        message = event.get("message") or {}
        if isinstance(message, dict):
            preview = str(message.get("content") or "")[:120]

    with _lock:
        state = _load(aid)
        if not is_challenge:
            state["total_requests"] = int(state.get("total_requests") or 0) + 1
        state["last_at"] = time.time()
        state["last_event_type"] = str(event_type)
        state["last_schema"] = schema
        state["last_message_preview"] = preview
        state["last_http_status"] = http_status
        if is_challenge:
            state["last_dispatch_status"] = "challenge"
            state["last_dispatch_detail"] = "URL 校验"
        _save(aid, state)


def record_dispatch_result(agent_id: str, status: str, detail: str = "") -> None:
    """记录 dispatch 处理结果或跳过原因。"""
    aid = (agent_id or "").strip()
    if not aid:
        return
    with _lock:
        state = _load(aid)
        state["last_dispatch_status"] = status
        state["last_dispatch_detail"] = detail[:300]
        _save(aid, state)


def record_ws_status(agent_id: str, status: str, detail: str = "") -> None:
    """记录 WebSocket 长连接状态。"""
    aid = (agent_id or "").strip()
    if not aid:
        return
    with _lock:
        state = _load(aid)
        state["ws_status"] = status
        state["ws_detail"] = detail[:300]
        state["ws_updated_at"] = time.time()
        _save(aid, state)


def get_activity_status(agent_id: str | None = None) -> dict[str, Any]:
    """供 diagnostics 展示的活动摘要。"""
    aid = (agent_id or "").strip()
    if not aid:
        from backend.agents.context import get_active_agent_id

        aid = get_active_agent_id()
    state = _load(aid)
    last_at = state.get("last_at")
    age_sec: int | None = None
    if isinstance(last_at, (int, float)) and last_at > 0:
        age_sec = max(0, int(time.time() - float(last_at)))
    return {
        "agent_id": aid,
        "total_requests": int(state.get("total_requests") or 0),
        "last_at": last_at,
        "last_age_sec": age_sec,
        "last_event_type": state.get("last_event_type") or "",
        "last_schema": state.get("last_schema") or "",
        "last_message_preview": state.get("last_message_preview") or "",
        "last_dispatch_status": state.get("last_dispatch_status") or "",
        "last_dispatch_detail": state.get("last_dispatch_detail") or "",
        "ws_status": state.get("ws_status") or "stopped",
        "ws_detail": state.get("ws_detail") or "",
    }
