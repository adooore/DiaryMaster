"""Agent 注册表：CRUD 与 active 切换。"""

from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from backend.config import APP_ROOT
from backend.user_settings import mask_api_key

from backend.agents.profile import (
    DEFAULT_AGENT_ID,
    AgentProfile,
    now_iso,
    slug_from_display_name,
    validate_agent_id,
)
from backend.agents.workspace import dedicated_workspace_dir, ensure_workspace_dir

AGENTS_DIR = APP_ROOT / "data" / "agents"
REGISTRY_PATH = AGENTS_DIR / "registry.json"


class AgentRegistry:
    """读写 data/agents/registry.json 与 Agent 元数据。"""

    def __init__(self) -> None:
        """加载注册表；若不存在则初始化 default Agent。"""
        self._lock = threading.RLock()
        self._agents: dict[str, AgentProfile] = {}
        self._active_agent_id: str = DEFAULT_AGENT_ID
        AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        if REGISTRY_PATH.is_file():
            self._load_registry()
        else:
            self._init_default_agent()

    @property
    def active_agent_id(self) -> str:
        """当前激活 Agent id。"""
        return self._active_agent_id

    def bootstrap(self) -> None:
        """应用启动：设置上下文 active agent 并同步 API Key。"""
        from backend.agents.context import set_active_agent_id
        from backend.config import sync_api_key_for_agent

        set_active_agent_id(self._active_agent_id)
        sync_api_key_for_agent(self._active_agent_id)

    def list_profiles(self) -> list[AgentProfile]:
        """按 sort_order、display_name 排序返回全部 Agent。"""
        items = sorted(
            self._agents.values(),
            key=lambda p: (p.sort_order, p.display_name.lower(), p.agent_id),
        )
        return items

    def get_profile(self, agent_id: str) -> AgentProfile:
        """按 id 获取 Agent；不存在抛 KeyError。"""
        aid = validate_agent_id(agent_id)
        if aid not in self._agents:
            raise KeyError(f"Agent 不存在: {aid}")
        return self._agents[aid]

    def agent_dir(self, agent_id: str) -> Path:
        """Agent 数据目录 data/agents/{id}/。"""
        return AGENTS_DIR / validate_agent_id(agent_id)

    def sessions_dir(self, agent_id: str) -> Path:
        """Agent Session 存储目录。"""
        path = self.agent_dir(agent_id) / "sessions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def memories_dir(self, agent_id: str) -> Path:
        """Agent 记忆文件目录。"""
        path = self.agent_dir(agent_id) / "memories"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def feishu_dir(self, agent_id: str) -> Path:
        """Agent 飞书渠道数据目录（bindings、config）。"""
        path = self.agent_dir(agent_id) / "feishu"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def find_by_feishu_app_id(self, app_id: str) -> AgentProfile | None:
        """按飞书 App ID 查找 Agent；未找到返回 None。"""
        needle = (app_id or "").strip()
        if not needle:
            return None
        for profile in self._agents.values():
            if (profile.feishu_app_id or "").strip() == needle:
                return profile
        return None

    def active_session_file(self, agent_id: str) -> Path:
        """Agent 当前 active session id 文件路径。"""
        return self.sessions_dir(agent_id) / "active_session.txt"

    def meta_path(self, agent_id: str) -> Path:
        """Agent meta.json 路径。"""
        return self.agent_dir(agent_id) / "meta.json"

    def set_active(self, agent_id: str) -> AgentProfile:
        """切换 active Agent 并持久化。"""
        profile = self.get_profile(agent_id)
        if not profile.enabled:
            raise ValueError(f"Agent 已禁用: {agent_id}")
        with self._lock:
            previous_id = self._active_agent_id
            self._active_agent_id = profile.agent_id
            self._save_registry()
        from backend.agents.context import set_active_agent_id
        from backend.agents.sessions import invalidate_session_store
        from backend.config import sync_api_key_for_agent

        set_active_agent_id(profile.agent_id)
        invalidate_session_store(previous_id)
        invalidate_session_store(profile.agent_id)
        sync_api_key_for_agent(profile.agent_id)
        return profile

    def create_agent(
        self,
        *,
        display_name: str,
        agent_id: str | None = None,
        description: str = "",
        role_prompt: str = "",
        workspace_mode: str = "dedicated",
        shared_workspace_ref: str | None = None,
        api_key: str | None = None,
        feishu_app_id: str | None = None,
        feishu_app_secret: str | None = None,
    ) -> AgentProfile:
        """新建 Agent 并写入磁盘。"""
        name = (display_name or "").strip()
        if not name:
            raise ValueError("display_name 不能为空")

        aid = validate_agent_id(agent_id) if agent_id else self._unique_id(slug_from_display_name(name))
        if aid in self._agents:
            raise ValueError(f"Agent 已存在: {aid}")

        mode = (workspace_mode or "dedicated").strip().lower()
        if mode not in ("dedicated", "shared"):
            raise ValueError("workspace_mode 须为 dedicated 或 shared")
        ws_ref = (shared_workspace_ref or "").strip() or None
        if mode == "shared":
            if not ws_ref:
                raise ValueError("共用工作区须指定 shared_workspace_ref（目标 Agent id）")
            self.get_profile(ws_ref)

        feishu_id = (feishu_app_id or "").strip() or None
        feishu_secret = (feishu_app_secret or "").strip() or None
        self._ensure_feishu_app_id_unique(feishu_id, exclude_agent_id=None)

        profile = AgentProfile(
            agent_id=aid,
            display_name=name[:80],
            description=(description or "")[:500],
            role_prompt=role_prompt or "",
            created_at=now_iso(),
            updated_at=now_iso(),
            api_key=(api_key or "").strip() or None,
            feishu_app_id=feishu_id,
            feishu_app_secret=feishu_secret,
            workspace_mode=mode,
            shared_workspace_ref=ws_ref,
            sort_order=len(self._agents),
        )

        with self._lock:
            self._agents[aid] = profile
            self.agent_dir(aid).mkdir(parents=True, exist_ok=True)
            self.sessions_dir(aid)
            self.memories_dir(aid)
            self.feishu_dir(aid)
            if mode == "dedicated":
                profile.shared_workspace_ref = None
                dedicated_workspace_dir(aid).mkdir(parents=True, exist_ok=True)
            self._write_meta(profile)
            self._save_registry()

        ensure_workspace_dir(profile)
        if (profile.feishu_app_id or "").strip() and (profile.feishu_app_secret or "").strip():
            self._invalidate_feishu_after_change((profile.feishu_app_id or "").strip())
        return profile

    def update_agent(
        self,
        agent_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        role_prompt: str | None = None,
        workspace_mode: str | None = None,
        shared_workspace_ref: str | None = None,
        api_key: str | None = None,
        clear_api_key: bool = False,
        feishu_app_id: str | None = None,
        feishu_app_secret: str | None = None,
        clear_feishu: bool = False,
        enabled: bool | None = None,
    ) -> AgentProfile:
        """更新 Agent 配置；api_key / feishu 留空表示不修改。"""
        profile = self.get_profile(agent_id)
        if display_name is not None:
            cleaned = display_name.strip()
            if not cleaned:
                raise ValueError("display_name 不能为空")
            profile.display_name = cleaned[:80]
        if description is not None:
            profile.description = description[:500]
        if role_prompt is not None:
            profile.role_prompt = role_prompt
        if workspace_mode is not None:
            mode = workspace_mode.strip().lower()
            if mode not in ("dedicated", "shared"):
                raise ValueError("workspace_mode 须为 dedicated 或 shared")
            profile.workspace_mode = mode
        if shared_workspace_ref is not None:
            profile.shared_workspace_ref = shared_workspace_ref.strip() or None
        if profile.workspace_mode == "shared" and not (profile.shared_workspace_ref or "").strip():
            raise ValueError("共用工作区须指定 shared_workspace_ref（目标 Agent id）")
        if profile.workspace_mode == "shared":
            self.get_profile(profile.shared_workspace_ref or "")
        if clear_api_key:
            profile.api_key = None
        elif api_key is not None and api_key.strip():
            profile.api_key = api_key.strip()
        if clear_feishu:
            old_app_id = (profile.feishu_app_id or "").strip()
            profile.feishu_app_id = None
            profile.feishu_app_secret = None
            feishu_changed = True
            feishu_old_app_id = old_app_id
        else:
            feishu_changed = False
            feishu_old_app_id = (profile.feishu_app_id or "").strip()
            if feishu_app_id is not None:
                new_id = feishu_app_id.strip() or None
                self._ensure_feishu_app_id_unique(new_id, exclude_agent_id=profile.agent_id)
                if new_id != profile.feishu_app_id:
                    feishu_changed = True
                profile.feishu_app_id = new_id
            if feishu_app_secret is not None and feishu_app_secret.strip():
                profile.feishu_app_secret = feishu_app_secret.strip()
                feishu_changed = True
        if enabled is not None:
            profile.enabled = bool(enabled)

        profile.updated_at = now_iso()
        with self._lock:
            self._agents[profile.agent_id] = profile
            self._write_meta(profile)
            self._save_registry()

        if profile.workspace_mode == "dedicated":
            profile.shared_workspace_ref = None
            dedicated_workspace_dir(profile.agent_id).mkdir(parents=True, exist_ok=True)
        ensure_workspace_dir(profile)

        if profile.agent_id == self._active_agent_id:
            from backend.config import sync_api_key_for_agent

            sync_api_key_for_agent(profile.agent_id)
        if feishu_changed:
            self._invalidate_feishu_after_change(feishu_old_app_id)
        return profile

    def delete_agent(self, agent_id: str) -> None:
        """删除 Agent；禁止删最后一个或 default（可配置）。"""
        aid = validate_agent_id(agent_id)
        if aid == DEFAULT_AGENT_ID:
            raise ValueError("不能删除 default Agent")
        if len(self._agents) <= 1:
            raise ValueError("至少保留一个 Agent")

        profile = self.get_profile(aid)
        feishu_app_id = (profile.feishu_app_id or "").strip()
        refs = self._agents_referencing_workspace(aid)
        if refs:
            raise ValueError(
                f"Agent {aid} 的工作区仍被 {', '.join(refs)} 共用，请先修改这些 Agent 的工作区配置"
            )

        with self._lock:
            del self._agents[aid]
            agent_path = self.agent_dir(aid)
            if agent_path.is_dir():
                shutil.rmtree(agent_path, ignore_errors=True)
            if self._active_agent_id == aid:
                self._active_agent_id = DEFAULT_AGENT_ID
            self._save_registry()

        from backend.agents.sessions import invalidate_session_store

        invalidate_session_store(aid)
        if feishu_app_id:
            self._invalidate_feishu_after_change(feishu_app_id)
        if self._active_agent_id == DEFAULT_AGENT_ID:
            self.set_active(DEFAULT_AGENT_ID)

    def summary(self, profile: AgentProfile) -> dict[str, Any]:
        """供 API 列表使用的 Agent 摘要（含脱敏 Key）。"""
        key = (profile.api_key or "").strip()
        ws_ref = profile.shared_workspace_ref if profile.workspace_mode == "shared" else None
        feishu_id = (profile.feishu_app_id or "").strip()
        feishu_secret = (profile.feishu_app_secret or "").strip()
        from backend.channels.feishu.config import is_enabled

        return {
            "agent_id": profile.agent_id,
            "display_name": profile.display_name,
            "description": profile.description,
            "enabled": profile.enabled,
            "is_active": profile.agent_id == self._active_agent_id,
            "workspace_mode": profile.workspace_mode,
            "shared_workspace_ref": ws_ref,
            "api_key_configured": bool(key),
            "api_key_masked": mask_api_key(key) if key else "",
            "feishu_app_id": feishu_id,
            "feishu_configured": is_enabled(profile.agent_id),
            "feishu_app_secret_configured": bool(feishu_secret),
            "feishu_app_secret_masked": mask_api_key(feishu_secret) if feishu_secret else "",
            "role_prompt": profile.role_prompt,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    def get_api_key(self, agent_id: str | None = None) -> str:
        """读取 Agent 级 API Key（不含 fallback）。"""
        aid = validate_agent_id(agent_id) if agent_id else self._active_agent_id
        profile = self.get_profile(aid)
        return (profile.api_key or "").strip()

    def _unique_id(self, base: str) -> str:
        """生成未占用的 agent_id。"""
        candidate = validate_agent_id(base) if _valid_id(base) else validate_agent_id(f"agent-{uuid.uuid4().hex[:6]}")
        if candidate not in self._agents:
            return candidate
        for i in range(2, 100):
            alt = f"{candidate}-{i}"[:32]
            if alt not in self._agents and _valid_id(alt):
                return validate_agent_id(alt)
        return validate_agent_id(f"agent-{uuid.uuid4().hex[:8]}")

    def _agents_referencing_workspace(self, agent_id: str) -> list[str]:
        """列出共用指定 Agent 独立工作区的其他 agent_id。"""
        refs: list[str] = []
        for p in self._agents.values():
            if p.agent_id == agent_id:
                continue
            if p.workspace_mode == "shared" and p.shared_workspace_ref == agent_id:
                refs.append(p.agent_id)
        return refs

    def _load_registry(self) -> None:
        """从 registry.json 加载。"""
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        self._active_agent_id = validate_agent_id(
            data.get("active_agent_id") or DEFAULT_AGENT_ID
        )
        agents_raw = data.get("agents") or []
        self._agents = {}
        for item in agents_raw:
            if not isinstance(item, dict):
                continue
            profile = AgentProfile.from_dict(item)
            self._agents[profile.agent_id] = profile
        if DEFAULT_AGENT_ID not in self._agents:
            raise RuntimeError("registry 缺少 default Agent")

    def _save_registry(self) -> None:
        """持久化 registry.json。"""
        payload = {
            "active_agent_id": self._active_agent_id,
            "agents": [
                p.to_dict(include_secrets=True)
                for p in self.list_profiles()
            ],
        }
        REGISTRY_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_meta(self, profile: AgentProfile) -> None:
        """写入 data/agents/{id}/meta.json。"""
        path = self.meta_path(profile.agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(profile.to_dict(include_secrets=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _init_default_agent(self) -> None:
        """首次启动：创建 default Agent 及目录结构。"""
        profile = AgentProfile(
            agent_id=DEFAULT_AGENT_ID,
            display_name="默认",
            description="",
            created_at=now_iso(),
            updated_at=now_iso(),
            workspace_mode="dedicated",
            sort_order=0,
        )
        self._agents = {DEFAULT_AGENT_ID: profile}
        self._active_agent_id = DEFAULT_AGENT_ID
        self.agent_dir(DEFAULT_AGENT_ID).mkdir(parents=True, exist_ok=True)
        self.sessions_dir(DEFAULT_AGENT_ID)
        self.memories_dir(DEFAULT_AGENT_ID)
        self.feishu_dir(DEFAULT_AGENT_ID)
        dedicated_workspace_dir(DEFAULT_AGENT_ID).mkdir(parents=True, exist_ok=True)
        self._write_meta(profile)
        self._save_registry()

    def _ensure_feishu_app_id_unique(
        self,
        app_id: str | None,
        *,
        exclude_agent_id: str | None,
    ) -> None:
        """校验飞书 App ID 未被其他 Agent 占用。"""
        needle = (app_id or "").strip()
        if not needle:
            return
        existing = self.find_by_feishu_app_id(needle)
        if existing and existing.agent_id != (exclude_agent_id or ""):
            raise ValueError(
                f"飞书 App ID 已被 Agent「{existing.display_name}」（{existing.agent_id}）使用"
            )

    def _invalidate_feishu_after_change(self, app_id: str) -> None:
        """飞书凭证变更后清 token 缓存并重启该 Agent 长连接。"""
        cleaned = (app_id or "").strip()
        if cleaned:
            try:
                from backend.channels.feishu.token import invalidate_token_cache

                invalidate_token_cache(cleaned)
            except ImportError:
                pass
        try:
            from backend.channels.feishu.ws_client import restart_feishu_ws_clients

            restart_feishu_ws_clients(force=True)
        except ImportError:
            pass


def _valid_id(candidate: str) -> bool:
    """判断字符串是否为合法 agent_id。"""
    try:
        validate_agent_id(candidate)
        return True
    except ValueError:
        return False


agent_registry = AgentRegistry()


def bootstrap_agents() -> None:
    """应用启动时初始化 Agent 上下文。"""
    agent_registry.bootstrap()


def get_agent_profile(agent_id: str) -> AgentProfile:
    """获取 AgentProfile。"""
    return agent_registry.get_profile(agent_id)


def list_agent_summaries() -> list[dict[str, Any]]:
    """列出全部 Agent 摘要。"""
    return [agent_registry.summary(p) for p in agent_registry.list_profiles()]
