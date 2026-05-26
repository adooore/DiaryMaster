"""UI 主题 Agent 工具。"""

from __future__ import annotations

from langchain.tools import tool

from backend.ui_theme import UI_THEME_BLOSSOM, UI_THEME_DARK, set_ui_theme


@tool
def set_app_ui_theme(theme: str) -> str:
    """
    更新 DiaryMaster Web / 飞书卡片共用的界面主题（写入 user_settings.json）。

    theme 取值：
    - dark：深色 · 香槟金（accent #c5a880）
    - blossom：浅色 · 白粉搭配（accent #d49aad）
    """
    mode = (theme or "").strip().lower()
    if mode not in (UI_THEME_DARK, UI_THEME_BLOSSOM):
        return "无效取值。请使用 dark 或 blossom。"
    return set_ui_theme(mode)
