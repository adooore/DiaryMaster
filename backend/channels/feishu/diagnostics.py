"""飞书渠道连通性检测（设置页「检测」按钮）。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Literal

from backend.channels.feishu.activity import get_activity_status
from backend.channels.feishu.config import FeishuConfig, get_feishu_config, is_enabled
from backend.channels.feishu.token import FeishuTokenError, fetch_tenant_access_token
from backend.channels.feishu.ws_client import get_ws_client_status
from backend.config import HOST, PORT, get_api_key

CheckStatus = Literal["ok", "warn", "fail", "skip"]

_WEBHOOK_PATH = "/channels/feishu/webhook"
_CHALLENGE_BODY = json.dumps(
    {"type": "url_verification", "challenge": "diarymaster-diag"},
    ensure_ascii=False,
).encode("utf-8")


def _check(
    check_id: str,
    label: str,
    status: CheckStatus,
    detail: str,
    *,
    hint: str = "",
) -> dict[str, str]:
    """构造单项检测结果。"""
    item: dict[str, str] = {
        "id": check_id,
        "label": label,
        "status": status,
        "detail": detail,
    }
    if hint:
        item["hint"] = hint
    return item


def _resolve_credentials(override: dict[str, Any] | None) -> FeishuConfig:
    """合并磁盘/环境变量配置与检测请求中的临时凭证。"""
    cfg = get_feishu_config()
    if not override:
        return cfg
    app_id = (override.get("app_id") or cfg.app_id or "").strip()
    app_secret = (override.get("app_secret") or cfg.app_secret or "").strip()
    return FeishuConfig(app_id=app_id, app_secret=app_secret)


def _config_source_notes() -> list[dict[str, str]]:
    """若凭证来自环境变量，追加说明项。"""
    items: list[dict[str, str]] = []
    if os.environ.get("FEISHU_APP_ID", "").strip():
        items.append(
            _check(
                "env_app_id",
                "环境变量覆盖",
                "ok",
                "FEISHU_APP_ID 已设置，优先于设置页磁盘值",
            )
        )
    if os.environ.get("FEISHU_APP_SECRET", "").strip():
        items.append(
            _check(
                "env_app_secret",
                "环境变量覆盖",
                "ok",
                "FEISHU_APP_SECRET 已设置，优先于设置页磁盘值",
            )
        )
    return items


def _probe_webhook_local() -> dict[str, str]:
    """对本机 webhook 发 challenge，验证路由与明文解析。"""
    host = "127.0.0.1" if HOST in ("0.0.0.0", "::") else HOST
    if host in ("::", "[::]"):
        host = "127.0.0.1"
    url = f"http://{host}:{PORT}{_WEBHOOK_PATH}"
    req = urllib.request.Request(
        url,
        data=_CHALLENGE_BODY,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8")
            code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
        raw = e.read().decode("utf-8", errors="replace")
        if code == 503:
            return _check(
                "webhook_local",
                "本机 Webhook",
                "fail",
                "POST /channels/feishu/webhook 返回 503：飞书凭证未启用",
                hint="请确认 App ID 与 App Secret 已保存，或检测前先在表单填写 Secret",
            )
        return _check(
            "webhook_local",
            "本机 Webhook",
            "fail",
            f"HTTP {code}：{raw[:160] or '无响应体'}",
            hint="确认 python run.py 正在运行且端口与 DIARYMASTER_PORT 一致",
        )
    except urllib.error.URLError as e:
        return _check(
            "webhook_local",
            "本机 Webhook",
            "fail",
            f"无法连接 {url}：{e.reason}",
            hint="请先启动 DiaryMaster（python run.py）",
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _check(
            "webhook_local",
            "本机 Webhook",
            "fail",
            f"响应不是 JSON（HTTP {code}）",
        )

    if data.get("challenge") == "diarymaster-diag":
        return _check(
            "webhook_local",
            "本机 Webhook",
            "ok",
            f"challenge 校验通过（{url}）",
        )
    return _check(
        "webhook_local",
        "本机 Webhook",
        "fail",
        f"响应异常（HTTP {code}）：{raw[:160]}",
    )


def run_feishu_diagnostics(
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    执行飞书渠道检测，返回分项结果与汇总。

    override 可传入设置页表单中的 app_id / app_secret（未保存时用于试连）。
    """
    checks: list[dict[str, str]] = []
    cfg = _resolve_credentials(override)

    if not cfg.app_id:
        checks.append(
            _check(
                "app_id",
                "App ID",
                "fail",
                "未配置",
                hint="在设置页填写 App ID 并保存，或在检测前填入表单",
            )
        )
    else:
        checks.append(
            _check("app_id", "App ID", "ok", f"已配置（{cfg.app_id[:8]}…）")
        )

    if not cfg.app_secret:
        checks.append(
            _check(
                "app_secret",
                "App Secret",
                "fail",
                "未配置",
                hint="填写 App Secret 并保存；若已保存过，检测时可留空 Secret",
            )
        )
    else:
        checks.append(_check("app_secret", "App Secret", "ok", "已配置"))

    if cfg.app_id and cfg.app_secret and not is_enabled():
        checks.append(
            _check(
                "saved_config",
                "已保存配置",
                "warn",
                "凭证尚未写入本机或 Secret 未保存",
                hint="填写 App Secret 后请先点「保存」，否则 Webhook 仍会返回 503",
            )
        )

    checks.extend(_config_source_notes())

    if cfg.app_id and cfg.app_secret:
        try:
            token, expire = fetch_tenant_access_token(cfg.app_id, cfg.app_secret)
            prefix = token[:12] + "…" if len(token) > 12 else token
            checks.append(
                _check(
                    "tenant_token",
                    "飞书 Token",
                    "ok",
                    f"获取成功（{prefix}，有效期约 {expire}s）",
                )
            )
        except FeishuTokenError as e:
            checks.append(
                _check(
                    "tenant_token",
                    "飞书 Token",
                    "fail",
                    str(e),
                    hint="核对 App ID / Secret 是否与飞书开放平台一致，应用是否已发布",
                )
            )
    else:
        checks.append(
            _check(
                "tenant_token",
                "飞书 Token",
                "skip",
                "凭证不完整，跳过",
            )
        )

    if is_enabled() or (cfg.app_id and cfg.app_secret):
        checks.append(_probe_webhook_local())
    else:
        checks.append(
            _check(
                "webhook_local",
                "本机 Webhook",
                "skip",
                "凭证未齐全，跳过",
            )
        )

    activity = get_activity_status()
    ws = get_ws_client_status()
    total = activity.get("total_requests") or 0
    age = activity.get("last_age_sec")

    if is_enabled():
        ws_alive = ws.get("thread_alive")
        ws_status = ws.get("status") or "stopped"
        ws_detail = ws.get("detail") or ""
        if ws_alive:
            if ws_status == "connected" or total > 0:
                ws_check_status: CheckStatus = "ok"
                ws_msg = "长连接线程运行中"
                if ws_detail:
                    ws_msg += f"（{ws_detail}）"
            elif ws_status == "connecting":
                ws_check_status = "warn"
                ws_msg = "正在连接飞书，请稍候再检测"
            else:
                ws_check_status = "warn"
                ws_msg = f"线程运行中，状态 {ws_status}"
            checks.append(
                _check("ws_client", "飞书长连接", ws_check_status, ws_msg)
            )
        else:
            checks.append(
                _check(
                    "ws_client",
                    "飞书长连接",
                    "fail",
                    "未启动（需重启 python run.py）",
                    hint="确认已 pip install lark-oapi；飞书后台选「使用长连接接收事件」",
                )
            )

    if total == 0:
        hint_ws = (
            "飞书后台 → 事件与回调 → 选「使用长连接接收事件」并保存（保存时本应用须在运行）；"
            "然后私聊发 hi 再检测"
        )
        hint_hook = (
            f"或使用 Webhook：HTTPS 隧道 + 请求网址 https://<隧道>{_WEBHOOK_PATH}，"
            "订阅 im.message.receive_v1"
        )
        if ws.get("thread_alive"):
            checks.append(
                _check(
                    "inbound_events",
                    "飞书消息到达",
                    "warn",
                    "尚未收到任何消息事件",
                    hint=hint_ws,
                )
            )
        else:
            checks.append(
                _check(
                    "inbound_events",
                    "飞书消息到达",
                    "fail",
                    "从未收到飞书事件",
                    hint=f"{hint_ws}；{hint_hook}",
                )
            )
    elif age is not None and age > 300:
        checks.append(
            _check(
                "inbound_events",
                "飞书消息到达",
                "warn",
                f"曾收到 {total} 次事件，最近一条约 {age // 60} 分钟前",
                hint="若刚发消息仍无记录，检查长连接是否在线或 Webhook URL 是否正确",
            )
        )
    else:
        detail = f"已收到 {total} 次推送"
        if activity.get("last_event_type"):
            detail += f"，最近事件 {activity['last_event_type']}"
        if activity.get("last_dispatch_status"):
            detail += f"，处理 {activity['last_dispatch_status']}"
        if activity.get("last_dispatch_detail"):
            detail += f"（{activity['last_dispatch_detail']}）"
        st: CheckStatus = "ok"
        if activity.get("last_dispatch_status") == "skip":
            st = "warn"
        elif activity.get("last_dispatch_status") not in ("ok", "challenge", ""):
            st = "warn"
        checks.append(_check("inbound_events", "飞书消息到达", st, detail))

    if get_api_key():
        checks.append(
            _check(
                "deepseek_api_key",
                "DeepSeek API Key",
                "ok",
                "已配置（飞书回复需调用模型）",
            )
        )
    else:
        checks.append(
            _check(
                "deepseek_api_key",
                "DeepSeek API Key",
                "warn",
                "未配置",
                hint="飞书能收到消息但 Agent 无法回复，请在设置页填写 API Key",
            )
        )

    if ws.get("thread_alive"):
        checks.append(
            _check(
                "event_mode",
                "事件订阅方式",
                "ok",
                "推荐：飞书后台已配置为「使用长连接接收事件」",
                hint="保存订阅方式前须先启动本应用，且控制台出现 connected to wss://…",
            )
        )
    else:
        checks.append(
            _check(
                "event_mode",
                "事件订阅方式",
                "warn",
                "长连接未运行；若使用 Webhook 模式需 HTTPS 隧道",
                hint=(
                    f"长连接：启动 run.py → 飞书后台选「使用长连接接收事件」；"
                    f"Webhook：请求网址 https://<隧道>{_WEBHOOK_PATH}"
                ),
            )
        )

    if not ws.get("thread_alive"):
        checks.append(
            _check(
                "tunnel",
                "HTTPS 隧道（仅 Webhook 模式）",
                "warn",
                "长连接未启用时，需 ngrok 等隧道转发公网",
                hint=f"隧道应转发到 127.0.0.1:{PORT}",
            )
        )

    failed = sum(1 for c in checks if c["status"] == "fail")
    warned = sum(1 for c in checks if c["status"] == "warn")
    if failed:
        overall: CheckStatus = "fail"
        summary = f"{failed} 项未通过，请先修复后再在飞书私聊测试"
    elif warned:
        overall = "warn"
        summary = "凭证与本机路由正常，请核对飞书事件订阅与 HTTPS 隧道"
    else:
        overall = "ok"
        summary = "检测通过，可在飞书私聊发消息测试"

    return {
        "ok": overall == "ok",
        "overall": overall,
        "summary": summary,
        "webhook_path": _WEBHOOK_PATH,
        "activity": activity,
        "ws": ws,
        "checks": checks,
    }
