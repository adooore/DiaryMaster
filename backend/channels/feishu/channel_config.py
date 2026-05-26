"""飞书渠道行为配置（data/feishu/config.json，与凭证分离）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.config import APP_ROOT

CONFIG_PATH = APP_ROOT / "data" / "feishu" / "config.json"

REPLY_DISPLAY_WITH_STEPS = "with_steps"
REPLY_DISPLAY_REPLY_ONLY = "reply_only"
DEFAULT_REPLY_DISPLAY = REPLY_DISPLAY_WITH_STEPS

CARD_BACKEND_CLASSIC = "classic"
CARD_BACKEND_CARDKIT = "cardkit"
DEFAULT_CARD_BACKEND = CARD_BACKEND_CARDKIT

_REPLY_DISPLAY_LABELS = {
    REPLY_DISPLAY_WITH_STEPS: "保留过程 + 回复",
    REPLY_DISPLAY_REPLY_ONLY: "仅最终回复",
}

_CARD_BACKEND_LABELS = {
    CARD_BACKEND_CLASSIC: "经典 interactive（im PATCH）",
    CARD_BACKEND_CARDKIT: "CardKit 实体（cardkit:card:write）",
}


def _normalize_reply_display(raw: Any) -> str:
    """校验并规范化 reply_display 取值。"""
    val = (raw or "").strip().lower()
    if val in (REPLY_DISPLAY_WITH_STEPS, REPLY_DISPLAY_REPLY_ONLY):
        return val
    return DEFAULT_REPLY_DISPLAY


def _normalize_card_backend(raw: Any) -> str:
    """校验并规范化 card_backend 取值。"""
    val = (raw or "").strip().lower()
    if val in (CARD_BACKEND_CLASSIC, CARD_BACKEND_CARDKIT):
        return val
    return DEFAULT_CARD_BACKEND


def load_channel_config() -> dict[str, Any]:
    """读取 data/feishu/config.json；不存在时返回默认。"""
    if not CONFIG_PATH.is_file():
        return {
            "reply_display": DEFAULT_REPLY_DISPLAY,
            "card_backend": DEFAULT_CARD_BACKEND,
        }
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "reply_display": DEFAULT_REPLY_DISPLAY,
            "card_backend": DEFAULT_CARD_BACKEND,
        }
    if not isinstance(data, dict):
        return {
            "reply_display": DEFAULT_REPLY_DISPLAY,
            "card_backend": DEFAULT_CARD_BACKEND,
        }
    return {
        "reply_display": _normalize_reply_display(data.get("reply_display")),
        "card_backend": _normalize_card_backend(data.get("card_backend")),
    }


def save_channel_config(config: dict[str, Any]) -> None:
    """写入 data/feishu/config.json。"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "reply_display": _normalize_reply_display(config.get("reply_display")),
        "card_backend": _normalize_card_backend(config.get("card_backend")),
    }
    CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_reply_display() -> str:
    """返回当前最终消息展示模式。"""
    return load_channel_config()["reply_display"]


def keep_process_in_final_message() -> bool:
    """最终飞书消息是否保留 Agent 步骤过程。"""
    return get_reply_display() == REPLY_DISPLAY_WITH_STEPS


def set_reply_display(mode: str) -> str:
    """
    设置 reply_display 并落盘。

    返回中文说明（供 Agent 工具或 API 响应）。
    """
    normalized = _normalize_reply_display(mode)
    save_channel_config({"reply_display": normalized})
    label = _REPLY_DISPLAY_LABELS[normalized]
    return f"已更新飞书最终消息展示为：{label}（{normalized}）"


def get_card_backend() -> str:
    """返回当前卡片后端：classic 或 cardkit。"""
    return load_channel_config()["card_backend"]


def set_card_backend(backend: str) -> str:
    """设置 card_backend 并落盘，返回中文说明。"""
    normalized = _normalize_card_backend(backend)
    current = load_channel_config()
    current["card_backend"] = normalized
    save_channel_config(current)
    label = _CARD_BACKEND_LABELS[normalized]
    return f"已更新飞书卡片后端为：{label}（{normalized}）"


def channel_config_for_api() -> dict[str, Any]:
    """供 GET /api/settings 的 feishu 块附加字段。"""
    mode = get_reply_display()
    backend = get_card_backend()
    return {
        "reply_display": mode,
        "reply_display_label": _REPLY_DISPLAY_LABELS[mode],
        "reply_display_options": [
            {"value": REPLY_DISPLAY_WITH_STEPS, "label": _REPLY_DISPLAY_LABELS[REPLY_DISPLAY_WITH_STEPS]},
            {"value": REPLY_DISPLAY_REPLY_ONLY, "label": _REPLY_DISPLAY_LABELS[REPLY_DISPLAY_REPLY_ONLY]},
        ],
        "card_backend": backend,
        "card_backend_label": _CARD_BACKEND_LABELS[backend],
        "card_backend_options": [
            {"value": CARD_BACKEND_CARDKIT, "label": _CARD_BACKEND_LABELS[CARD_BACKEND_CARDKIT]},
            {"value": CARD_BACKEND_CLASSIC, "label": _CARD_BACKEND_LABELS[CARD_BACKEND_CLASSIC]},
        ],
        "config_path": "data/feishu/config.json",
    }


def apply_channel_config_patch(patch: dict[str, Any] | None) -> None:
    """合并 PATCH（reply_display、card_backend）。"""
    if not patch:
        return
    current = load_channel_config()
    changed = False
    if "reply_display" in patch:
        current["reply_display"] = _normalize_reply_display(patch.get("reply_display"))
        changed = True
    if "card_backend" in patch:
        current["card_backend"] = _normalize_card_backend(patch.get("card_backend"))
        changed = True
    if changed:
        save_channel_config(current)
