"""Agent 工作区根路径解析（独立 / 共用）。"""

from __future__ import annotations

from pathlib import Path

from backend.config import APP_ROOT, WORKSPACE

from backend.agents.profile import AgentProfile, DEFAULT_AGENT_ID


def dedicated_workspace_dir(agent_id: str) -> Path:
    """返回 Agent 独立工作区目录路径（不一定已存在）。"""
    return APP_ROOT / "data" / "agents" / agent_id / "workspace"


def get_workspace_root(agent_id: str | None = None) -> Path:
    """解析 Agent 的有效 workspace 根目录。"""
    from backend.agents.registry import agent_registry

    aid = (agent_id or "").strip() or agent_registry.active_agent_id
    profile = agent_registry.get_profile(aid)
    return resolve_workspace_root(profile)


def resolve_workspace_root(profile: AgentProfile) -> Path:
    """根据 AgentProfile 的工作区配置解析根路径。"""
    mode = (profile.workspace_mode or "dedicated").strip().lower()
    if mode == "shared":
        ref = (profile.shared_workspace_ref or "legacy").strip()
        if ref == "legacy":
            return WORKSPACE
        if ref == DEFAULT_AGENT_ID or ref:
            from backend.agents.registry import agent_registry

            try:
                other = agent_registry.get_profile(ref)
            except KeyError:
                return WORKSPACE
            if (other.workspace_mode or "").lower() == "shared" and other.shared_workspace_ref == ref:
                return WORKSPACE
            return dedicated_workspace_dir(other.agent_id)
        return WORKSPACE

    custom = (profile.workspace_path or "").strip()
    if custom:
        path = Path(custom)
        if path.is_absolute():
            return path
        return (APP_ROOT / custom).resolve()

    return dedicated_workspace_dir(profile.agent_id)


def ensure_workspace_dir(profile: AgentProfile) -> Path:
    """确保 Agent 工作区目录存在并返回根路径。"""
    root = resolve_workspace_root(profile)
    root.mkdir(parents=True, exist_ok=True)
    return root
