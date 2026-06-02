"""
长期记忆双文件存储：USER.md / MEMORY.md（§ 分隔条目，存于 data/memories/）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from backend.config import APP_ROOT

USER_LIMIT = 1375
MEMORY_LIMIT = 2200

ENTRY_SEP = "§"

StoreName = Literal["user", "memory"]

_STORE_FILES: dict[StoreName, str] = {
    "user": "USER.md",
    "memory": "MEMORY.md",
}
_STORE_LIMITS: dict[StoreName, int] = {
    "user": USER_LIMIT,
    "memory": MEMORY_LIMIT,
}


class MemoryStoreError(Exception):
    """记忆读写或条目操作失败。"""


class MemoryLimitExceeded(MemoryStoreError):
    """写入后超过该 store 的字符上限。"""


def _memories_dir(agent_id: str | None = None) -> Path:
    """返回指定 Agent 的记忆目录。"""
    from backend.agents.context import get_active_agent_id
    from backend.agents.registry import agent_registry

    aid = (agent_id or "").strip() or get_active_agent_id()
    return agent_registry.memories_dir(aid)


def _ensure_dir(agent_id: str | None = None) -> None:
    """确保当前 Agent 的 memories 目录存在。"""
    _memories_dir(agent_id).mkdir(parents=True, exist_ok=True)


def _normalize_store(store: str) -> StoreName:
    """校验 store 名称并返回字面量类型。"""
    key = (store or "").strip().lower()
    if key not in _STORE_FILES:
        raise MemoryStoreError(f"无效的 store：{store!r}，应为 user 或 memory")
    return key  # type: ignore[return-value]


def _path_for_store(store: str, agent_id: str | None = None) -> Path:
    """返回指定 store 对应的 Markdown 文件路径。"""
    name = _normalize_store(store)
    return _memories_dir(agent_id) / _STORE_FILES[name]


def _limit_for_store(store: str) -> int:
    """返回指定 store 的字符上限。"""
    return _STORE_LIMITS[_normalize_store(store)]


def _read_raw(store: str) -> str:
    """读取 store 文件全文；不存在时返回空字符串。"""
    path = _path_for_store(store)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _write_raw(store: str, content: str, agent_id: str | None = None) -> None:
    """将全文写入 store 文件（自动创建目录与空文件）。"""
    _ensure_dir(agent_id)
    _path_for_store(store, agent_id).write_text(content, encoding="utf-8")


def _parse_entries(content: str) -> list[str]:
    """按 § 解析条目，去掉首尾空白并丢弃空段。"""
    if not content:
        return []
    return [part.strip() for part in content.split(ENTRY_SEP) if part.strip()]


def _serialize_entries(entries: list[str]) -> str:
    """将条目列表序列化为磁盘格式（§ 连接）。"""
    cleaned = [e.strip() for e in entries if e.strip()]
    return ENTRY_SEP.join(cleaned)


def read_content(store: str) -> str:
    """读取 store 的磁盘正文（供快照或 API 使用）。"""
    return _read_raw(store)


def write_content(store: str, content: str) -> None:
    """将全文写入 store（供 API 手工编辑），写入前校验字符上限。"""
    text = content if content is not None else ""
    _check_limit(store, text)
    _write_raw(store, text)


def list_entries(store: str) -> list[str]:
    """返回 store 中全部记忆条目（已解析、去空）。"""
    return _parse_entries(_read_raw(store))


def format_for_prompt(store: str) -> str:
    """格式化为可注入 system prompt 的正文（§ 连接，无条目时为空串）。"""
    return _serialize_entries(list_entries(store))


def usage(store: str) -> dict[str, int]:
    """返回 used、limit、percent（字符占用，供 prompt 占用率展示）。"""
    limit = _limit_for_store(store)
    used = len(_read_raw(store))
    percent = round(used / limit * 100) if limit > 0 else 0
    return {"used": used, "limit": limit, "percent": percent}


def _check_limit(store: str, content: str) -> None:
    """写入前校验字符上限。"""
    limit = _limit_for_store(store)
    if len(content) > limit:
        raise MemoryLimitExceeded(
            f"{store} 记忆已达上限（{len(content)}/{limit} 字符）"
        )


def _require_unique_substring(content: str, needle: str, action: str) -> None:
    """要求 needle 在 content 中恰好出现一次，否则抛错。"""
    if not needle:
        raise MemoryStoreError(f"{action} 需要非空的匹配文本")
    count = content.count(needle)
    if count == 0:
        raise MemoryStoreError(f"{action} 失败：未找到匹配内容")
    if count > 1:
        raise MemoryStoreError(f"{action} 失败：匹配内容出现 {count} 次，需唯一")


def add(store: str, text: str) -> bool:
    """
    追加一条记忆；与已有条目完全相同则去重跳过。

    返回 True 表示已写入，False 表示去重未写入。
    """
    entry = (text or "").strip()
    if not entry:
        raise MemoryStoreError("add 需要非空 text")

    entries = list_entries(store)
    if entry in entries:
        return False

    entries.append(entry)
    new_content = _serialize_entries(entries)
    _check_limit(store, new_content)
    _write_raw(store, new_content)
    return True


def replace(store: str, old_text: str, new_text: str) -> None:
    """将正文中唯一匹配的 old_text 替换为 new_text（new_text 可为空以清空片段）。"""
    old = old_text if old_text is not None else ""
    new = new_text if new_text is not None else ""
    content = _read_raw(store)
    _require_unique_substring(content, old, "replace")
    new_content = content.replace(old, new, 1)
    _check_limit(store, new_content)
    _write_raw(store, new_content)


def remove(store: str, old_text: str) -> None:
    """从正文中删除唯一匹配的 old_text 子串。"""
    old = old_text if old_text is not None else ""
    content = _read_raw(store)
    _require_unique_substring(content, old, "remove")
    new_content = content.replace(old, "", 1)
    normalized = _serialize_entries(_parse_entries(new_content))
    _check_limit(store, normalized)
    _write_raw(store, normalized)
