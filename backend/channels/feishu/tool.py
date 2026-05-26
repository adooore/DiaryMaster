"""飞书渠道配置 Agent 工具（写入 data/feishu/config.json）。"""

from __future__ import annotations

from langchain.tools import tool

from backend.channels.feishu.channel_config import (
    CARD_BACKEND_CARDKIT,
    CARD_BACKEND_CLASSIC,
    REPLY_DISPLAY_REPLY_ONLY,
    REPLY_DISPLAY_WITH_STEPS,
    set_card_backend,
    set_reply_display,
)


@tool
def configure_feishu_channel(
    reply_display: str = "",
    card_backend: str = "",
) -> str:
    """
    更新飞书机器人渠道行为配置（写入本机 data/feishu/config.json）。

    reply_display 取值：
    - with_steps：最终消息保留 Agent 步骤过程，并在下方附回复正文
    - reply_only：最终消息仅显示回复正文（不保留过程）

    card_backend 取值：
    - cardkit：CardKit 卡片实体 + 流式更新（需 cardkit:card:write）
    - classic：经典 interactive 卡片 + im PATCH 更新
    """
    parts: list[str] = []
    display = (reply_display or "").strip().lower()
    if display:
        if display not in (REPLY_DISPLAY_WITH_STEPS, REPLY_DISPLAY_REPLY_ONLY):
            return (
                "reply_display 无效。请使用 with_steps 或 reply_only。"
            )
        parts.append(set_reply_display(display))
    backend = (card_backend or "").strip().lower()
    if backend:
        if backend not in (CARD_BACKEND_CARDKIT, CARD_BACKEND_CLASSIC):
            return "card_backend 无效。请使用 cardkit 或 classic。"
        parts.append(set_card_backend(backend))
    if not parts:
        return "未提供可更新项。请传入 reply_display 和/或 card_backend。"
    return "\n".join(parts)
