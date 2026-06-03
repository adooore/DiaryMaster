"""飞书 im.message.receive_v1 事件分发：去重、串行、Agent 单轮、回复。"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from backend.channels.feishu.activity import record_dispatch_result
from backend.channels.feishu.bind import activate_session_for_open_id
from backend.channels.feishu.client import (
    FeishuClientError,
    send_text,
    user_facing_error,
)
from backend.channels.feishu.status_message import start_status_message
from backend.channels.feishu.config import is_enabled
from backend.config import get_api_key

_log = logging.getLogger(__name__)

_DEDUPE_TTL_SEC = 24 * 3600
_DEDUPE_MAX_ENTRIES = 2000
_INTERNAL_AGENT_KEY = "_agent_id"

_dedupe_lock = threading.Lock()
_dedupe_by_agent: dict[str, OrderedDict[str, float]] = {}
_user_locks: dict[str, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def _processed_path(agent_id: str) -> Path:
    """返回 Agent 的 processed.json 路径。"""
    from backend.agents.registry import agent_registry

    return agent_registry.feishu_dir(agent_id) / "processed.json"


def _get_dedupe_cache(agent_id: str) -> OrderedDict[str, float]:
    """获取或创建 Agent 去重表；调用方须已持有 _dedupe_lock。"""
    aid = (agent_id or "").strip()
    cache = _dedupe_by_agent.get(aid)
    if cache is not None:
        return cache
    cache = OrderedDict()
    path = _processed_path(aid)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                now = time.time()
                for mid, ts in data.items():
                    if isinstance(mid, str) and isinstance(ts, (int, float)):
                        if now - float(ts) < _DEDUPE_TTL_SEC:
                            cache[mid] = float(ts)
        except (json.JSONDecodeError, OSError):
            pass
    _dedupe_by_agent[aid] = cache
    return cache


def _persist_processed(agent_id: str) -> None:
    """将 Agent 去重表写入磁盘（失败仅记日志）。"""
    aid = (agent_id or "").strip()
    path = _processed_path(aid)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _dedupe_lock:
        snapshot = dict(_dedupe_by_agent.get(aid) or {})
    try:
        path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        _log.warning("写入飞书去重文件失败 [%s]: %s", aid, e)


def _dedupe_seen(agent_id: str, message_id: str) -> bool:
    """
    若 message_id 已在 TTL 内处理过返回 True（应跳过 Agent）；否则登记并返回 False。
    """
    if not message_id or not agent_id:
        return False
    now = time.time()
    with _dedupe_lock:
        cache = _get_dedupe_cache(agent_id)
        expired = [k for k, t in cache.items() if now - t >= _DEDUPE_TTL_SEC]
        for k in expired:
            cache.pop(k, None)
        if message_id in cache:
            return True
        cache[message_id] = now
        while len(cache) > _DEDUPE_MAX_ENTRIES:
            cache.popitem(last=False)
    _persist_processed(agent_id)
    return False


def _lock_for_user(agent_id: str, open_id: str) -> threading.Lock:
    """获取 per-agent+open_id 互斥锁。"""
    key = f"{agent_id}:{open_id}"
    with _user_locks_guard:
        if key not in _user_locks:
            _user_locks[key] = threading.Lock()
        return _user_locks[key]


def _resolve_event_type(payload: dict[str, Any]) -> str:
    """解析 v2.0 header.event_type 或 v1.0 event.type。"""
    header = payload.get("header") or {}
    if header.get("event_type"):
        return str(header["event_type"])
    event = payload.get("event") or {}
    if isinstance(event, dict) and event.get("type"):
        return str(event["type"])
    return str(payload.get("type") or "")


def resolve_agent_id(payload: dict[str, Any]) -> str | None:
    """按 WS 注入的 _agent_id 或 header.app_id 解析目标 Agent。"""
    internal = (payload.get(_INTERNAL_AGENT_KEY) or "").strip()
    if internal:
        from backend.agents.registry import agent_registry

        try:
            agent_registry.get_profile(internal)
            return internal
        except KeyError:
            return None

    header = payload.get("header") or {}
    app_id = (header.get("app_id") or "").strip()
    if not app_id:
        return None

    from backend.agents.registry import agent_registry

    profile = agent_registry.find_by_feishu_app_id(app_id)
    return profile.agent_id if profile else None


def handle_event_payload(payload: dict[str, Any]) -> None:
    """
    处理已解密/明文的事件 JSON（后台线程入口）。

    仅处理 im.message.receive_v1 文本消息；忽略机器人自身消息。
    """
    agent_id = resolve_agent_id(payload)
    if not agent_id:
        record_dispatch_result(agent_id, "skip", "无法匹配飞书 App ID 到 Agent")
        return
    if not is_enabled(agent_id):
        record_dispatch_result(agent_id, "skip", "飞书未启用")
        return

    event_type = _resolve_event_type(payload)
    if event_type != "im.message.receive_v1":
        record_dispatch_result(agent_id, "skip", f"忽略事件类型 {event_type or '(空)'}")
        return

    event = payload.get("event") or {}
    message = event.get("message") or {}
    if message.get("message_type") != "text":
        record_dispatch_result(
            agent_id,
            "skip",
            f"非文本消息：{message.get('message_type') or '(空)'}",
        )
        return

    sender = event.get("sender") or {}
    if sender.get("sender_type") == "app":
        record_dispatch_result(agent_id, "skip", "忽略机器人自身消息")
        return

    sender_id = sender.get("sender_id") or {}
    open_id = (sender_id.get("open_id") or "").strip()
    chat_id = (message.get("chat_id") or "").strip()
    chat_type = (message.get("chat_type") or "").strip()
    message_id = (message.get("message_id") or "").strip()

    if _dedupe_seen(agent_id, message_id):
        record_dispatch_result(agent_id, "skip", f"重复 message_id {message_id}")
        return

    text = _extract_text_content(message.get("content"))
    if not text:
        record_dispatch_result(agent_id, "skip", "消息正文为空")
        return

    receive_id, receive_id_type = _reply_target(open_id, chat_id, chat_type)
    if not receive_id:
        record_dispatch_result(agent_id, "skip", "无法确定回复目标")
        return

    if not open_id:
        open_id = receive_id

    user_lock = _lock_for_user(agent_id, open_id)
    if not user_lock.acquire(blocking=False):
        try:
            send_text(
                receive_id,
                receive_id_type,
                "上一条消息仍在处理中，请稍候。",
                agent_id=agent_id,
            )
        except Exception:
            _log.exception("飞书发送「处理中」提示失败")
        return

    try:
        _process_message(
            agent_id=agent_id,
            open_id=open_id,
            text=text,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )
        record_dispatch_result(agent_id, "ok", f"已处理：{text[:40]}")
    finally:
        user_lock.release()


def _extract_text_content(content: Any) -> str:
    """从 message.content JSON 字符串解析 text 字段。"""
    if not content:
        return ""
    if isinstance(content, dict):
        return (content.get("text") or "").strip()
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content.strip()
        if isinstance(parsed, dict):
            return (parsed.get("text") or "").strip()
        return str(parsed).strip()
    return ""


def _reply_target(open_id: str, chat_id: str, chat_type: str = "") -> tuple[str, str]:
    """选择发消息用的 receive_id 与类型；单聊优先 open_id。"""
    if chat_type == "p2p" and open_id:
        return open_id, "open_id"
    if chat_id:
        return chat_id, "chat_id"
    if open_id:
        return open_id, "open_id"
    return "", ""


def _finalize_feishu_reply(
    updater: Any,
    *,
    agent_id: str,
    receive_id: str,
    receive_id_type: str,
    reply: str,
) -> None:
    """将状态消息更新为最终展示（是否保留过程由 Agent 飞书 config 决定）。"""
    from backend.channels.feishu.channel_config import keep_process_in_final_message

    updater.finalize_to(
        (reply or "").strip() or "（无文本回复）",
        receive_id=receive_id,
        receive_id_type=receive_id_type,
        keep_process=keep_process_in_final_message(agent_id),
    )


def _process_message(
    *,
    agent_id: str,
    open_id: str,
    text: str,
    receive_id: str,
    receive_id_type: str,
) -> None:
    """绑定 Session、调用 chat_once（步骤更新同一条飞书卡片）、最终 PATCH 回复。"""
    from backend.agents.context import set_active_agent_id
    from backend.channels.feishu.slash import try_handle_slash_command

    set_active_agent_id(agent_id)

    slash_reply = try_handle_slash_command(
        text=text,
        agent_id=agent_id,
        open_id=open_id,
    )
    if slash_reply is not None:
        send_text(receive_id, receive_id_type, slash_reply, agent_id=agent_id)
        return

    if not get_api_key(agent_id):
        send_text(
            receive_id,
            receive_id_type,
            "未配置 DeepSeek API Key，请在 DiaryMaster 设置页为该 Agent 或实例填写密钥后重试。",
            agent_id=agent_id,
        )
        return

    try:
        status = start_status_message(receive_id, receive_id_type)
    except FeishuClientError as e:
        _log.warning("飞书状态消息发送失败，回退为仅最终回复: %s", e)
        status = None

    try:
        activate_session_for_open_id(open_id, agent_id)
        from backend.agent import chat_once

        def on_step(step: dict[str, Any]) -> None:
            if status is not None:
                status.on_step(step)

        result = chat_once(
            text,
            model_id=None,
            current_file=None,
            thinking_enabled=False,
            channel="feishu",
            on_step=on_step,
        )
    except Exception as e:
        _log.exception("飞书渠道 Agent 调用失败")
        record_dispatch_result(agent_id, "error", str(e)[:200])
        err_text = user_facing_error(e)
        if status is not None:
            try:
                status.finalize_to(
                    err_text, receive_id=receive_id, receive_id_type=receive_id_type
                )
            except Exception:
                send_text(receive_id, receive_id_type, err_text, agent_id=agent_id)
        else:
            send_text(receive_id, receive_id_type, err_text, agent_id=agent_id)
        return

    if result.get("type") == "error":
        detail = result.get("detail") or "未知错误"
        err_text = f"处理失败：{detail}"
        if status is not None:
            status.finalize_to(
                err_text, receive_id=receive_id, receive_id_type=receive_id_type
            )
        else:
            send_text(receive_id, receive_id_type, err_text, agent_id=agent_id)
        return

    if result.get("type") != "done":
        msg = "未收到完整回复，请重试。"
        if status is not None:
            status.finalize_to(msg, receive_id=receive_id, receive_id_type=receive_id_type)
        else:
            send_text(receive_id, receive_id_type, msg, agent_id=agent_id)
        return

    reply = (result.get("reply") or "").strip()
    try:
        if status is not None:
            status.flush_progress(force=True)
            _finalize_feishu_reply(
                status,
                agent_id=agent_id,
                receive_id=receive_id,
                receive_id_type=receive_id_type,
                reply=reply,
            )
        else:
            send_text(
                receive_id,
                receive_id_type,
                reply or "（无文本回复）",
                agent_id=agent_id,
            )
    except Exception as e:
        _log.exception("飞书发送回复失败")
        try:
            send_text(receive_id, receive_id_type, user_facing_error(e), agent_id=agent_id)
        except Exception:
            pass


def dispatch_in_background(payload: dict[str, Any], *, agent_id: str | None = None) -> None:
    """在后台线程处理事件，避免阻塞 webhook 响应。"""
    enriched = dict(payload)
    if agent_id:
        enriched[_INTERNAL_AGENT_KEY] = agent_id
    thread = threading.Thread(
        target=handle_event_payload,
        args=(enriched,),
        daemon=True,
        name="feishu-dispatch",
    )
    thread.start()
