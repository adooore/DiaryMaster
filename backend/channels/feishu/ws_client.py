"""飞书 WebSocket 长连接：无需公网 Webhook，由 SDK 主动连开放平台。"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from backend.channels.feishu.activity import record_ws_status
from backend.channels.feishu.config import get_feishu_config, is_enabled
from backend.channels.feishu.dispatch import dispatch_in_background

_log = logging.getLogger(__name__)

_ws_thread: threading.Thread | None = None
_ws_lock = threading.Lock()
_ws_status = "stopped"
_ws_detail = ""
_ws_started_at: float | None = None


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


def _on_p2_im_message_receive_v1(data: Any) -> None:
    """长连接收到 im.message.receive_v1；3 秒内返回，Agent 在后台线程执行。"""
    global _ws_status
    _ws_status = "connected"
    try:
        from backend.channels.feishu.activity import record_webhook_request

        payload = sdk_event_to_payload(data)
        record_webhook_request(payload)
        dispatch_in_background(payload)
    except Exception:
        _log.exception("飞书长连接事件入队失败")


def _run_ws_client() -> None:
    """在独立线程中启动 lark.ws.Client（阻塞直到异常退出）。"""
    global _ws_status, _ws_detail, _ws_started_at
    import lark_oapi as lark

    cfg = get_feishu_config()
    _ws_status = "connecting"
    _ws_detail = "正在连接飞书开放平台…"
    record_ws_status(_ws_status, _ws_detail)
    _log.info("飞书长连接：开始连接（App ID %s…）", cfg.app_id[:8])

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_p2_im_message_receive_v1)
        .build()
    )
    cli = lark.ws.Client(
        cfg.app_id,
        cfg.app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    try:
        _ws_started_at = time.time()

        def _mark_connected_later() -> None:
            global _ws_status, _ws_detail
            if _ws_status == "connecting" and _ws_thread and _ws_thread.is_alive():
                _ws_status = "connected"
                _ws_detail = "已连接飞书开放平台"
                record_ws_status(_ws_status, _ws_detail)

        threading.Timer(2.5, _mark_connected_later).start()
        cli.start()
    except Exception as e:
        _ws_status = "error"
        _ws_detail = str(e)
        record_ws_status(_ws_status, _ws_detail)
        _log.exception("飞书长连接异常退出")
    finally:
        if _ws_status != "error":
            _ws_status = "stopped"
            _ws_detail = "连接已结束"
        record_ws_status(_ws_status, _ws_detail)


def start_feishu_ws_client() -> bool:
    """
    若已配置飞书凭证则启动长连接后台线程。

    返回是否新启动了线程（已在运行则 False）。
    """
    global _ws_thread
    if not is_enabled():
        return False
    with _ws_lock:
        if _ws_thread and _ws_thread.is_alive():
            return False
        _ws_thread = threading.Thread(
            target=_run_ws_client,
            name="feishu-ws",
            daemon=True,
        )
        _ws_thread.start()
        return True


def get_ws_client_status() -> dict[str, Any]:
    """供 diagnostics 展示的长连接状态。"""
    alive = bool(_ws_thread and _ws_thread.is_alive())
    status = _ws_status
    if alive and status == "connecting" and _ws_started_at:
        if time.time() - _ws_started_at > 3:
            status = "connected"
    return {
        "enabled": is_enabled(),
        "thread_alive": alive,
        "status": status,
        "detail": _ws_detail,
        "started_at": _ws_started_at,
    }
