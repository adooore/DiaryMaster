"""Web UI 主题定义与持久化（与 style.css 配色对齐，供飞书卡片等渠道复用）。"""

from __future__ import annotations

from typing import Any

from backend.user_settings import load_settings, save_settings

UI_THEME_DARK = "dark"
UI_THEME_BLOSSOM = "blossom"
DEFAULT_UI_THEME = UI_THEME_DARK
VALID_UI_THEMES = (UI_THEME_DARK, UI_THEME_BLOSSOM)

_UI_THEME_LABELS = {
    UI_THEME_DARK: "深色 · 香槟金",
    UI_THEME_BLOSSOM: "浅色 · 白粉搭配",
}


def _hex_to_rgba(hex_color: str, alpha: float = 1.0) -> str:
    """将 #RRGGBB 转为 rgba 字符串（飞书卡片 config.style.color）。"""
    raw = (hex_color or "").strip().lstrip("#")
    if len(raw) != 6:
        return f"rgba(128,128,128,{alpha})"
    r = int(raw[0:2], 16)
    g = int(raw[2:4], 16)
    b = int(raw[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _cardkit_style_colors(
    *,
    accent: str,
    success: str,
    danger: str,
    heading: str,
) -> dict[str, Any]:
    """构建 CardKit config.style.color 自定义色板。"""
    return {
        "dm-accent": {
            "light_mode": _hex_to_rgba(accent, 0.92),
            "dark_mode": _hex_to_rgba(accent, 0.92),
        },
        "dm-success": {
            "light_mode": _hex_to_rgba(success, 0.95),
            "dark_mode": _hex_to_rgba(success, 0.95),
        },
        "dm-danger": {
            "light_mode": _hex_to_rgba(danger, 0.92),
            "dark_mode": _hex_to_rgba(danger, 0.92),
        },
        "dm-heading": {
            "light_mode": _hex_to_rgba(heading, 0.95),
            "dark_mode": _hex_to_rgba(heading, 0.95),
        },
    }


# 与 web/style.css [data-theme] 变量对应；header_* 为飞书 preset 最接近色
_UI_THEME_PALETTES: dict[str, dict[str, Any]] = {
    UI_THEME_DARK: {
        "id": UI_THEME_DARK,
        "label": _UI_THEME_LABELS[UI_THEME_DARK],
        "accent": "#c5a880",
        "success": "#8fbc8f",
        "danger": "#e07a6a",
        "heading": "#dcc9a8",
        "header_processing": "grey",
        "header_done": "yellow",
        "header_error": "red",
        "cardkit_style": _cardkit_style_colors(
            accent="#c5a880",
            success="#8fbc8f",
            danger="#e07a6a",
            heading="#dcc9a8",
        ),
    },
    UI_THEME_BLOSSOM: {
        "id": UI_THEME_BLOSSOM,
        "label": _UI_THEME_LABELS[UI_THEME_BLOSSOM],
        "accent": "#d49aad",
        "success": "#5d8f62",
        "danger": "#d45d5d",
        "heading": "#b87288",
        "header_processing": "wathet",
        "header_done": "carmine",
        "header_error": "red",
        "cardkit_style": _cardkit_style_colors(
            accent="#d49aad",
            success="#5d8f62",
            danger="#d45d5d",
            heading="#b87288",
        ),
    },
}


def normalize_ui_theme(raw: Any) -> str:
    """校验并规范化 ui_theme 取值。"""
    val = (raw or "").strip().lower()
    if val in VALID_UI_THEMES:
        return val
    return DEFAULT_UI_THEME


def get_ui_theme() -> str:
    """读取当前 UI 主题（user_settings.json）。"""
    data = load_settings()
    return normalize_ui_theme(data.get("ui_theme"))


def set_ui_theme(theme: str) -> str:
    """写入 ui_theme 并返回中文说明。"""
    normalized = normalize_ui_theme(theme)
    data = load_settings()
    data["ui_theme"] = normalized
    save_settings(data)
    label = _UI_THEME_LABELS[normalized]
    return f"已更新界面主题为：{label}（{normalized}）"


def get_ui_theme_palette(theme: str | None = None) -> dict[str, Any]:
    """返回指定主题的飞书卡片配色板；默认读当前设置。"""
    key = normalize_ui_theme(theme or get_ui_theme())
    return dict(_UI_THEME_PALETTES[key])


def ui_theme_for_api() -> dict[str, Any]:
    """供 GET /api/settings 的 ui_theme 块。"""
    current = get_ui_theme()
    return {
        "ui_theme": current,
        "ui_theme_label": _UI_THEME_LABELS[current],
        "ui_theme_options": [
            {"value": UI_THEME_DARK, "label": _UI_THEME_LABELS[UI_THEME_DARK]},
            {"value": UI_THEME_BLOSSOM, "label": _UI_THEME_LABELS[UI_THEME_BLOSSOM]},
        ],
    }
