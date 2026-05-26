"""飞书 IM 发消息 Open API 封装。"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from backend.channels.feishu.token import FeishuTokenError, get_tenant_access_token

_FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
_MESSAGES_PATH = "/im/v1/messages"
# 文本消息 content.text 建议分段上限（飞书单条展示约 4k 字符量级）
_TEXT_SEGMENT_CHARS = 4000


class FeishuClientError(Exception):
    """飞书发消息失败。"""


def _format_api_error(data: dict[str, Any], http_code: int | None = None) -> str:
    """将飞书 API 错误转为中文摘要。"""
    code = data.get("code", http_code)
    msg = data.get("msg") or data.get("message") or "未知错误"
    prefix = f"飞书发消息失败（code={code}）" if code is not None else "飞书发消息失败"
    return f"{prefix}：{msg}"


def _post_message(
    receive_id: str,
    receive_id_type: str,
    text: str,
) -> None:
    """调用 im/v1/messages 发送一条文本消息。"""
    token = get_tenant_access_token()
    query = urllib.parse.urlencode({"receive_id_type": receive_id_type})
    url = f"{_FEISHU_API_BASE}{_MESSAGES_PATH}?{query}"
    content = json.dumps({"text": text}, ensure_ascii=False)
    body = json.dumps(
        {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": content,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise FeishuClientError(
                f"飞书发消息 HTTP {e.code}：{raw[:200] or e.reason}"
            ) from e
        raise FeishuClientError(_format_api_error(data, e.code)) from e
    except urllib.error.URLError as e:
        raise FeishuClientError(f"飞书发消息网络错误：{e.reason}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise FeishuClientError("飞书发消息响应不是合法 JSON") from e
    if data.get("code") != 0:
        raise FeishuClientError(_format_api_error(data))


def send_text(
    receive_id: str,
    receive_id_type: str,
    text: str,
) -> None:
    """
    向指定接收方发送文本；超长时按 _TEXT_SEGMENT_CHARS 分段多条发送。

    receive_id_type 常用 open_id 或 chat_id。
    """
    if not (text or "").strip():
        return
    chunks = _split_text(text)
    for i, chunk in enumerate(chunks):
        payload = chunk
        if len(chunks) > 1:
            payload = f"({i + 1}/{len(chunks)})\n{chunk}"
        _post_message(receive_id, receive_id_type, payload)


def _split_text(text: str) -> list[str]:
    """按字符上限切分长文本，尽量在换行处断开。"""
    if len(text) <= _TEXT_SEGMENT_CHARS:
        return [text]
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= _TEXT_SEGMENT_CHARS:
            parts.append(rest)
            break
        cut = rest[:_TEXT_SEGMENT_CHARS]
        nl = cut.rfind("\n")
        if nl > _TEXT_SEGMENT_CHARS // 2:
            segment, rest = rest[: nl + 1], rest[nl + 1 :]
        else:
            segment, rest = rest[:_TEXT_SEGMENT_CHARS], rest[_TEXT_SEGMENT_CHARS:]
        parts.append(segment)
    return parts


def send_text_or_raise(
    receive_id: str,
    receive_id_type: str,
    text: str,
) -> None:
    """send_text 的别名，供 dispatch 区分 token 与 client 异常。"""
    send_text(receive_id, receive_id_type, text)


def user_facing_error(exc: BaseException) -> str:
    """将常见异常转为发给飞书用户的中文提示。"""
    if isinstance(exc, FeishuTokenError):
        return f"飞书鉴权失败：{exc}"
    if isinstance(exc, FeishuClientError):
        return str(exc)
    msg = str(exc).strip() or exc.__class__.__name__
    if "API Key" in msg or "DEEPSEEK" in msg.upper() or "api_key" in msg.lower():
        return "未配置 DeepSeek API Key，请在 DiaryMaster 设置页填写后重试。"
    if "模型" in msg or "model" in msg.lower():
        return f"模型调用失败：{msg}"
    return f"处理消息时出错：{msg}"
