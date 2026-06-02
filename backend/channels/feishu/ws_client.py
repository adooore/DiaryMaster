"""飞书 WebSocket 长连接：每个已配置 Agent 各起一个 WS 线程。"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from backend.channels.feishu.activity import record_ws_status
from backend.channels.feishu.config import get_feishu_config, list_feishu_enabled_agent_ids
from backend.channels.feishu.dispatch import dispatch_in_background

_log = logging.getLogger(__name__)

_ws_lock = threading.Lock()
_ws_threads: dict[str, threading.Thread] = {}
_ws_status_by_agent: dict[str, dict[str, Any]] = {}
_monitor_started = False
_monitor_lock = threading.Lock()
_MONITOR_INTERVAL_SEC = 20.0


def sdk_event_to_payload(data: Any) -> dict[str, Any]:
    """将 lark-oapi P2 事件对象转为 dispatch 可消费的 payload dict。"""
    import lark_oapi as lark

    raw = lark.JSON.marshal(data)
    parsed: Any = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, dict):
        return {
            "schema": "2.0",
            "header": {"event_type": "im.message.receive_v1"},
            "event": {},
        }
    if parsed.get("header") and parsed.get("event"):
        return parsed
    if isinstance(parsed.get("event"), dict):
        return {
            "schema": "2.0",
            "header": {"event_type": "im.message.receive_v1"},
            "event": parsed["event"],
        }
    if parsed.get("message") or parsed.get("sender"):
        return {
            "schema": "2.0",
            "header": {"event_type": "im.message.receive_v1"},
            "event": parsed,
        }
    return parsed


def _set_agent_ws_status(agent_id: str, status: str, detail: str) -> None:
    """更新单个 Agent 的长连接状态并写入 activity。"""
    started_at = _ws_status_by_agent.get(agent_id, {}).get("started_at")
    if status == "connecting":
        started_at = time.time()
    _ws_status_by_agent[agent_id] = {
        "agent_id": agent_id,
        "status": status,
        "detail": detail,
        "started_at": started_at,
    }
    record_ws_status(agent_id, status, detail)


def _make_message_handler(agent_id: str):
    """为指定 Agent 创建 im.message.receive_v1 回调。"""

    def _on_p2_im_message_receive_v1(data: Any) -> None:
        """长连接收到 im.message.receive_v1；3 秒内返回，Agent 在后台线程执行。"""
        _set_agent_ws_status(agent_id, "connected", "已连接飞书开放平台")
        try:
            from backend.channels.feishu.activity import record_webhook_request

            payload = sdk_event_to_payload(data)
            header = payload.get("header") or {}
            if not header.get("app_id"):
                cfg = get_feishu_config(agent_id)
                if cfg.app_id:
                    header = dict(header)
                    header["app_id"] = cfg.app_id
                    payload["header"] = header
            record_webhook_request(payload, agent_id=agent_id)
            dispatch_in_background(payload, agent_id=agent_id)
        except Exception:
            _log.exception("飞书长连接事件入队失败（agent=%s）", agent_id)

    return _on_p2_im_message_receive_v1


def _run_ws_client(agent_id: str) -> None:
    """在独立线程中启动 lark.ws.Client（阻塞直到异常退出）。"""
    import lark_oapi as lark

    cfg = get_feishu_config(agent_id)
    if not cfg.app_id or not cfg.app_secret:
        _set_agent_ws_status(agent_id, "stopped", "飞书凭证未配置")
        return

    _set_agent_ws_status(agent_id, "connecting", "正在连接飞书开放平台…")
    _log.info(
        "飞书长连接 [%s]：开始连接（App ID %s…）",
        agent_id,
        cfg.app_id[:8],
    )

    handler = _make_message_handler(agent_id)
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handler)
        .build()
    )
    cli = lark.ws.Client(
        cfg.app_id,
        cfg.app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    try:

        def _mark_connected_later() -> None:
            thread = _ws_threads.get(agent_id)
            info = _ws_status_by_agent.get(agent_id) or {}
            if info.get("status") == "connecting" and thread and thread.is_alive():
                _set_agent_ws_status(agent_id, "connected", "已连接飞书开放平台")

        threading.Timer(2.5, _mark_connected_later).start()
        cli.start()
    except Exception as e:
        _set_agent_ws_status(agent_id, "error", str(e))
        _log.exception("飞书长连接 [%s] 异常退出", agent_id)
    finally:
        info = _ws_status_by_agent.get(agent_id) or {}
        if info.get("status") != "error":
            _set_agent_ws_status(agent_id, "stopped", "连接已结束")


def _start_ws_for_agent(agent_id: str, *, force: bool = False) -> bool:
    """若该 Agent 尚未连接则启动 WS 线程；force 时丢弃旧线程引用并强制再起。"""
    aid = (agent_id or "").strip()
    if not aid:
        return False
    cfg = get_feishu_config(aid)
    if not cfg.app_id or not cfg.app_secret:
        return False
    with _ws_lock:
        thread = _ws_threads.get(aid)
        if thread and thread.is_alive() and not force:
            return False
        if force or (thread and not thread.is_alive()):
            _ws_threads.pop(aid, None)
        thread = threading.Thread(
            target=_run_ws_client,
            args=(aid,),
            name=f"feishu-ws-{aid}",
            daemon=True,
        )
        _ws_threads[aid] = thread
        thread.start()
        return True


def reconcile_ws_clients() -> int:
    """确保已配置飞书的 Agent 均有存活 WS；清理已禁用 Agent 的状态。返回新启动数。"""
    enabled = set(list_feishu_enabled_agent_ids())
    with _ws_lock:
        for aid in list(_ws_threads.keys()):
            thread = _ws_threads.get(aid)
            if aid not in enabled:
                _ws_threads.pop(aid, None)
                _ws_status_by_agent.pop(aid, None)
            elif thread and not thread.is_alive():
                _ws_threads.pop(aid, None)
    started = 0
    for aid in enabled:
        if _start_ws_for_agent(aid):
            started += 1
    return started


def _ws_monitor_loop() -> None:
    """后台定期补启已断开的长连接（uvicorn reload 或线程异常退出后）。"""
    while True:
        time.sleep(_MONITOR_INTERVAL_SEC)
        try:
            n = reconcile_ws_clients()
            if n:
                _log.info("飞书 WS 健康检查：已补启 %d 个 Agent 长连接", n)
        except Exception:
            _log.exception("飞书 WS 健康检查失败")


def _ensure_ws_monitor() -> None:
    """启动全局 WS 健康检查线程（仅一次）。"""
    global _monitor_started
    with _monitor_lock:
        if _monitor_started:
            return
        _monitor_started = True
        threading.Thread(
            target=_ws_monitor_loop,
            name="feishu-ws-monitor",
            daemon=True,
        ).start()


def start_feishu_ws_client() -> bool:
    """
    为全部已配置飞书凭证的 Agent 启动长连接，并开启健康检查。

    返回是否新启动了至少一个线程。
    """
    _ensure_ws_monitor()
    started = restart_feishu_ws_clients()
    return started > 0


def restart_feishu_ws_clients(*, force: bool = False) -> int:
    """重启已启用 Agent 的 WS 连接；force 时强制丢弃旧线程引用后重连。返回新启动线程数。"""
    enabled = set(list_feishu_enabled_agent_ids())
    if force:
        with _ws_lock:
            for aid in list(_ws_threads.keys()):
                if aid in enabled:
                    _ws_threads.pop(aid, None)
                    _set_agent_ws_status(aid, "connecting", "正在重启长连接…")
                else:
                    _ws_threads.pop(aid, None)
                    _ws_status_by_agent.pop(aid, None)
    started = reconcile_ws_clients()
    if force and started == 0 and enabled:
        for aid in enabled:
            if _start_ws_for_agent(aid, force=True):
                started += 1
    return started


def get_ws_client_status() -> dict[str, Any]:
    """供 diagnostics 展示的长连接状态（含各 Agent）。"""
    agents: list[dict[str, Any]] = []
    enabled = list_feishu_enabled_agent_ids()
    any_alive = False
    for aid in enabled:
        thread = _ws_threads.get(aid)
        alive = bool(thread and thread.is_alive())
        any_alive = any_alive or alive
        info = dict(_ws_status_by_agent.get(aid) or {})
        status = info.get("status") or ("connected" if alive else "stopped")
        if alive and status == "connecting" and info.get("started_at"):
            if time.time() - float(info["started_at"]) > 3:
                status = "connected"
        agents.append(
            {
                "agent_id": aid,
                "thread_alive": alive,
                "status": status,
                "detail": info.get("detail") or "",
                "started_at": info.get("started_at"),
            }
        )
    overall = "connected" if any_alive else ("stopped" if not enabled else "connecting")
    return {
        "enabled": bool(enabled),
        "thread_alive": any_alive,
        "status": overall,
        "detail": f"{len(enabled)} 个 Agent 已配置飞书",
        "agents": agents,
    }
