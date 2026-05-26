"""飞书卡片 JSON 构建：CardKit 2.0 与经典 interactive。"""

from __future__ import annotations

import json
from typing import Any

from backend.ui_theme import get_ui_theme_palette

# 飞书卡片 content 上限约 30KB，留余量给 JSON 转义
_CARD_MAX_BYTES = 28_000
_CARD_HEADER_TITLE = "DiaryMaster"
CARDKIT_ELEMENT_BODY = "dm_body"


def _palette() -> dict[str, Any]:
    """读取当前 Web UI 主题对应的飞书配色板。"""
    return get_ui_theme_palette()


def _card_config() -> dict[str, Any]:
    """返回 classic 卡片 config（可 PATCH）。"""
    return {"wide_screen_mode": True, "update_multi": True}


def _cardkit_config(*, streaming: bool) -> dict[str, Any]:
    """返回 CardKit config，含 UI 主题自定义色。"""
    pal = _palette()
    config: dict[str, Any] = {
        "update_multi": True,
        "streaming_mode": streaming,
        "style": {"color": pal["cardkit_style"]},
    }
    if streaming:
        config["streaming_config"] = _cardkit_streaming_config()
    return config


def _cardkit_header(subtitle: str, template: str) -> dict[str, Any]:
    """CardKit 标题区：preset 主题色 + 强调色图标。"""
    return {
        "title": {"tag": "plain_text", "content": _CARD_HEADER_TITLE},
        "subtitle": {"tag": "plain_text", "content": subtitle[:80]},
        "template": template,
        "icon": {
            "tag": "standard_icon",
            "token": "robot_outlined",
            "color": "dm-accent",
        },
    }


def card_content_bytes(card: dict[str, Any]) -> int:
    """估算卡片 JSON 序列化后的字节长度。"""
    return len(json.dumps(card, ensure_ascii=False).encode("utf-8"))


def _cardkit_streaming_config() -> dict[str, Any]:
    """CardKit 流式更新默认配置。"""
    return {
        "print_frequency_ms": {"default": 70, "android": 70, "ios": 70, "pc": 70},
        "print_step": {"default": 1, "android": 1, "ios": 1, "pc": 1},
        "print_strategy": "fast",
    }


def build_cardkit_json(
    *,
    subtitle: str,
    body_md: str,
    template: str,
    streaming: bool = True,
) -> dict[str, Any]:
    """构建 CardKit 卡片 JSON 2.0（配色跟随 Web UI 主题）。"""
    return {
        "schema": "2.0",
        "config": _cardkit_config(streaming=streaming),
        "header": _cardkit_header(subtitle, template),
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "element_id": CARDKIT_ELEMENT_BODY,
                    "content": body_md,
                },
            ],
        },
    }


def build_cardkit_initial_json() -> dict[str, Any]:
    """CardKit 占位卡片（处理中主题色）。"""
    pal = _palette()
    return build_cardkit_json(
        subtitle="⏳ 处理中…",
        body_md="⏳ 处理中…",
        template=pal["header_processing"],
        streaming=True,
    )


def build_cardkit_final_json(body_md: str) -> dict[str, Any]:
    """CardKit 最终卡片（完成主题色 + 关闭流式）。"""
    pal = _palette()
    return build_cardkit_json(
        subtitle="✅ 已完成",
        body_md=body_md,
        template=pal["header_done"],
        streaming=False,
    )


def progress_markdown(step_lines: list[str]) -> str:
    """CardKit 进行中 markdown 正文。"""
    if not step_lines:
        return "⏳ 处理中…"
    lines_md = "\n".join(f"• {ln}" for ln in step_lines)
    return f"⏳ **处理中…**\n\n{lines_md}"


def final_markdown(
    step_lines: list[str],
    reply: str,
    *,
    keep_process: bool = True,
) -> str:
    """CardKit 最终 markdown 正文。"""
    reply_text = (reply or "").strip() or "（无文本回复）"
    if not keep_process:
        return reply_text
    parts: list[str] = ["✅ **已完成**"]
    if step_lines:
        parts.append("")
        parts.extend(f"• {ln}" for ln in step_lines)
    parts.extend(["", "---", "", reply_text])
    return "\n".join(parts)


def fit_final_markdown(
    step_lines: list[str],
    reply: str,
    *,
    keep_process: bool,
    max_chars: int = 90_000,
) -> tuple[str, str | None]:
    """
    在字符上限内构建 CardKit 最终 markdown；过长时截断并返回续发文本。

    返回 (markdown, 续发文本或 None)。
    """
    text = final_markdown(step_lines, reply, keep_process=keep_process)
    if len(text) <= max_chars:
        return text, None
    if not keep_process:
        head = reply[: max_chars - 20] + "\n\n（续见下一条）"
        return head, reply[max_chars - 20 :] or None
    # 保留步骤时优先截断回复
    reply_text = (reply or "").strip() or "（无文本回复）"
    low, high = 0, len(reply_text)
    best = 0
    while low <= high:
        mid = (low + high) // 2
        suffix = "\n\n（续见下一条）" if mid < len(reply_text) else ""
        trial = final_markdown(step_lines, reply_text[:mid] + suffix, keep_process=True)
        if len(trial) <= max_chars:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    if best < len(reply_text):
        return (
            final_markdown(step_lines, reply_text[:best] + "\n\n（续见下一条）", keep_process=True),
            reply_text[best:],
        )
    return final_markdown(step_lines, reply_text[:500] + "…", keep_process=False), None


def build_initial_card() -> dict[str, Any]:
    """构建占位 classic 卡片。"""
    pal = _palette()
    return {
        "config": _card_config(),
        "header": _header(pal["header_processing"], "⏳ 处理中…"),
        "elements": [
            _markdown_div("⏳ 处理中…"),
        ],
    }


