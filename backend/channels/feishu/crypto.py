"""飞书事件订阅：URL challenge 与明文 JSON 解析。"""

from __future__ import annotations

import json
from typing import Any


class FeishuCryptoError(Exception):
    """请求体解析失败。"""


def parse_challenge_response(payload: dict[str, Any]) -> dict[str, str] | None:
    """
    若 payload 为 URL 校验，返回 {"challenge": "..."} 供 HTTP 响应；否则 None。

    支持明文 type=url_verification 或仅含 challenge 字段的校验包。
    """
    if payload.get("type") == "url_verification":
        ch = payload.get("challenge")
        if isinstance(ch, str) and ch:
            return {"challenge": ch}
    ch = payload.get("challenge")
    if isinstance(ch, str) and ch and "encrypt" not in payload:
        return {"challenge": ch}
    return None


def parse_webhook_body(raw_body: bytes) -> dict[str, Any]:
    """解析飞书 POST 明文 JSON body；加密事件需在飞书后台关闭「加密」。"""
    text = raw_body.decode("utf-8")
    try:
        payload: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as e:
        raise FeishuCryptoError("请求体不是合法 JSON") from e

    if payload.get("encrypt"):
        raise FeishuCryptoError(
            "收到加密事件：请在飞书开放平台 → 事件订阅 中关闭「加密」，或联系开发者"
        )
    return payload
