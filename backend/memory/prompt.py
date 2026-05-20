"""
System prompt 记忆块：从磁盘快照字符串拼入基础规则（不在 build_system_prompt 内读盘）。
"""

from __future__ import annotations

from . import store

# 记忆块固定在基础规则正文之后：规则优先，记忆块仅补充跨会话偏好与习惯。
_MEMORY_BLOCK_PLACEMENT = "after_base"


def _format_usage_line(label: str, used: int, limit: int, percent: int) -> str:
    """生成单 store 占用率行，如 [USER · 67% — 920/1375 chars]。"""
    return f"[{label} · {percent}% — {used}/{limit} chars]"


def format_memory_block(
    user_body: str,
    memory_body: str,
    *,
    user_usage: dict[str, int] | None = None,
    memory_usage: dict[str, int] | None = None,
) -> str:
    """
    将 USER / MEMORY 正文格式化为记忆块（含标题与占用率行）。

    同输入同输出，无时间戳等可变字段。
    """
    user_u = user_usage if user_usage is not None else store.usage("user")
    mem_u = memory_usage if memory_usage is not None else store.usage("memory")

    sections: list[str] = [
        "## 长期记忆（跨会话）",
        "",
        _format_usage_line(
            "USER",
            user_u["used"],
            user_u["limit"],
            user_u["percent"],
        ),
        user_body.strip() if user_body.strip() else "（无）",
        "",
        _format_usage_line(
            "MEMORY",
            mem_u["used"],
            mem_u["limit"],
            mem_u["percent"],
        ),
        memory_body.strip() if memory_body.strip() else "（无）",
    ]
    return "\n".join(sections)


def build_memory_snapshot() -> str:
    """从磁盘读取双文件并生成会话级记忆快照字符串（Session 启动时调用一次）。"""
    user_body = store.format_for_prompt("user")
    memory_body = store.format_for_prompt("memory")
    if not user_body.strip() and not memory_body.strip():
        return ""
    return format_memory_block(
        user_body,
        memory_body,
        user_usage=store.usage("user"),
        memory_usage=store.usage("memory"),
    )


def build_system_prompt(base: str, memory_snapshot: str | None) -> str:
    """
    将记忆快照拼入 system prompt；memory_snapshot 由调用方传入，本函数不读盘。

    memory_snapshot 为 None 或仅空白时返回 base 原文。
    """
    base_text = base if base is not None else ""
    snapshot = (memory_snapshot or "").strip()
    if not snapshot:
        return base_text

    base_stripped = base_text.rstrip()
    if _MEMORY_BLOCK_PLACEMENT == "after_base":
        return f"{base_stripped}\n\n{snapshot}"
    return f"{snapshot}\n\n{base_stripped}"
