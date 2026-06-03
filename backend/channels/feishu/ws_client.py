"""飞书 WebSocket 长连接：单管理线程 + 单 event loop 承载全部 Agent 连接。"""

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
_ws_clients: dict[str, Any] = {}
_connecting: set[str] = set()
_ws_status_by_agent: dict[str, dict[str, Any]] = {}
_manager_thread: threading.Thread | None = None
_manager_loop: Any = None
_manager_ready = threading.Event()
_manager_lock = threading.Lock()
_MONITOR_INTERVAL_SEC = 20.0


def sdk_event_to_payload(data: Any) -> dict[str, Any]:
    """将 lark-oapi P2 事件对象转为 dispatch 可消费的 payload dict。"""
    from lark_oapi.core.json import JSON

    raw = JSON.marshal(data)
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


def _build_ws_client(agent_id: str):
    """创建 lark.ws.Client（仅能在 WS 管理线程中调用）。"""
    import lark_oapi as lark

    cfg = get_feishu_config(agent_id)
    handler = _make_message_handler(agent_id)
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handler)
        .build()
    )
    return lark.ws.Client(
        cfg.app_id,
        cfg.app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )


def _agent_ws_alive(agent_id: str) -> bool:
    with _ws_lock:
        cli = _ws_clients.get(agent_id)
    return bool(cli is not None and cli._conn is not None)


async def _connect_agent(agent_id: str) -> bool:
    """在管理 loop 上连接单个 Agent；已连接时返回 False。"""
    aid = (agent_id or "").strip()
    if not aid:
        return False

    with _ws_lock:
        cli = _ws_clients.get(aid)
        if aid in _connecting or (cli is not None and cli._conn is not None):
            return False
        _connecting.add(aid)

    cfg = get_feishu_config(aid)
    if not cfg.app_id or not cfg.app_secret:
        with _ws_lock:
            _connecting.discard(aid)
        _set_agent_ws_status(aid, "stopped", "飞书凭证未配置")
        return False

    _set_agent_ws_status(aid, "connecting", "正在连接飞书开放平台…")
    _log.info(
        "飞书长连接 [%s]：开始连接（App ID %s…）",
        aid,
        cfg.app_id[:8],
    )

    import lark_oapi.ws.client as lark_ws_module

    cli = _build_ws_client(aid)
    try:
        await cli._connect()
        lark_ws_module.loop.create_task(cli._ping_loop())
        with _ws_lock:
            _ws_clients[aid] = cli
        _set_agent_ws_status(aid, "connected", "已连接飞书开放平台")
        return True
    except Exception as e:
        _set_agent_ws_status(aid, "error", str(e))
        _log.exception("飞书长连接 [%s] 连接失败", aid)
        try:
            cli._auto_reconnect = False
            await cli._disconnect()
        except Exception:
            pass
        return False
    finally:
        with _ws_lock:
            _connecting.discard(aid)


async def _disconnect_agent(agent_id: str) -> None:
    """断开并移除单个 Agent 的长连接。"""
    with _ws_lock:
        cli = _ws_clients.pop(agent_id, None)
    if cli is None:
        return
    cli._auto_reconnect = False
    try:
        await cli._disconnect()
    except Exception:
        _log.exception("飞书长连接 [%s] 断开失败", agent_id)
    info = _ws_status_by_agent.get(agent_id) or {}
    if info.get("status") != "error":
        _set_agent_ws_status(agent_id, "stopped", "连接已结束")


async def _sync_clients_async() -> int:
    """确保已启用 Agent 均已连接；清理已禁用 Agent。返回新连接数。"""
    enabled = set(list_feishu_enabled_agent_ids())
    started = 0

    for aid in list(_ws_clients.keys()):
        if aid not in enabled:
            await _disconnect_agent(aid)
            _ws_status_by_agent.pop(aid, None)

    with _ws_lock:
        stale = [
            aid
            for aid, cli in _ws_clients.items()
            if aid in enabled and cli._conn is None
        ]
    for aid in stale:
        with _ws_lock:
            _ws_clients.pop(aid, None)
        info = _ws_status_by_agent.get(aid) or {}
        if info.get("status") != "error":
            _set_agent_ws_status(aid, "stopped", "连接已结束")

    for aid in enabled:
        if await _connect_agent(aid):
            started += 1
    return started


