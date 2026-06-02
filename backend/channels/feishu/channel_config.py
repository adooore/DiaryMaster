"""飞书渠道行为配置（data/agents/{id}/feishu/config.json，与凭证分离）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def _config_path(agent_id: str | None = None) -> Path:
    """返回指定 Agent 的飞书 config.json 路径。"""
    from backend.agents.context import get_active_agent_id
    from backend.agents.registry import agent_registry

    aid = (agent_id or "").strip() or get_active_agent_id()
    return agent_registry.feishu_dir(aid) / "config.json"


def load_channel_config(agent_id: str | None = None) -> dict[str, Any]:
    """读取 Agent 的飞书 config.json；不存在时返回默认。"""
    path = _config_path(agent_id)
    if not path.is_file():
        return {
            "reply_display": DEFAULT_REPLY_DISPLAY,
            "card_backend": DEFAULT_CARD_BACKEND,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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


def save_channel_config(config: dict[str, Any], agent_id: str | None = None) -> None:
    """写入 Agent 的飞书 config.json。"""
    path = _config_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "reply_display": _normalize_reply_display(config.get("reply_display")),
        "card_backend": _normalize_card_backend(config.get("card_backend")),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_reply_display(agent_id: str | None = None) -> str:
    """返回当前 Agent 的最终消息展示模式。"""
    return load_channel_config(agent_id)["reply_display"]


def keep_process_in_final_message(agent_id: str | None = None) -> bool:
    """最终飞书消息是否保留 Agent 步骤过程。"""
    return get_reply_display(agent_id) == REPLY_DISPLAY_WITH_STEPS


def set_reply_display(mode: str, agent_id: str | None = None) -> str:
    """设置 reply_display 并落盘，返回中文说明。"""
    normalized = _normalize_reply_display(mode)
    save_channel_config({"reply_display": normalized}, agent_id)
    label = _REPLY_DISPLAY_LABELS[normalized]
    return f"已更新飞书最终消息展示为：{label}（{normalized}）"


def get_card_backend(agent_id: str | None = None) -> str:
    """返回当前 Agent 的卡片后端。"""
    return load_channel_config(agent_id)["card_backend"]


def set_card_backend(backend: str, agent_id: str | None = None) -> str:
    """设置 card_backend 并落盘，返回中文说明。"""
    normalized = _normalize_card_backend(backend)
    current = load_channel_config(agent_id)
    current["card_backend"] = normalized
    save_channel_config(current, agent_id)
    label = _CARD_BACKEND_LABELS[normalized]
    return f"已更新飞书卡片后端为：{label}（{normalized}）"


def channel_config_for_api(agent_id: str | None = None) -> dict[str, Any]:
    """供 Agent API 返回的飞书行为配置块。"""
    from backend.agents.context import get_active_agent_id

    aid = agent_id or get_active_agent_id()
    mode = get_reply_display(aid)
    backend = get_card_backend(aid)
    rel = f"data/agents/{aid}/feishu/config.json"
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
        "config_path": rel,
    }


def apply_channel_config_patch(patch: dict[str, Any] | None, agent_id: str | None = None) -> None:
    """合并 PATCH（reply_display、card_backend）到指定 Agent。"""
    if not patch:
        return
    current = load_channel_config(agent_id)
    changed = False
    if "reply_display" in patch:
        current["reply_display"] = _normalize_reply_display(patch.get("reply_display"))
        changed = True
    if "card_backend" in patch:
        current["card_backend"] = _normalize_card_backend(patch.get("card_backend"))
        changed = True
    if changed:
        save_channel_config(current, agent_id)
