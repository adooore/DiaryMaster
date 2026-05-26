"""飞书配置读写辅助（供 main.py 扩展 GET/PUT /api/settings）。"""

from __future__ import annotations

from typing import Any

from backend.channels.feishu.config import get_feishu_config, is_enabled
from backend.channels.feishu.token import invalidate_token_cache
from backend.user_settings import load_settings, mask_api_key, save_settings

_SECRET_KEYS = ("app_secret",)
_LEGACY_KEYS = ("verification_token", "encrypt_key")


def feishu_settings_status() -> dict[str, Any]:
    """返回 GET /api/settings 中的 feishu 块（无明文密钥）。"""
    cfg = get_feishu_config()
    configured = bool(cfg.app_id and cfg.app_secret)
    return {
        "enabled": is_enabled(),
        "configured": configured,
        "app_id": cfg.app_id,
        "app_secret_masked": mask_api_key(cfg.app_secret) if cfg.app_secret else "",
        "app_secret_configured": bool(cfg.app_secret),
    }


def apply_feishu_settings(
    feishu: dict[str, Any] | None,
    *,
    clear: bool = False,
) -> None:
    """
    将 PUT /api/settings 中的 feishu 对象合并进 user_settings.json。

    - clear=True 或 feishu is None：删除 feishu 键
    - app_secret 留空表示不修改；app_id 非空时覆盖
    """
    data = load_settings()
    if clear or feishu is None:
        data.pop("feishu", None)
        save_settings(data)
        invalidate_token_cache()
        return

    if not isinstance(feishu, dict):
        return

    current = data.get("feishu") or {}
    if not isinstance(current, dict):
        current = {}
    merged = dict(current)

    if "app_id" in feishu:
        merged["app_id"] = (feishu.get("app_id") or "").strip()

    for key in _SECRET_KEYS:
        if key not in feishu:
            continue
        val = (feishu.get(key) or "").strip()
        if val:
            merged[key] = val

    for key in _LEGACY_KEYS:
        merged.pop(key, None)

    if merged:
        data["feishu"] = merged
    else:
        data.pop("feishu", None)
    save_settings(data)
    invalidate_token_cache()