async def _restart_all_async() -> int:
    """强制断开全部已连接 Agent 后重新同步。"""
    with _ws_lock:
        aids = list(_ws_clients.keys())
    for aid in aids:
        await _disconnect_agent(aid)
        _set_agent_ws_status(aid, "connecting", "正在重启长连接…")
    return await _sync_clients_async()


def _ws_manager_main() -> None:
    """
    在独立线程中运行单个 asyncio loop。

    lark-oapi 的 ws.Client 在模块级共用 event loop，不能多线程各调 cli.start()。
    """
    import asyncio

    import lark_oapi.ws.client as lark_ws_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    lark_ws_module.loop = loop

    global _manager_loop
    _manager_loop = loop

    async def _manager() -> None:
        while True:
            try:
                n = await _sync_clients_async()
                if n:
                    _log.info("飞书 WS 健康检查：已补启 %d 个 Agent 长连接", n)
            except Exception:
                _log.exception("飞书 WS 同步失败")
            await asyncio.sleep(_MONITOR_INTERVAL_SEC)

    _manager_ready.set()
    try:
        loop.run_until_complete(_manager())
    except Exception:
        _log.exception("飞书 WS 管理线程异常退出")
    finally:
        _manager_loop = None
        _manager_ready.clear()
        with _ws_lock:
            _ws_clients.clear()


def _ensure_ws_manager() -> None:
    """启动全局 WS 管理线程（仅一次）。"""
    global _manager_thread
    with _manager_lock:
        if _manager_thread and _manager_thread.is_alive():
            return
        _manager_ready.clear()
        _manager_thread = threading.Thread(
            target=_ws_manager_main,
            name="feishu-ws-manager",
            daemon=True,
        )
        _manager_thread.start()


def _run_on_manager(coro, *, timeout: float = 60.0) -> int:
    """在 WS 管理 loop 上执行协程并返回新连接数。"""
    import asyncio

    _ensure_ws_manager()
    if not _manager_ready.wait(timeout=10.0):
        _log.warning("飞书 WS 管理线程尚未就绪")
        return 0
    loop = _manager_loop
    if loop is None or not loop.is_running():
        return 0
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return int(future.result(timeout=timeout))
    except Exception:
        _log.exception("飞书 WS 管理操作失败")
        return 0


def reconcile_ws_clients() -> int:
    """确保已配置飞书的 Agent 均有存活 WS；清理已禁用 Agent 的状态。返回新启动数。"""
    return _run_on_manager(_sync_clients_async())


def start_feishu_ws_client() -> bool:
    """
    为全部已配置飞书凭证的 Agent 启动长连接，并开启健康检查。

    返回是否新启动了至少一个连接。
    """
    started = restart_feishu_ws_clients()
    return started > 0


def restart_feishu_ws_clients(*, force: bool = False) -> int:
    """重启已启用 Agent 的 WS 连接；force 时强制断开后重连。返回新启动连接数。"""
    if force:
        enabled = set(list_feishu_enabled_agent_ids())
        with _ws_lock:
            for aid in list(_ws_status_by_agent.keys()):
                if aid not in enabled:
                    _ws_status_by_agent.pop(aid, None)
        return _run_on_manager(_restart_all_async())
    return _run_on_manager(_sync_clients_async())


def get_ws_client_status() -> dict[str, Any]:
    """供 diagnostics 展示的长连接状态（含各 Agent）。"""
    agents: list[dict[str, Any]] = []
    enabled = list_feishu_enabled_agent_ids()
    manager_alive = bool(_manager_thread and _manager_thread.is_alive())
    any_alive = False
    for aid in enabled:
        alive = _agent_ws_alive(aid)
        any_alive = any_alive or alive
        info = dict(_ws_status_by_agent.get(aid) or {})
        status = info.get("status") or ("connected" if alive else "stopped")
        if (alive or manager_alive) and status == "connecting" and info.get("started_at"):
            if time.time() - float(info["started_at"]) > 3 and alive:
                status = "connected"
        agents.append(
            {
                "agent_id": aid,
                "thread_alive": alive or manager_alive,
                "status": status,
                "detail": info.get("detail") or "",
                "started_at": info.get("started_at"),
            }
        )
    overall = "connected" if any_alive else ("stopped" if not enabled else "connecting")
    return {
        "enabled": bool(enabled),
        "thread_alive": any_alive or manager_alive,
        "status": overall,
        "detail": f"{len(enabled)} 个 Agent 已配置飞书",
        "agents": agents,
    }
