"""飞书 CardKit v1 卡片实体 API（cardkit:card:write）。"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from backend.channels.feishu.token import get_tenant_access_token

_FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
_CARDKIT_PATH = "/cardkit/v1/cards"
_MESSAGES_PATH = "/im/v1/messages"


class FeishuCardKitError(Exception):
    """CardKit 卡片实体操作失败。"""


def _format_api_error(data: dict[str, Any], http_code: int | None = None) -> str:
    """将飞书 API 错误转为中文摘要。"""
    code = data.get("code", http_code)
    msg = data.get("msg") or data.get("message") or "未知错误"
    prefix = f"飞书 CardKit 失败（code={code}）" if code is not None else "飞书 CardKit 失败"
    return f"{prefix}：{msg}"


def _request_json(url: str, *, method: str, body: bytes | None = None) -> dict[str, Any]:
    """发起带 tenant token 的 JSON 请求并返回解析后的响应 dict。"""
    token = get_tenant_access_token()
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise FeishuCardKitError(
                f"飞书 CardKit HTTP {e.code}：{raw[:200] or e.reason}"
            ) from e
        raise FeishuCardKitError(_format_api_error(data, e.code)) from e
    except urllib.error.URLError as e:
        raise FeishuCardKitError(f"飞书 CardKit 网络错误：{e.reason}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise FeishuCardKitError("飞书 CardKit 响应不是合法 JSON") from e
    if data.get("code") != 0:
        raise FeishuCardKitError(_format_api_error(data))
    return data


def create_card_entity(card_json: dict[str, Any]) -> str:
    """基于卡片 JSON 2.0 创建卡片实体并返回 card_id。"""
    payload = {
        "type": "card_json",
        "data": json.dumps(card_json, ensure_ascii=False),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{_FEISHU_API_BASE}{_CARDKIT_PATH}"
    data = _request_json(url, method="POST", body=body)
    card_id = ((data.get("data") or {}).get("card_id") or "").strip()
    if not card_id:
        raise FeishuCardKitError("创建卡片实体响应缺少 card_id")
    return card_id


def send_card_entity(
    receive_id: str,
    receive_id_type: str,
    card_id: str,
) -> str:
    """通过 card_id 发送卡片实体并返回 message_id。"""
    query = urllib.parse.urlencode({"receive_id_type": receive_id_type})
    url = f"{_FEISHU_API_BASE}{_MESSAGES_PATH}?{query}"
    content = json.dumps({"type": "card", "data": {"card_id": card_id}}, ensure_ascii=False)
    body = json.dumps(
        {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": content,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    data = _request_json(url, method="POST", body=body)
    message_id = ((data.get("data") or {}).get("message_id") or "").strip()
    if not message_id:
        raise FeishuCardKitError("发送卡片实体响应缺少 message_id")
    return message_id


def stream_update_element(
    card_id: str,
    element_id: str,
    content: str,
    sequence: int,
) -> None:
    """流式更新卡片 markdown/plain_text 元素的全量文本。"""
    if not (content or "").strip():
        raise FeishuCardKitError("流式更新内容为空")
    path = (
        f"{_CARDKIT_PATH}/{urllib.parse.quote(card_id, safe='')}"
        f"/elements/{urllib.parse.quote(element_id, safe='')}/content"
    )
    url = f"{_FEISHU_API_BASE}{path}"
    body = json.dumps(
        {"content": content, "sequence": sequence},
        ensure_ascii=False,
    ).encode("utf-8")
    _request_json(url, method="PUT", body=body)


def batch_update_card(
    card_id: str,
    sequence: int,
    actions: list[dict[str, Any]],
) -> None:
    """局部更新卡片实体（配置、组件等）。"""
    path = f"{_CARDKIT_PATH}/{urllib.parse.quote(card_id, safe='')}/batch_update"
    url = f"{_FEISHU_API_BASE}{path}"
    body = json.dumps(
        {
            "sequence": sequence,
            "actions": json.dumps(actions, ensure_ascii=False),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    _request_json(url, method="POST", body=body)


def update_card_entity(
    card_id: str,
    card_json: dict[str, Any],
    sequence: int,
) -> None:
    """全量更新卡片实体（含 header 主题色、正文、config）。"""
    path = f"{_CARDKIT_PATH}/{urllib.parse.quote(card_id, safe='')}"
    url = f"{_FEISHU_API_BASE}{path}"
    body = json.dumps(
        {
            "card": {
                "type": "card_json",
                "data": json.dumps(card_json, ensure_ascii=False),
            },
            "sequence": sequence,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    _request_json(url, method="PUT", body=body)


def update_card_entity(
    card_id: str,
    card_json: dict[str, Any],
    sequence: int,
) -> None:
    """全量更新卡片实体（含 header 主题色、正文、config）。"""
    path = f"{_CARDKIT_PATH}/{urllib.parse.quote(card_id, safe='')}"
    url = f"{_FEISHU_API_BASE}{path}"
    body = json.dumps(
        {
            "card": {
                "type": "card_json",
                "data": json.dumps(card_json, ensure_ascii=False),
            },
            "sequence": sequence,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    _request_json(url, method="PUT", body=body)
