"""长期记忆 REST API 载荷（供 main.py 路由调用）。"""

from __future__ import annotations

from . import store


def memories_payload() -> dict:
    """组装 USER / MEMORY 原文与 usage，供 GET/PUT /api/memories 响应。"""
    return {
        "user": {"content": store.read_content("user"), "usage": store.usage("user")},
        "memory": {
            "content": store.read_content("memory"),
            "usage": store.usage("memory"),
        },
    }
