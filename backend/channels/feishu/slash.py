"""飞书 IM `/` 指令：Session 管理（不调用 Agent）。"""

from __future__ import annotations

from backend.channels.feishu import session_ops

HELP_TEXT = """可用指令：
/help · 本帮助
/sessions · 列出会话（★ 为当前）
/new · 新建会话并切换过去
/switch <序号或id> · 切换会话
/current · 查看当前会话

示例：/switch 2  ·  /switch abc12345"""


def parse_slash_command(text: str) -> tuple[str, str] | None:
    """解析行首 `/` 指令；非指令返回 None。"""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None
    body = raw[1:].strip()
    if not body:
        return "help", ""
    if " " in body:
        cmd, args = body.split(None, 1)
        return cmd.strip().lower(), args.strip()
    return body.lower(), ""


def _normalize_cmd(cmd: str) -> str:
    aliases = {
        "帮助": "help",
        "会话": "sessions",
        "列表": "sessions",
        "新建": "new",
        "切换": "switch",
        "当前": "current",
    }
    return aliases.get(cmd, cmd)


def try_handle_slash_command(
    *,
    text: str,
    agent_id: str,
    open_id: str,
) -> str | None:
    """
    处理飞书 slash 指令。

    返回回复文本表示已处理；返回 None 表示非指令，应走 Agent。
    """
    parsed = parse_slash_command(text)
    if parsed is None:
        return None

    cmd, args = parsed
    cmd = _normalize_cmd(cmd)

    if cmd == "help":
        return HELP_TEXT

    if cmd == "sessions":
        return session_ops.format_sessions_text(open_id=open_id, agent_id=agent_id)

    if cmd == "current":
        return session_ops.format_current_session_text(open_id=open_id, agent_id=agent_id)

    if cmd == "new":
        return session_ops.create_new_session_for_open_id(open_id, agent_id)

    if cmd == "switch":
        if not args:
            return "用法：/switch <序号> 或 /switch <Session id 前缀>"
        try:
            return session_ops.switch_session_for_open_id(open_id, args, agent_id)
        except ValueError as e:
            return str(e)

    return "未知指令，发送 /help 查看帮助。"
