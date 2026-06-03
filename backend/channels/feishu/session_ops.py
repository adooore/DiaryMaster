"""飞书 / Web 共用的 Session 操作（list / new / switch / current）。"""

from __future__ import annotations

from backend.memory import ensure_memory_snapshot, refresh_memory_snapshot
from backend.session_store import Session, store

from backend.channels.feishu.bind import (
    create_and_bind_session,
    get_active_session_id,
    set_active_session,
)


def _session_title(session: Session | dict) -> str:
    if isinstance(session, dict):
        return (session.get("title") or session.get("id") or "").strip() or "新对话"
    return (session.title or session.id or "").strip() or "新对话"


def _resolve_session_id(token: str) -> str:
    """按完整 id、前缀或列表序号（1-based）解析 Session id。"""
    needle = (token or "").strip()
    if not needle:
        raise ValueError("请提供 Session id 或序号，例如 /switch 2")

    sessions = store.list_sessions()
    if needle.isdigit():
        idx = int(needle)
        if idx < 1 or idx > len(sessions):
            raise ValueError(f"序号无效：{idx}（共 {len(sessions)} 个会话）")
        return sessions[idx - 1]["id"]

    try:
        return store.get_session_by_id(needle).id
    except ValueError:
        pass

    matches = [s["id"] for s in sessions if s["id"].startswith(needle)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"前缀「{needle}」匹配到多个 Session，请写更完整的 id")
    raise ValueError(f"找不到 Session：{needle}")


def format_sessions_text(
    *,
    open_id: str | None = None,
    agent_id: str | None = None,
    limit: int = 15,
) -> str:
    """格式化 Session 列表（飞书 /sessions）。"""
    sessions = store.list_sessions()
    bound_id = get_active_session_id(open_id, agent_id) if open_id else store.active_id
    if not sessions:
        return "暂无会话。发送 /new 新建。"

    lines: list[str] = []
    for index, item in enumerate(sessions[:limit], start=1):
        sid = item.get("id") or ""
        title = item.get("title") or sid
        turn = item.get("turn") or 0
        active = sid == bound_id or (bound_id is None and item.get("is_active"))
        mark = "★" if active else " "
        lines.append(f"{mark} [{index}] {sid} | {title} | turn={turn}")

    total = len(sessions)
    if total > limit:
        lines.append(f"… 共 {total} 个会话（仅展示前 {limit} 个）")
    else:
        lines.append(f"共 {total} 个会话")

    lines.append("切换：/switch 2 或 /switch <id前缀>")
    return "\n".join(lines)


def format_current_session_text(
    *,
    open_id: str | None = None,
    agent_id: str | None = None,
) -> str:
    """当前 Session 摘要（飞书 /current）。"""
    bound_id = get_active_session_id(open_id, agent_id) if open_id else None
    if bound_id:
        try:
            session = store.get_session_by_id(bound_id)
        except ValueError:
            session = store.get_session()
    else:
        session = store.get_session()

    title = _session_title(session)
    return (
        f"当前会话：{session.id}\n"
        f"标题：{title}\n"
        f"轮次：{session.turn}"
    )


def create_new_session_for_open_id(open_id: str, agent_id: str | None = None) -> str:
    """新建 Session 并绑定飞书用户（/new）。"""
    session = create_and_bind_session(open_id, agent_id)
    title = _session_title(session)
    return (
        f"已新建会话：{session.id} | {title}\n"
        f"下一条消息将在此会话中继续。"
    )


def switch_session_for_open_id(
    open_id: str,
    target: str,
    agent_id: str | None = None,
) -> str:
    """切换飞书用户绑定 Session（/switch）。"""
    sid = _resolve_session_id(target)
    set_active_session(open_id, sid, agent_id)
    ensure_memory_snapshot(sid)
    session = store.get_session_by_id(sid)
    return f"已切换到：{session.id} | {_session_title(session)} | turn={session.turn}"


def create_new_session_web() -> str:
    """Web / 无 open_id 时新建 Session。"""
    session = store.new_session()
    refresh_memory_snapshot(session.id)
    return (
        f"已新建会话：{session.id} | {_session_title(session)}\n"
        f"下一条消息将在此会话中继续。"
    )


def switch_session_web(target: str) -> str:
    """Web / 无 open_id 时切换 Session。"""
    sid = _resolve_session_id(target)
    store.switch_session(sid)
    ensure_memory_snapshot(sid)
    session = store.get_session_by_id(sid)
    return f"已切换到：{session.id} | {_session_title(session)} | turn={session.turn}"
