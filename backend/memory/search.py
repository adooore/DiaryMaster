"""
跨 Session 历史对话检索：遍历 data/sessions/*.json，对 chat_log 做子串匹配（只读）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.config import APP_ROOT

SESSIONS_DIR = APP_ROOT / "data" / "sessions"

DEFAULT_LIMIT = 5
MAX_LIMIT = 20
SNIPPET_RADIUS = 80


def _normalize_limit(limit: int) -> int:
    """将 limit 限制在 1～MAX_LIMIT。"""
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = DEFAULT_LIMIT
    return max(1, min(n, MAX_LIMIT))


def _iter_session_json() -> list[tuple[Path, dict[str, Any]]]:
    """读取 sessions 目录下全部 JSON，跳过损坏文件。"""
    if not SESSIONS_DIR.is_dir():
        return []
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(SESSIONS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("id"):
            loaded.append((path, data))
    return loaded


def _texts_from_chat_log(chat_log: list[Any]) -> list[str]:
    """从 chat_log 提取可搜索的用户/助手正文。"""
    texts: list[str] = []
    for event in chat_log or []:
        if not isinstance(event, dict) or event.get("type") != "message":
            continue
        role = event.get("role")
        if role not in ("user", "assistant"):
            continue
        text = (event.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def _texts_from_messages(messages: list[Any]) -> list[str]:
    """从 messages 字段提取正文（旧格式或内存序列化时的兜底）。"""
    texts: list[str] = []
    for msg in messages or []:
        if isinstance(msg, dict):
            content = msg.get("content") or msg.get("text") or ""
        else:
            content = getattr(msg, "content", "") or ""
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif isinstance(block, str):
                    parts.append(block)
            content = "".join(parts)
        text = str(content).strip()
        if text:
            texts.append(text)
    return texts


def _collect_searchable_texts(data: dict[str, Any]) -> list[str]:
    """优先 chat_log，否则 messages。"""
    chat_log = data.get("chat_log")
    if chat_log:
        texts = _texts_from_chat_log(chat_log)
        if texts:
            return texts
    return _texts_from_messages(data.get("messages") or [])


def _make_snippet(text: str, query: str, *, max_len: int = SNIPPET_RADIUS * 2 + 40) -> str:
    """在 text 中定位 query，返回带省略号的上下文片段。"""
    q = query.strip()
    if not text:
        return ""
    if not q:
        return text[:max_len] + ("…" if len(text) > max_len else "")
    lower_text = text.lower()
    lower_q = q.lower()
    idx = lower_text.find(lower_q)
    if idx < 0:
        return text[:max_len] + ("…" if len(text) > max_len else "")
    start = max(0, idx - SNIPPET_RADIUS)
    end = min(len(text), idx + len(q) + SNIPPET_RADIUS)
    snippet = text[start:end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def _match_score(texts: list[str], query: str) -> tuple[int, str]:
    """统计子串命中次数，并返回最佳摘要片段。"""
    q = query.strip()
    if not q:
        return 0, ""
    lower_q = q.lower()
    hits = 0
    best_snippet = ""
    for text in texts:
        lower_text = text.lower()
        pos = 0
        while True:
            found = lower_text.find(lower_q, pos)
            if found < 0:
                break
            hits += 1
            pos = found + len(lower_q)
        if hits and not best_snippet:
            best_snippet = _make_snippet(text, q)
    if hits and not best_snippet:
        best_snippet = _make_snippet("\n".join(texts[:3]), q)
    return hits, best_snippet


def search_past_chats(
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    current_session_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    在全部 Session 的持久化 JSON 中搜索 query 子串。

    返回列表项含 session_id、title、created_at、snippet、is_current、match_count。
    """
    q = (query or "").strip()
    if not q:
        return []

    cap = _normalize_limit(limit)
    rows: list[dict[str, Any]] = []

    for _path, data in _iter_session_json():
        sid = str(data.get("id") or "")
        texts = _collect_searchable_texts(data)
        if not texts:
            continue
        match_count, snippet = _match_score(texts, q)
        if match_count <= 0:
            continue
        rows.append(
            {
                "session_id": sid,
                "title": (data.get("title") or sid).strip() or sid,
                "created_at": data.get("created_at") or "",
                "snippet": snippet,
                "is_current": bool(current_session_id and sid == current_session_id),
                "match_count": match_count,
            }
        )

    rows.sort(
        key=lambda r: (r.get("match_count") or 0, r.get("created_at") or ""),
        reverse=True,
    )
    return rows[:cap]


def format_search_results(results: list[dict[str, Any]], query: str) -> str:
    """将检索结果格式化为给模型阅读的中文摘要。"""
    q = (query or "").strip()
    if not q:
        return "请提供非空的 query 关键词。"
    if not results:
        return f"未在历史会话中找到与「{q}」相关的对话片段。"
    lines = [f"共找到 {len(results)} 条相关历史会话（关键词「{q}」）："]
    for i, row in enumerate(results, 1):
        cur = "【当前会话】" if row.get("is_current") else ""
        title = row.get("title") or row.get("session_id")
        when = row.get("created_at") or "（时间未知）"
        sid = row.get("session_id") or ""
        snippet = row.get("snippet") or "（无片段）"
        hits = row.get("match_count") or 0
        lines.append(f"{i}. {title}{cur}")
        lines.append(f"   session_id: {sid}")
        lines.append(f"   时间: {when}；命中约 {hits} 处")
        lines.append(f"   片段: {snippet}")
    lines.append("（只读检索，未切换会话；需继续某次对话请由用户在前端切换 Session。）")
    return "\n".join(lines)


def run_search(query: str, limit: int, current_session_id: str | None) -> str:
    """在历史 Session 中搜索并返回格式化摘要（供 Agent 工具调用）。"""
    results = search_past_chats(
        query,
        limit=limit,
        current_session_id=current_session_id,
    )
    return format_search_results(results, query)
