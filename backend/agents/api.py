"""Agent 管理 REST API（供 main.py 挂载）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import agent as agent_module
from backend.agents.registry import agent_registry
from backend.config import api_key_status, sync_api_key_for_agent
from backend.memory import MemoryLimitExceeded, MemoryStoreError, memories_payload, store as memory_store

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentCreateRequest(BaseModel):
    """POST /api/agents 请求体。"""

    display_name: str
    agent_id: str | None = None
    description: str = ""
    role_prompt: str = ""
    workspace_mode: str = "dedicated"
    shared_workspace_ref: str | None = None
    api_key: str | None = None
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_reply_display: str | None = None
    feishu_card_backend: str | None = None


class AgentUpdateRequest(BaseModel):
    """PUT /api/agents/{id} 请求体。"""

    display_name: str | None = None
    description: str | None = None
    role_prompt: str | None = None
    workspace_mode: str | None = None
    shared_workspace_ref: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    clear_feishu: bool = False
    feishu_reply_display: str | None = None
    feishu_card_backend: str | None = None
    enabled: bool | None = None


class AgentActiveRequest(BaseModel):
    """PUT /api/agents/active 请求体。"""

    agent_id: str


class AgentMemoriesUpdateRequest(BaseModel):
    """PUT /api/agents/{id}/memories 请求体。"""

    user: str = ""
    memory: str = ""


def _agent_detail_payload(profile) -> dict[str, Any]:
    """单个 Agent 详情（含 API Key 状态与飞书行为配置）。"""
    from backend.channels.feishu.channel_config import channel_config_for_api

    payload = agent_registry.summary(profile)
    payload["api_key_status"] = api_key_status(profile.agent_id)
    payload["feishu_channel"] = channel_config_for_api(profile.agent_id)
    return payload


def _apply_feishu_channel_patch(agent_id: str, body: AgentCreateRequest | AgentUpdateRequest) -> None:
    """合并请求体中的飞书行为配置到 Agent。"""
    from backend.channels.feishu.channel_config import apply_channel_config_patch

    patch: dict[str, str] = {}
    reply = getattr(body, "feishu_reply_display", None)
    backend = getattr(body, "feishu_card_backend", None)
    if reply is not None:
        patch["reply_display"] = reply
    if backend is not None:
        patch["card_backend"] = backend
    if patch:
        apply_channel_config_patch(patch, agent_id)


def _agents_list_payload() -> dict[str, Any]:
    """组装 Agent 列表响应。"""
    return {
        "active_agent_id": agent_registry.active_agent_id,
        "agents": [agent_registry.summary(p) for p in agent_registry.list_profiles()],
    }


@router.get("")
def api_list_agents():
    """列出全部 Agent 与当前 active。"""
    return _agents_list_payload()


@router.put("/active")
def api_set_active_agent(body: AgentActiveRequest):
    """切换当前 active Agent。"""
    try:
        agent_registry.set_active(body.agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    agent_module.clear_agent_cache()
    sync_api_key_for_agent(body.agent_id)
    return {"ok": True, **_agents_list_payload()}


@router.get("/{agent_id}")
def api_get_agent(agent_id: str):
    """读取单个 Agent 详情。"""
    try:
        profile = agent_registry.get_profile(agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    payload = _agent_detail_payload(profile)
    return payload


@router.post("")
def api_create_agent(body: AgentCreateRequest):
    """新建 Agent。"""
    try:
        profile = agent_registry.create_agent(
            display_name=body.display_name,
            agent_id=body.agent_id,
            description=body.description,
            role_prompt=body.role_prompt,
            workspace_mode=body.workspace_mode,
            shared_workspace_ref=body.shared_workspace_ref,
            api_key=body.api_key,
            feishu_app_id=body.feishu_app_id,
            feishu_app_secret=body.feishu_app_secret,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _apply_feishu_channel_patch(profile.agent_id, body)
    agent_module.clear_agent_cache()
    return {"ok": True, "agent": agent_registry.summary(profile), **_agents_list_payload()}


@router.put("/{agent_id}")
def api_update_agent(agent_id: str, body: AgentUpdateRequest):
    """更新 Agent 配置。"""
    try:
        profile = agent_registry.update_agent(
            agent_id,
            display_name=body.display_name,
            description=body.description,
            role_prompt=body.role_prompt,
            workspace_mode=body.workspace_mode,
            shared_workspace_ref=body.shared_workspace_ref,
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
            feishu_app_id=body.feishu_app_id,
            feishu_app_secret=body.feishu_app_secret,
            clear_feishu=body.clear_feishu,
            enabled=body.enabled,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _apply_feishu_channel_patch(agent_id, body)
    agent_module.clear_agent_cache()
    return {"ok": True, "agent": agent_registry.summary(profile), **_agents_list_payload()}


@router.delete("/{agent_id}")
def api_delete_agent(agent_id: str):
    """删除 Agent。"""
    try:
        agent_registry.delete_agent(agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    agent_module.clear_agent_cache()
    return {"ok": True, **_agents_list_payload()}


@router.get("/{agent_id}/memories")
def api_get_agent_memories(agent_id: str):
    """读取指定 Agent 的长期记忆。"""
    from backend.agents.context import set_active_agent_id

    try:
        agent_registry.get_profile(agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    previous = agent_registry.active_agent_id
    set_active_agent_id(agent_id)
    try:
        return {"agent_id": agent_id, **memories_payload()}
    finally:
        set_active_agent_id(previous)


@router.put("/{agent_id}/memories")
def api_update_agent_memories(agent_id: str, body: AgentMemoriesUpdateRequest):
    """保存指定 Agent 的长期记忆。"""
    from backend.agents.context import set_active_agent_id

    try:
        agent_registry.get_profile(agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    previous = agent_registry.active_agent_id
    set_active_agent_id(agent_id)
    try:
        memory_store.write_content("user", body.user)
        memory_store.write_content("memory", body.memory)
    except MemoryLimitExceeded as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except MemoryStoreError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        set_active_agent_id(previous)
    agent_module.clear_agent_cache()
    set_active_agent_id(agent_id)
    try:
        payload = {"ok": True, "agent_id": agent_id, **memories_payload()}
    finally:
        set_active_agent_id(previous)
    return payload
