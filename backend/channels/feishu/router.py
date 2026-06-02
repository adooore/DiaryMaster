"""飞书事件订阅 HTTP 路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from backend.channels.feishu.activity import record_webhook_request
from backend.channels.feishu.config import is_enabled, list_feishu_enabled_agent_ids
from backend.channels.feishu.crypto import (
    FeishuCryptoError,
    parse_challenge_response,
    parse_webhook_body,
)
from backend.channels.feishu.dispatch import dispatch_in_background, resolve_agent_id

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/feishu", tags=["feishu"])

# enabled=false 时返回 503，便于运维区分「未配置」与「处理成功」
_DISABLED_STATUS = 503


@router.post("/webhook")
async def feishu_webhook(request: Request) -> Response:
    """
    接收飞书事件推送：challenge 校验、明文事件、异步分发 im.message.receive_v1。

    未启用飞书配置时返回 503（不伪装 200，避免误以为已接入）。
    """
    if not list_feishu_enabled_agent_ids():
        return JSONResponse(
            status_code=_DISABLED_STATUS,
            content={"error": "飞书渠道未配置或未启用"},
        )

    raw_body = await request.body()

    try:
        payload = parse_webhook_body(raw_body)
    except FeishuCryptoError as e:
        _log.warning("飞书 webhook 校验失败: %s", e)
        return JSONResponse(status_code=403, content={"error": str(e)})

    challenge_resp = parse_challenge_response(payload)
    if challenge_resp:
        return JSONResponse(content=challenge_resp)

    agent_id = resolve_agent_id(payload)
    if not agent_id or not is_enabled(agent_id):
        return JSONResponse(
            status_code=_DISABLED_STATUS,
            content={"error": "无法匹配飞书 App ID 到已启用的 Agent"},
        )

    record_webhook_request(payload, agent_id=agent_id)
    dispatch_in_background(payload, agent_id=agent_id)
    return JSONResponse(content={})
