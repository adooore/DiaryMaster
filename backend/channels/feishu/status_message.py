"""飞书单条消息状态更新（CardKit 实体或 classic interactive 卡片）。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from backend.channels.feishu.card_builder import (
    CARDKIT_ELEMENT_BODY,
    build_cardkit_final_json,
    build_cardkit_initial_json,
    build_initial_card,
    build_progress_card,
    fit_final_card,
    fit_final_markdown,
    progress_markdown,
)
from backend.channels.feishu.cardkit_client import (
    FeishuCardKitError,
    create_card_entity,
    send_card_entity,
    stream_update_element,
    update_card_entity,
)
from backend.channels.feishu.channel_config import CARD_BACKEND_CARDKIT, get_card_backend
from backend.channels.feishu.client import (
    FeishuClientError,
    send_interactive_card,
    send_text,
    send_text_message,
    update_interactive_card,
    update_text,
)

_log = logging.getLogger(__name__)

_MIN_UPDATE_INTERVAL_SEC = 0.85
_MAX_STEP_LINES = 8


def format_step_line(step: dict[str, Any]) -> str | None:
    """将 Agent 步骤格式化为飞书状态行（None 表示跳过）。"""
    kind = step.get("kind")
    label = (step.get("label") or "").strip()
    status = step.get("status") or ""
    if not label and kind != "tool":
        return None
    if kind == "tool":
        if status == "running":
            return f"… {label}"
        if status == "error":
            return f"✗ {label}"
        return f"✓ {label}"
    if kind == "thinking":
        return f"💭 {label}" if status == "running" else None
    if kind == "reply_status":
        if status == "running":
            return f"✍ {label}"
        if status in ("done", "error"):
            prefix = "✓" if status == "done" else "✗"
            return f"{prefix} {label}"
        return None
    if kind == "reasoning":
        return None
    if kind == "model":
        return f"🤖 {label}" if label else None
    return label or None


class _StepStateMixin:
    """步骤列表与节流调度（classic / CardKit 共用）。"""

    def __init__(self) -> None:
        self._step_lines: dict[str, str] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._last_update_at = 0.0
        self._timer: threading.Timer | None = None

    def on_step(self, step: dict[str, Any]) -> None:
        """收到 Agent 步骤时更新内部状态并节流推送飞书。"""
        line = format_step_line(step)
        if not line:
            return
        step_id = str(step.get("id") or f"anon-{len(self._order)}")
        with self._lock:
            if step_id not in self._step_lines:
                self._order.append(step_id)
            self._step_lines[step_id] = line
            self._schedule_update_locked(force=False)

    def _visible_step_lines_unlocked(self) -> list[str]:
        """在已持锁时返回当前应展示的步骤行（进行中仅最近若干条）。"""
        ids = self._order[-_MAX_STEP_LINES:]
        return [self._step_lines[sid] for sid in ids if sid in self._step_lines]

    def _all_step_lines_unlocked(self) -> list[str]:
        """在已持锁时返回全部步骤行（用于最终卡片）。"""
        return [self._step_lines[sid] for sid in self._order if sid in self._step_lines]

    def flush_progress(self, *, force: bool = False) -> None:
        """立即把当前进度推送到飞书。"""
        with self._lock:
            self._flush_locked(force=force)

    def _schedule_update_locked(self, *, force: bool) -> None:
        """在锁内调度节流更新。"""
        now = time.time()
        if force or now - self._last_update_at >= _MIN_UPDATE_INTERVAL_SEC:
            self._flush_locked(force=True)
            return
        if self._timer and self._timer.is_alive():
            return
        delay = max(0.05, _MIN_UPDATE_INTERVAL_SEC - (now - self._last_update_at))

        def _fire() -> None:
            with self._lock:
                self._flush_locked(force=True)

        self._timer = threading.Timer(delay, _fire)
        self._timer.daemon = True
        self._timer.start()

    def finalize_to(
        self,
        text: str,
        *,
        receive_id: str,
        receive_id_type: str,
        keep_process: bool = True,
    ) -> None:
        """更新为最终展示（子类实现具体推送）。"""
        raise NotImplementedError

    def _flush_locked(self, *, force: bool) -> None:
        """在锁内执行进度推送（子类实现）。"""
        raise NotImplementedError


class FeishuStatusUpdater(_StepStateMixin):
    """维护一条 classic interactive 卡片，随 Agent 步骤 PATCH 更新。"""

    def __init__(self, message_id: str) -> None:
        super().__init__()
        self._message_id = message_id

    def finalize_to(
        self,
        text: str,
        *,
        receive_id: str,
        receive_id_type: str,
        keep_process: bool = True,
    ) -> None:
        """PATCH 最终 classic 卡片。"""
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            step_lines = self._all_step_lines_unlocked() if keep_process else []
            reply = (text or "").strip() or "（无文本回复）"
        self._patch_final(
            step_lines,
            reply,
            keep_process=keep_process,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )

    def _patch_final(
        self,
        step_lines: list[str],
        reply: str,
        *,
        keep_process: bool,
        receive_id: str,
        receive_id_type: str,
    ) -> None:
        """PATCH 最终卡片；超长时截断并续发文本，失败时 fallback。"""
        card, overflow = fit_final_card(
            step_lines,
            reply,
            keep_process=keep_process,
        )
        try:
            update_interactive_card(self._message_id, card)
        except FeishuClientError as e:
            _log.warning("飞书更新最终卡片失败，改发文本: %s", e)
            fallback = _final_text_fallback(step_lines, reply, keep_process=keep_process)
            send_text(receive_id, receive_id_type, fallback)
            if overflow:
                send_text(receive_id, receive_id_type, overflow)
            return
        if overflow:
            send_text(receive_id, receive_id_type, overflow)

    def _flush_locked(self, *, force: bool) -> None:
        """在锁内 PATCH 进度卡片。"""
        now = time.time()
        if not force and now - self._last_update_at < _MIN_UPDATE_INTERVAL_SEC:
            return
        card = build_progress_card(self._visible_step_lines_unlocked())
        try:
            update_interactive_card(self._message_id, card)
            self._last_update_at = now
        except FeishuClientError as e:
            _log.warning("飞书卡片状态更新失败: %s", e)


class CardKitStatusUpdater(_StepStateMixin):
    """CardKit 卡片实体：创建 → 发送 → 流式更新 markdown 元素。"""

    def __init__(self, card_id: str, message_id: str) -> None:
        super().__init__()
        self._card_id = card_id
        self._message_id = message_id
        self._sequence = 0

    def _next_sequence(self) -> int:
        """返回严格递增的 CardKit 操作序号。"""
        self._sequence += 1
        return self._sequence

    def finalize_to(
        self,
        text: str,
        *,
        receive_id: str,
        receive_id_type: str,
        keep_process: bool = True,
    ) -> None:
        """关闭流式模式并写入最终 markdown。"""
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            step_lines = self._all_step_lines_unlocked() if keep_process else []
            reply = (text or "").strip() or "（无文本回复）"
        body_md, overflow = fit_final_markdown(
            step_lines,
            reply,
            keep_process=keep_process,
        )
        seq = self._next_sequence()
        try:
            update_card_entity(
                self._card_id,
                build_cardkit_final_json(body_md),
                seq,
            )
        except FeishuCardKitError as e:
            _log.warning("CardKit 最终更新失败，改发文本: %s", e)
            fallback = _final_text_fallback(step_lines, reply, keep_process=keep_process)
            send_text(receive_id, receive_id_type, fallback)
            if overflow:
                send_text(receive_id, receive_id_type, overflow)
            return
        if overflow:
            send_text(receive_id, receive_id_type, overflow)

    def _flush_locked(self, *, force: bool) -> None:
        """在锁内流式更新 markdown 正文。"""
        now = time.time()
        if not force and now - self._last_update_at < _MIN_UPDATE_INTERVAL_SEC:
            return
        md = progress_markdown(self._visible_step_lines_unlocked())
        seq = self._next_sequence()
        try:
            stream_update_element(
                self._card_id,
                CARDKIT_ELEMENT_BODY,
                md,
                seq,
            )
            self._last_update_at = now
        except FeishuCardKitError as e:
            _log.warning("CardKit 进度更新失败: %s", e)


def _final_text_fallback(
    step_lines: list[str],
    reply: str,
    *,
    keep_process: bool,
) -> str:
    """卡片更新失败时拼接等效纯文本。"""
    if not keep_process:
        return reply
    parts: list[str] = ["✅ 已完成"]
    if step_lines:
        parts.append("")
        parts.extend(f"• {ln}" for ln in step_lines)
    parts.extend(["", "—— 回复 ——", "", reply])
    return "\n".join(parts)


def start_status_message(receive_id: str, receive_id_type: str) -> _StepStateMixin:
    """按配置发送 CardKit 或 classic 占位卡片；失败时逐级回退。"""
    if get_card_backend() == CARD_BACKEND_CARDKIT:
        try:
            return _start_cardkit_status_message(receive_id, receive_id_type)
        except FeishuCardKitError as e:
            _log.warning("CardKit 占位失败，回退 classic 卡片: %s", e)
    return _start_classic_status_message(receive_id, receive_id_type)


def _start_cardkit_status_message(
    receive_id: str,
    receive_id_type: str,
) -> CardKitStatusUpdater:
    """创建 CardKit 卡片实体并发送到会话。"""
    card_id = create_card_entity(build_cardkit_initial_json())
    message_id = send_card_entity(receive_id, receive_id_type, card_id)
    return CardKitStatusUpdater(card_id, message_id)


def _start_classic_status_message(
    receive_id: str,
    receive_id_type: str,
) -> FeishuStatusUpdater | _TextFallbackUpdater:
    """发送 classic interactive 占位卡片。"""
    try:
        message_id = send_interactive_card(
            receive_id,
            receive_id_type,
            build_initial_card(),
        )
        return FeishuStatusUpdater(message_id)
    except FeishuClientError as e:
        _log.warning("飞书卡片占位发送失败，回退文本: %s", e)
        message_id = send_text_message(receive_id, receive_id_type, "⏳ 处理中…")
        return _TextFallbackUpdater(message_id)


class _TextFallbackUpdater(FeishuStatusUpdater):
    """卡片 API 不可用时的文本 PUT 回退更新器。"""

    def _flush_locked(self, *, force: bool) -> None:
        """在锁内执行文本 PUT。"""
        now = time.time()
        if not force and now - self._last_update_at < _MIN_UPDATE_INTERVAL_SEC:
            return
        lines = self._visible_step_lines_unlocked()
        if not lines:
            text = "⏳ 处理中…"
        else:
            body = "\n".join(f"• {ln}" for ln in lines)
            text = f"⏳ 处理中…\n\n{body}"
        try:
            update_text(self._message_id, text)
            self._last_update_at = now
        except FeishuClientError as e:
            _log.warning("飞书文本状态更新失败: %s", e)

    def _patch_final(
        self,
        step_lines: list[str],
        reply: str,
        *,
        keep_process: bool,
        receive_id: str,
        receive_id_type: str,
    ) -> None:
        """文本模式写入最终消息。"""
        body = _final_text_fallback(step_lines, reply, keep_process=keep_process)
        try:
            update_text(self._message_id, body)
        except FeishuClientError as e:
            _log.warning("飞书更新最终文本失败，改发新消息: %s", e)
            send_text(receive_id, receive_id_type, body)
