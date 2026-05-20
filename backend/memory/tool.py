"""memory 工具业务逻辑（add/replace/remove），供 agent 层 @tool 包装 UI 步骤。"""

from __future__ import annotations

from . import store


def run_memory_action(
    action: str,
    store_name: str,
    text: str,
    old_text: str,
    new_text: str,
) -> str:
    """执行 memory_store 的 add/replace/remove，返回给模型的简短中文结果。"""
    action_key = (action or "").strip().lower()
    if action_key not in ("add", "replace", "remove"):
        return f"失败：无效的 action {action!r}，应为 add、replace 或 remove"

    try:
        if action_key == "add":
            added = store.add(store_name, text)
            u = store.usage(store_name)
            if added:
                return f"已写入 {store_name} 记忆（占用 {u['percent']}%）"
            return f"未写入：与已有条目重复（占用 {u['percent']}%）"
        if action_key == "replace":
            store.replace(store_name, old_text, new_text)
            u = store.usage(store_name)
            return f"已替换 {store_name} 记忆（占用 {u['percent']}%）"
        store.remove(store_name, old_text)
        u = store.usage(store_name)
        return f"已删除 {store_name} 记忆片段（占用 {u['percent']}%）"
    except store.MemoryLimitExceeded as e:
        return f"失败：{e}"
    except store.MemoryStoreError as e:
        return f"失败：{e}"