def build_progress_card(step_lines: list[str]) -> dict[str, Any]:
    """构建进行中 classic 卡片。"""
    pal = _palette()
    if not step_lines:
        body = "⏳ 处理中…"
    else:
        lines_md = "\n".join(f"• {ln}" for ln in step_lines)
        body = f"⏳ **处理中…**\n\n{lines_md}"
    return {
        "config": _card_config(),
        "header": _header(pal["header_processing"], "⏳ 处理中…"),
        "elements": [_markdown_div(body)],
    }


def build_final_card(
    step_lines: list[str],
    reply: str,
    *,
    keep_process: bool = True,
) -> dict[str, Any]:
    """
    构建最终 classic 卡片。

    keep_process=True 时保留步骤区、分隔线与回复；False 时仅展示回复正文。
    """
    pal = _palette()
    reply_text = (reply or "").strip() or "（无文本回复）"
    if not keep_process:
        return {
            "config": _card_config(),
            "header": _header(pal["header_done"], "DiaryMaster"),
            "elements": [_markdown_div(reply_text)],
        }

    elements: list[dict[str, Any]] = []
    if step_lines:
        steps_md = "\n".join(f"• {ln}" for ln in step_lines)
        elements.append(_markdown_div(f"✅ **已完成**\n\n{steps_md}"))
    else:
        elements.append(_markdown_div("✅ **已完成**"))
    elements.append({"tag": "hr"})
    elements.append(_markdown_div(reply_text))
    return {
        "config": _card_config(),
        "header": _header(pal["header_done"], "✅ 已完成"),
        "elements": elements,
    }


def build_error_card(message: str) -> dict[str, Any]:
    """构建错误 classic 卡片。"""
    pal = _palette()
    text = (message or "").strip() or "处理失败"
    if len(text) > 500:
        text = text[:480] + "…"
    return {
        "config": _card_config(),
        "header": _header(pal["header_error"], "处理失败"),
        "elements": [_markdown_div(text)],
    }


def fit_final_card(
    step_lines: list[str],
    reply: str,
    *,
    keep_process: bool,
    max_bytes: int = _CARD_MAX_BYTES,
) -> tuple[dict[str, Any], str | None]:
    """
    在字节上限内构建最终卡片；若回复过长则截断并返回需续发的余下文本。

    返回 (卡片 dict, 续发文本或 None)。
    """
    card = build_final_card(step_lines, reply, keep_process=keep_process)
    if card_content_bytes(card) <= max_bytes:
        return card, None

    if not keep_process:
        return _truncate_reply_only(reply, max_bytes)

    card, overflow = _truncate_with_steps(step_lines, reply, max_bytes)
    return card, overflow


def _header(template: str, subtitle: str) -> dict[str, Any]:
    """构建卡片 header。"""
    return {
        "title": {"tag": "plain_text", "content": _CARD_HEADER_TITLE},
        "subtitle": {"tag": "plain_text", "content": subtitle[:80]},
        "template": template,
    }


def _markdown_div(content: str) -> dict[str, Any]:
    """构建 lark_md div 元素。"""
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def _truncate_reply_only(
    reply: str,
    max_bytes: int,
) -> tuple[dict[str, Any], str | None]:
    """仅回复模式下截断卡片内回复并返回溢出部分。"""
    reply_text = (reply or "").strip() or "（无文本回复）"
    low, high = 0, len(reply_text)
    best = 0
    while low <= high:
        mid = (low + high) // 2
        candidate = reply_text[:mid]
        if mid < len(reply_text):
            candidate += "\n\n（续见下一条）"
        trial = build_final_card([], candidate, keep_process=False)
        if card_content_bytes(trial) <= max_bytes:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    if best >= len(reply_text):
        return build_final_card([], reply_text, keep_process=False), None
    suffix = reply_text[best:]
    return (
        build_final_card([], reply_text[:best] + "\n\n（续见下一条）", keep_process=False),
        suffix or None,
    )


def _truncate_with_steps(
    step_lines: list[str],
    reply: str,
    max_bytes: int,
) -> tuple[dict[str, Any], str | None]:
    """保留步骤时优先截断回复区，必要时缩减步骤行数。"""
    reply_text = (reply or "").strip() or "（无文本回复）"
    steps = list(step_lines)

    for _ in range(len(steps) + 2):
        card = build_final_card(steps, reply_text, keep_process=True)
        if card_content_bytes(card) <= max_bytes:
            return card, None

        if reply_text:
            low, high = 0, len(reply_text)
            best = 0
            while low <= high:
                mid = (low + high) // 2
                suffix = "\n\n（续见下一条）" if mid < len(reply_text) else ""
                trial_reply = reply_text[:mid] + suffix
                trial = build_final_card(steps, trial_reply, keep_process=True)
                if card_content_bytes(trial) <= max_bytes:
                    best = mid
                    low = mid + 1
                else:
                    high = mid - 1
            if best < len(reply_text):
                return (
                    build_final_card(
                        steps,
                        reply_text[:best] + "\n\n（续见下一条）",
                        keep_process=True,
                    ),
                    reply_text[best:],
                )

        if steps:
            steps = steps[:-1]
            continue

        short = reply_text[:200] + ("…" if len(reply_text) > 200 else "")
        card = build_final_card([], short, keep_process=False)
        if card_content_bytes(card) <= max_bytes:
            overflow = reply_text[200:] if len(reply_text) > 200 else None
            return card, overflow
        break

    return build_error_card("回复内容过长，请在 Web 端查看完整结果。"), None
