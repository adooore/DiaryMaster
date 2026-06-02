"""飞书 tenant_access_token 获取与按 App ID 缓存。"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from backend.channels.feishu.config import get_feishu_config

_FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
_TOKEN_PATH = "/auth/v3/tenant_access_token/internal"
_REFRESH_MARGIN_SEC = 60

_lock = threading.Lock()
_cached_by_app: dict[str, tuple[str, float]] = {}


class FeishuTokenError(Exception):
    """获取 tenant_access_token 失败。"""


def invalidate_token_cache(app_id: str | None = None) -> None:
    """清空 token 缓存；无 app_id 时清空全部。"""
    with _lock:
        if app_id:
            _cached_by_app.pop(app_id.strip(), None)
        else:
            _cached_by_app.clear()


def get_tenant_access_token(*, agent_id: str | None = None, force_refresh: bool = False) -> str:
    """返回有效的 tenant_access_token；过期前 60 秒自动刷新。"""
    cfg = get_feishu_config(agent_id)
    if not cfg.app_id or not cfg.app_secret:
        raise FeishuTokenError("飞书 App ID 或 App Secret 未配置")

    now = time.time()
    with _lock:
        if not force_refresh and cfg.app_id in _cached_by_app:
            token, expire_at = _cached_by_app[cfg.app_id]
            if token and now < expire_at - _REFRESH_MARGIN_SEC:
                return token

    token, expire = fetch_tenant_access_token(cfg.app_id, cfg.app_secret)
    with _lock:
        _cached_by_app[cfg.app_id] = (token, now + max(expire, 120))
    return token


def fetch_tenant_access_token(app_id: str, app_secret: str) -> tuple[str, int]:
    """用指定凭证换取 tenant_access_token（不写缓存）。"""
    if not app_id or not app_secret:
        raise FeishuTokenError("飞书 App ID 或 App Secret 未配置")

    body = json.dumps(
        {"app_id": app_id, "app_secret": app_secret},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{_FEISHU_API_BASE}{_TOKEN_PATH}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise FeishuTokenError(
            f"飞书 token 请求 HTTP {e.code}：{detail or e.reason}"
        ) from e
    except urllib.error.URLError as e:
        raise FeishuTokenError(f"飞书 token 网络错误：{e.reason}") from e

    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as e:
        raise FeishuTokenError("飞书 token 响应不是合法 JSON") from e

    if data.get("code") != 0:
        raise FeishuTokenError(
            f"飞书 token 失败（code={data.get('code')}）：{data.get('msg') or '未知错误'}"
        )

    token = (data.get("tenant_access_token") or "").strip()
    expire = int(data.get("expire") or 0)
    if not token:
        raise FeishuTokenError("飞书 token 响应缺少 tenant_access_token")
    return token, expire
