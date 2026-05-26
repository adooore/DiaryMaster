"""飞书机器人配置：环境变量覆盖 user_settings.json 中的 feishu 对象。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from backend.user_settings import load_settings

_ENV_APP_ID = "FEISHU_APP_ID"
_ENV_APP_SECRET = "FEISHU_APP_SECRET"


@dataclass(frozen=True)
class FeishuConfig:
    """飞书应用凭证（App ID + App Secret 即可启用）。"""

    app_id: str
    app_secret: str


def _env_or_disk(key_env: str, disk_key: str, feishu_disk: dict[str, Any]) -> str:
    """环境变量非空时优先，否则读磁盘 feishu 对象字段。"""
    env_val = os.environ.get(key_env, "").strip()
    if env_val:
        return env_val
    return (feishu_disk.get(disk_key) or "").strip()


def get_feishu_config() -> FeishuConfig:
    """合并环境变量与 user_settings.json，返回飞书配置。"""
    feishu_disk = load_settings().get("feishu") or {}
    if not isinstance(feishu_disk, dict):
        feishu_disk = {}
    return FeishuConfig(
        app_id=_env_or_disk(_ENV_APP_ID, "app_id", feishu_disk),
        app_secret=_env_or_disk(_ENV_APP_SECRET, "app_secret", feishu_disk),
    )


def is_enabled() -> bool:
    """App ID 与 App Secret 均已配置时视为已启用。"""
    cfg = get_feishu_config()
    return bool(cfg.app_id and cfg.app_secret)
