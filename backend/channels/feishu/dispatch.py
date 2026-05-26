"""飞书 im.message.receive_v1 事件分发：去重、串行、Agent 单轮、回复。"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from backend.channels.feishu.activity import record_dispatch_result, record_webhook_request
from backend.channels.feishu.bind import activate_session_for_open_id
from backend.channels.feishu.client import send_text, user_facing_error
from backend.channels.feishu.config import is_enabled
from backend.config import APP_ROOT, get_api_key

_log = logging.getLogger(__name__)

_PROCESSED_PATH = APP_ROOT / "data" / "feishu" / "processed.json"
_DEDUPE_TTL_SEC = 24 * 3600
_DEDUPE_MAX_ENTRIES = 2000

_dedupe_lock = threading.Lock()
_dedupe_memory: OrderedDict[str, float] = OrderedDict()
_user_locks: dict[str, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def _load_processed_disk() -> None:
    """启动时从 processed.json 预热去重缓存（可选）。"""
    if not _PROCESSED_PATH.is_file():
        return
    try:
        data = json.loads(_PROCESSED_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        now = time.time()
        with _dedupe_lock:
            for mid, ts in data.items():
                if isinstance(mid, str) and isinstance(ts, (int, float)):
                    if now - float(ts) < _DEDUPE_TTL_SEC:
                        _dedupe_memory[mid] = float(ts)
    except (json.JSONDecodeError, OSError):
        return


_load_processed_disk()


def _persist_processed() -> None:
    """将内存去重表写入磁盘（失败仅记日志）。"""
    _PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _dedupe_lock:
        snapshot = dict(_dedupe_memory)
    try:
        _PROCESSED_PATH.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        _log.warning("写入飞书去重文件失败: %s", e)


def _dedupe_seen(message_id: str) -> bool:
    """
    若 message_id 已在 TTL 内处理过返回 True（应跳过 Agent）；否则登记并返回 False。
    """
    if not message_id:
        return False
    now = time.time()
    with _dedupe_lock:
        expired = [
            k
            for k, t in _dedupe_memory.items()
            if now - t >= _DEDUPE_TTL_SEC
        ]
        for k in expired:
            _dedupe_memory.pop(k, None)
        if message_id in _dedupe_memory:
            return True
        _dedupe_memory[message_id] = now
        while len(_dedupe_memory) > _DEDUPE_MAX_ENTRIES:
            _dedupe_memory.popitem(last=False)
    _persist_processed()
    return False


def _lock_for_open_id(open_id: str) -> threading.Lock:
    """获取 per-open_id 互斥锁。"""
    with _user_locks_guard:
        if open_id not in _user_locks:
            _user_locks[open_id] = threading.Lock()
        return _user_locks[open_id]


def _resolve_event_type(payload: dict[str, Any]) -> str:
    """解析 v2.0 header.event_type 或 v1.0 event.type。"""
    header = payload.get("header") or {}
    if header.get("event_type"):
        return str(header["event_type"])
    event = payload.get("event") or {}
    if isinstance(event, dict) and event.get("type"):
        return str(event["type"])
    return str(payload.get("type") or "")


def handle_event_payload(payload: dict[str, Any]) -> None:
    """
    处理已解密/明文的事件 JSON（后台线程入口）。

    仅处理 im.message.receive_v1 文本消息；忽略机器人自身消息。
    """
    if not is_enabled():
        record_dispatch_result("skip", "飞书未启用")
        return

    event_type = _resolve_event_type(payload)
    if event_type != "im.message.receive_v1":
        record_dispatch_result("skip", f"忽略事件类型 {event_type or '(空)'}")
        return

    event = payload.get("event") or {}
    message = event.get("message") or {}
    if message.get("message_type") != "text":
        record_dispatch_result(
            "skip",
            f"非文本消息：{message.get('message_type') or '(空)'}",
        )
        return

    sender = event.get("sender") or {}
    if sender.get("sender_type") == "app":
        record_dispatch_result("skip", "忽略机器人自身消息")
        return

    sender_id = sender.get("sender_id") or {}
    open_id = (sender_id.get("open_id") or "").strip()
    chat_id = (message.get("chat_id") or "").strip()
    chat_type = (message.get("chat_type") or "").strip()
    message_id = (message.get("message_id") or "").strip()

    if _dedupe_seen(message_id):
        record_dispatch_result("skip", f"重复 message_id {message_id}")
        return

    text = _extract_text_content(message.get("content"))
    if not text:
        record_dispatch_result("skip", "消息正文为空")
        return

    receive_id, receive_id_type = _reply_target(open_id, chat_id, chat_type)
    if not receive_id:
        record_dispatch_result("skip", "无法确定回复目标")
        return

    if not open_id:
        open_id = receive_id

    user_lock = _lock_for_open_id(open_id)
    if not user_lock.acquire(blocking=False):
        try:
            send_text(
                receive_id,
                receive_id_type,
                "上一条消息仍在处理中，请稍候。",
            )
        except Exception:
            _log.exception("飞书发送「处理中」提示失败")
        return

    try:
        _process_message(
            open_id=open_id,
            text=text,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )
        record_dispatch_result("ok", f"已处理：{text[:40]}")
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


def _process_message(
    *,
    open_id: str,
    text: str,
    receive_id: str,
    receive_id_type: str,
) -> None:
    """绑定 Session、调用 chat_once、将回复发往飞书。"""
    if not get_api_key():
        send_text(
            receive_id,
            receive_id_type,
            "未配置 DeepSeek API Key，请在 DiaryMaster 浏览器设置页填写后重试。",
        )
        return

    try:
        activate_session_for_open_id(open_id)
        from backend.agent import chat_once

        result = chat_once(
            text,
            model_id=None,
            current_file=None,
            thinking_enabled=False,
            channel="feishu",
        )
    except Exception as e:
        _log.exception("飞书渠道 Agent 调用失败")
        record_dispatch_result("error", str(e)[:200])
        try:
            send_text(receive_id, receive_id_type, user_facing_error(e))
        except Exception:
            _log.exception("飞书发送错误提示失败")
        return

    if result.get("type") == "error":
        detail = result.get("detail") or "未知错误"
        send_text(receive_id, receive_id_type, f"处理失败：{detail}")
        return

    if result.get("type") != "done":
        send_text(receive_id, receive_id_type, "未收到完整回复，请重试。")
        return

    reply = (result.get("reply") or "").strip()
    if not reply:
        reply = "（无文本回复）"
    try:
        send_text(receive_id, receive_id_type, reply)
    except Exception as e:
        _log.exception("飞书发送回复失败")
        try:
            send_text(receive_id, receive_id_type, user_facing_error(e))
        except Exception:
            pass


def dispatch_in_background(payload: dict[str, Any]) -> None:
    """在后台线程处理事件，避免阻塞 webhook 响应。"""
    thread = threading.Thread(
        target=handle_event_payload,
        args=(payload,),
        daemon=True,
        name="feishu-dispatch",
    )
    thread.start()
