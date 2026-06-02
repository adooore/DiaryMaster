"""应用路径、监听地址与 DeepSeek API Key 的读取/保存。"""

from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = APP_ROOT / "workspace"
WEB_DIR = APP_ROOT / "web"

ENV_API_KEY = "DEEPSEEK_API_KEY"
# 进程启动时继承的系统 DEEPSEEK_API_KEY（settings 覆盖前的快照，供无本机设置时回退）
_SYSTEM_API_KEY_FALLBACK = os.environ.get(ENV_API_KEY, "").strip()
HOST = os.environ.get("DIARYMASTER_HOST", "127.0.0.1")
PORT = int(os.environ.get("DIARYMASTER_PORT", "8765"))


def _disk_api_key() -> str:
    """从 data/user_settings.json 读取 DeepSeek API Key。"""
    from backend.user_settings import load_settings

    return (load_settings().get("deepseek_api_key") or "").strip()


def sync_api_key_to_env(agent_id: str | None = None) -> None:
    """
    同步 API Key 到进程环境变量：优先 Agent 级 Key，否则 user_settings / 系统环境。
    """
    from backend.agents.registry import agent_registry

    aid = (agent_id or "").strip() or agent_registry.active_agent_id
    agent_key = agent_registry.get_api_key(aid)
    if agent_key:
        os.environ[ENV_API_KEY] = agent_key
        return

    disk = _disk_api_key()
    if disk:
        os.environ[ENV_API_KEY] = disk
    elif _SYSTEM_API_KEY_FALLBACK:
        os.environ[ENV_API_KEY] = _SYSTEM_API_KEY_FALLBACK
    else:
        os.environ.pop(ENV_API_KEY, None)


def sync_api_key_for_agent(agent_id: str) -> None:
    """切换 Agent 后同步其 API Key 到环境变量。"""
    sync_api_key_to_env(agent_id)


def bootstrap_api_key_from_disk() -> None:
    """应用启动时同步 active Agent 的 API Key 到环境变量。"""
    sync_api_key_to_env()


def get_api_key(agent_id: str | None = None) -> str:
    """读取 effective API Key（Agent 优先，再实例 fallback）。"""
    sync_api_key_to_env(agent_id)
    return os.environ.get(ENV_API_KEY, "").strip()


def set_api_key(key: str) -> None:
    """仅写入 data/user_settings.json，再同步到环境变量。"""
    from backend.user_settings import load_settings, save_settings

    cleaned = (key or "").strip()
    data = load_settings()
    if cleaned:
        data["deepseek_api_key"] = cleaned
    else:
        data.pop("deepseek_api_key", None)
    save_settings(data)
    sync_api_key_to_env()


def api_key_status(agent_id: str | None = None) -> dict[str, str | bool]:
    """设置页展示：Agent 级与实例 fallback 密钥状态。"""
    from backend.user_settings import mask_api_key
    from backend.agents.registry import agent_registry

    aid = (agent_id or "").strip() or agent_registry.active_agent_id
    agent_key = agent_registry.get_api_key(aid)
    disk = _disk_api_key()
    effective = agent_key or disk or _SYSTEM_API_KEY_FALLBACK
    return {
        "configured": bool(effective),
        "masked": mask_api_key(effective) if effective else "",
        "provider": "deepseek",
        "agent_id": aid,
        "agent_key_configured": bool(agent_key),
        "agent_key_masked": mask_api_key(agent_key) if agent_key else "",
        "fallback_key_configured": bool(disk),
        "fallback_key_masked": mask_api_key(disk) if disk else "",
    }
