"""
DiaryMaster 记忆子系统：双文件长期记忆、Session 快照、跨 Session 历史检索。

模块划分：
- store：USER.md / MEMORY.md 读写与条目操作
- prompt：记忆块拼装与 build_system_prompt
- snapshot：Session 级冻结快照
- tool / search：Agent 工具业务逻辑
- api：设置页 REST 载荷
- policies：SYSTEM_PROMPT 中的策略文案
"""

from backend.memory import store
from backend.memory.api import memories_payload
from backend.memory.policies import MEMORY_TOOL_POLICY, SEARCH_TOOL_POLICY
from backend.memory.prompt import (
    build_memory_snapshot,
    build_system_prompt,
    format_memory_block,
)
from backend.memory.search import search_past_chats, format_search_results
from backend.memory.snapshot import (
    drop as drop_memory_snapshot,
    effective_system_prompt,
    ensure as ensure_memory_snapshot,
    get as get_memory_snapshot,
    refresh as refresh_memory_snapshot,
)
from backend.memory.tool import run_memory_action

__all__ = [
    "MEMORY_TOOL_POLICY",
    "SEARCH_TOOL_POLICY",
    "MemoryLimitExceeded",
    "MemoryStoreError",
    "build_memory_snapshot",
    "build_system_prompt",
    "drop_memory_snapshot",
    "effective_system_prompt",
    "ensure_memory_snapshot",
    "format_memory_block",
    "format_search_results",
    "get_memory_snapshot",
    "memories_payload",
    "refresh_memory_snapshot",
    "run_memory_action",
    "search_past_chats",
    "store",
]

MemoryStoreError = store.MemoryStoreError
MemoryLimitExceeded = store.MemoryLimitExceeded
