"""DiaryMaster Agent：LangChain 工具、对话流式执行、文件变更记录。

本文件分层说明：
- 带 @tool 的函数：暴露给大模型，docstring 会进入工具描述。
- 带 _ 前缀的函数：项目内部实现，docstring 主要给人阅读。
- chat_stream：一轮对话的主入口，向 UI 推送 step / done 事件。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from backend import workspace_fs
from backend.context_usage import TurnUsageTracker
from backend.model_registry import (
    default_model_id,
    get_model,
    resolve_api_key,
    validate_model_id,
)
from backend.patch_apply import PatchError, apply_unique_replace
from backend.agent_steps import (
    clear_step_emitter,
    format_step_detail,
    new_step_id,
    publish_step,
    set_step_emitter,
    tool_result_status,
    truncate_detail,
)
from backend.session_store import FileChange, store

# 已有文件超过此行数时，write_file 会拒绝整篇覆盖，迫使模型用 edit_file。
FULL_WRITE_MAX_LINES = 60

# 当前这一轮对话的临时状态（每轮 chat_stream 开始时清空）。
_written_this_turn: list[str] = []  # 本轮 Agent 写过的文件路径
_changes_this_turn: list[FileChange] = []  # 本轮产生的 FileChange 对象
_current_turn: int = 0  # 与 session_store.turn 对齐
_collected_steps: list[dict[str, Any]] = []  # 本轮步骤快照，结束时写入 done 事件

# 发给大模型的系统提示（与各 @tool 的 docstring 一起约束行为）。
SYSTEM_PROMPT = f"""你是 DiaryMaster 的笔记助手，像朋友一样帮助用户整理和修改笔记。

规则：
- 不要编造用户没有明确表达的事实；信息不足时先简短追问。
- 用简洁的中文回复用户。

写入与修改：
- **新建**笔记（文件尚不存在）→ 使用 write_file，写入完整内容。
- **修改**已有笔记 → 默认使用 edit_file：old_string 必须从 read_file 或上下文中**原样复制**（含换行、空格、标点），且在文件中**只出现一次**；new_string 为替换后的片段。
- 仅当用户明确要求「全文重写」，或文件很短（不足 {FULL_WRITE_MAX_LINES} 行）且需大范围改写时，才用 write_file 覆盖已有文件。
- edit_file 失败时不要改用 write_file 猜测全文；先 read_file 核对后再重试 edit_file。
- 一处修改对应一次 edit_file；多处修改可多次调用 edit_file，或一次 old_string 包含足够上下文。

跨文件写作：
- 工作区可能有多篇笔记。用户消息里会附带「工作区文件列表」；需要某篇全文时用 read_file 读取。
- 汇总、周总结、对比多篇笔记：先 list_files / read_file 读取源笔记，再 write_file 写入新的汇总文件（新文件用 write_file 合理）。
- 未 read_file 读过的内容不要编造。"""

def _norm_rel(path: str) -> str:
    """把路径规范成工作区相对路径（正斜杠、去掉首部 /）。"""
    return path.replace("\\", "/").lstrip("/")


def _read_safe(path: str) -> str:
    """读取笔记内容；文件不存在或非法路径时返回空字符串，不抛异常。"""
    try:
        return workspace_fs.read_file(path)
    except workspace_fs.WorkspaceError:
        return ""


def _upsert_collected_step(step: dict[str, Any]) -> None:
    """按 step.id 更新 _collected_steps，供结束时打包进 done.steps。"""
    sid = step.get("id")
    if not sid:
        return
    for i, existing in enumerate(_collected_steps):
        if existing.get("id") == sid:
            _collected_steps[i] = step
            return
    _collected_steps.append(step)


def _publish(step: dict[str, Any]) -> None:
    """写入本轮步骤列表，并通过 agent_steps 推给 SSE（若已注册 emitter）。"""
    step = {**step, "turn": _current_turn}
    _upsert_collected_step(step)
    publish_step(step)


def _step_thinking(label: str, *, step_id: str, status: str = "running") -> None:
    """发布一条「思考/规划」类步骤（UI 里 kind=thinking，非工具调用）。"""
    _publish(
        {
            "id": step_id,
            "kind": "thinking",
            "status": status,
            "label": label,
            "tool": None,
            "path": None,
        }
    )


def _step_reply_status(label: str, *, step_id: str, status: str = "running") -> None:
    """回复生成状态（UI 固定显示在步骤列表最后一行）。"""
    _publish(
        {
            "id": step_id,
            "kind": "reply_status",
            "status": status,
            "label": label,
            "tool": None,
            "path": None,
        }
    )


def _run_llm_step(tool: str, label: str, work: Callable[[], str]) -> str:
    """
    包装一次独立 LLM 调用（不在 LangChain Agent 工具列表里），并推送 UI 步骤。
    用于 generate_title 等；kind=llm，与文件工具区分。
    """
    step_id = new_step_id()
    _publish(
        {
            "id": step_id,
            "kind": "llm",
            "tool": tool,
            "status": "running",
            "label": label,
            "path": None,
        }
    )
    result = work()
    _publish(
        {
            "id": step_id,
            "kind": "llm",
            "tool": tool,
            "status": "done",
            "label": label,
            "path": None,
            "detail": truncate_detail(result, 120),
        }
    )
    return result


def _publish_agent_model_step(msg: AIMessage) -> None:
    """Agent 主循环里每次 model 节点产出 AIMessage 时，记一条「模型调用」步骤。"""
    step_id = new_step_id()
    if msg.tool_calls:
        names = ", ".join(_tool_call_name(tc) for tc in msg.tool_calls)
        _publish(
            {
                "id": step_id,
                "kind": "llm",
                "tool": "agent",
                "status": "running",
                "label": "模型调用 · 规划工具",
                "path": None,
            }
        )
        _publish(
            {
                "id": step_id,
                "kind": "llm",
                "tool": "agent",
                "status": "done",
                "label": "模型调用 · 规划工具",
                "path": None,
                "detail": f"将调用: {names}",
            }
        )
        return

    text = _extract_ai_text(msg)
    if not text:
        return
    _publish(
        {
            "id": step_id,
            "kind": "llm",
            "tool": "agent",
            "status": "running",
            "label": "模型调用 · 生成回复",
            "path": None,
        }
    )
    _publish(
        {
            "id": step_id,
            "kind": "llm",
            "tool": "agent",
            "status": "done",
            "label": "模型调用 · 生成回复",
            "path": None,
            "detail": truncate_detail(text, 120),
        }
    )


def _run_tool_step(tool: str, label: str, path: str | None, work: Callable[[], str]) -> str:
    """
    包装一次工具真实逻辑：先推送 running，执行 work()，再推送 done/error。
    所有 @tool 都经此函数，以便右侧对话区实时显示 [read_file]、[edit_file] 等。
    """
    step_id = new_step_id()
    _publish(
        {
            "id": step_id,
            "kind": "tool",
            "tool": tool,
            "status": "running",
            "label": label,
            "path": path,
        }
    )
    result = work()
    _publish(
        {
            "id": step_id,
            "kind": "tool",
            "tool": tool,
            "status": tool_result_status(result),
            "label": label,
            "path": path,
            "detail": format_step_detail(tool, result),
        }
    )
    return result


def _commit_file_change(rel: str, old_content: str, new_content: str, *, action: str) -> str:
    """
    把新内容写入磁盘，并在 session 里记录一条 FileChange（供 diff / 回退）。
    返回给模型的短句摘要；无实际改动时不写盘。
    """
    if old_content == new_content:
        return f"{action}：内容无变化"
    workspace_fs.write_file(rel, new_content)
    if rel not in _written_this_turn:
        _written_this_turn.append(rel)
    change = store.record_change(
        rel,
        old_content,
        new_content,
        source="agent",
        turn=_current_turn,
    )
    if change is not None:
        _changes_this_turn.append(change)
    delta = len(new_content) - len(old_content)
    sign = "+" if delta >= 0 else ""
    return f"已{action} {rel}（全文 {len(new_content)} 字符，本次 {sign}{delta}）"


@tool
def list_files() -> str:
    """列出工作区内所有笔记文件的相对路径（每行一个）。"""
    return _run_tool_step(
        "list_files",
        "列出工作区文件",
        None,
        _list_files_impl,
    )


def _list_files_impl() -> str:
    """（内部）扫描 workspace 目录，返回路径列表文本。由 list_files 工具调用。"""
    paths = workspace_fs.list_files()
    if not paths:
        return "（工作区暂无文件）"
    return "\n".join(paths)


@tool
def read_file(path: str) -> str:
    """读取工作区内一篇笔记的完整内容。path 为相对路径，如 2025-05-15.md。"""
    rel = _norm_rel(path)
    return _run_tool_step(
        "read_file",
        f"读取 {rel}",
        rel,
        lambda: _read_file_impl(rel),
    )


def _read_file_impl(rel: str) -> str:
    """（内部）读取单文件并加上 --- 包裹头尾，便于模型辨认边界。"""
    try:
        body = workspace_fs.read_file(rel)
    except workspace_fs.WorkspaceError as e:
        return f"读取失败: {e}"
    return f"--- {rel} ---\n{body}\n---"


@tool
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """
    局部修改已有笔记：将文件中唯一匹配的 old_string 替换为 new_string。
    old_string 须与 read_file 读到的原文完全一致；若匹配 0 次或多次会失败且不写盘。
    """
    rel = _norm_rel(path)
    return _run_tool_step(
        "edit_file",
        f"局部修改 {rel}",
        rel,
        lambda: _edit_file_impl(rel, old_string, new_string),
    )


def _edit_file_impl(rel: str, old_string: str, new_string: str) -> str:
    """（内部）唯一匹配替换；失败时返回错误文案且不写盘。由 edit_file 工具调用。"""
    try:
        old_content = workspace_fs.read_file(rel)
    except workspace_fs.WorkspaceError as e:
        return f"局部修改失败: 文件不存在或无法读取 ({e})。新建请用 write_file。"

    try:
        new_content = apply_unique_replace(old_content, old_string, new_string)
    except PatchError as e:
        return f"局部修改失败: {e}"

    return _commit_file_change(rel, old_content, new_content, action="局部修改")


@tool
def write_file(path: str, content: str) -> str:
    """将完整内容写入工作区。用于新建文件，或短文全文重写；修改已有长文请优先 edit_file。"""
    rel = _norm_rel(path)
    return _run_tool_step(
        "write_file",
        f"写入 {rel}",
        rel,
        lambda: _write_file_impl(rel, content),
    )


def _write_file_impl(rel: str, content: str) -> str:
    """（内部）整文件写入；过长已有文件会拒绝。由 write_file 工具调用。"""
    old_content = _read_safe(rel)
    if old_content:
        line_count = len(old_content.splitlines())
        if line_count >= FULL_WRITE_MAX_LINES:
            return (
                f"写入中止: {rel} 已有 {line_count} 行，请用 edit_file 局部修改，"
                "或先确认用户需要全文重写。"
            )
    return _commit_file_change(rel, old_content, content, action="写入")


def _create_chat_model(
    model_id: str,
    *,
    thinking_enabled: bool,
    temperature: float | None = 0.3,
):
    """按 registry 创建 LangChain 聊天模型（含思考模式 extra_body）。"""
    spec = get_model(model_id)
    api_key = resolve_api_key(spec)
    extra_body = {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}
    kwargs: dict[str, Any] = {
        "model": spec.langchain_model,
        "api_key": api_key,
        "model_kwargs": {"extra_body": extra_body},
    }
    if thinking_enabled:
        return init_chat_model(**kwargs)
    if temperature is not None:
        kwargs["temperature"] = temperature
    return init_chat_model(**kwargs)


def _build_agent(model_id: str, thinking_enabled: bool):
    """创建 LangChain Agent（按 model_id + 思考开关）。"""
    model = _create_chat_model(model_id, thinking_enabled=thinking_enabled)
    return create_agent(
        model=model,
        tools=[list_files, read_file, edit_file, write_file],
        system_prompt=SYSTEM_PROMPT,
    )


_agent_cache: dict[tuple[str, bool], Any] = {}


def _get_agent(model_id: str, thinking_enabled: bool):
    """按 (model_id, thinking) 缓存 Agent 实例。"""
    mid = validate_model_id(model_id)
    key = (mid, bool(thinking_enabled))
    if key not in _agent_cache:
        _agent_cache[key] = _build_agent(mid, key[1])
    return _agent_cache[key]


def _extract_reasoning(msg: AIMessage) -> str:
    """从 AIMessage 取出思考链文本（DeepSeek reasoning_content）。"""
    ak = getattr(msg, "additional_kwargs", None) or {}
    if isinstance(ak, dict):
        rc = ak.get("reasoning_content")
        if rc:
            return rc if isinstance(rc, str) else str(rc)
    rm = getattr(msg, "response_metadata", None) or {}
    if isinstance(rm, dict):
        rc = rm.get("reasoning_content")
        if rc:
            return rc if isinstance(rc, str) else str(rc)
    return ""


def _publish_reasoning_step(step_id: str, text: str, *, running: bool) -> None:
    if not text.strip():
        return
    _publish(
        {
            "id": step_id,
            "kind": "reasoning",
            "tool": None,
            "status": "running" if running else "done",
            "label": "思考中…" if running else "思考过程",
            "path": None,
            "detail": truncate_detail(text, 4000),
        }
    )


def _extract_ai_text(msg: AIMessage) -> str:
    """从 AIMessage 取出纯文本（兼容 str 或多段 content 块）。"""
    raw = msg.content
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, list):
        parts = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif hasattr(block, "text"):
                parts.append(getattr(block, "text", ""))
        return "".join(parts).strip()
    return ""


def _tool_call_name(tc: Any) -> str:
    """从 tool_call 对象或 dict 里取出工具名，用于步骤展示。"""
    if isinstance(tc, dict):
        return tc.get("name", "?")
    return getattr(tc, "name", "?")


def _build_user_message(user_message: str, current_file: str | None) -> str:
    """
    拼进本轮 HumanMessage 的完整用户侧文本：
    工作区文件列表 + 当前打开文件全文 + 用户输入。
    """
    context_parts = []
    all_files = workspace_fs.list_files()
    if all_files:
        listing = "\n".join(f"- {p}" for p in all_files)
        context_parts.append(f"工作区文件列表:\n{listing}")

    if current_file:
        try:
            body = workspace_fs.read_file(current_file)
            context_parts.append(f"用户当前打开的文件: {current_file}\n---\n{body}\n---")
        except workspace_fs.WorkspaceError:
            context_parts.append(f"用户当前打开的文件: {current_file}（读取失败）")

    if context_parts:
        return "\n\n".join(context_parts) + "\n\n用户消息: " + user_message
    return user_message


def _extract_reply(out_messages: list) -> str:
    """从 Agent 最终消息列表里取最后一条有内容的 AI 回复。"""
    for msg in reversed(out_messages):
        if not isinstance(msg, AIMessage):
            continue
        text = _extract_ai_text(msg)
        if text:
            return text
    return "（无回复内容）"


def _flush_pending(pending: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """把工具执行期间缓存在 pending 里的 step 事件依次 yield 出去。"""
    while pending:
        yield pending.pop(0)


def chat_stream(
    user_message: str,
    current_file: str | None = None,
    *,
    model_id: str | None = None,
    thinking_enabled: bool = False,
) -> Iterator[dict[str, Any]]:
    """
    流式执行一轮对话（主入口）。

    产出事件类型：
    - step：思考、文件工具、模型调用（kind=llm）、生成标题（tool=generate_title）等。
    - done：含 reply、written_files、changes、steps、session_id、turn；首轮含 session_title。
    - error：异常信息。

    流程：LangChain Agent 循环 →（首轮）循环外再调一次 LLM 生成标题 → done。
    标题生成不在 Agent 工具列表内，但在同一轮流式时间线里展示。
    """
    global _written_this_turn, _changes_this_turn, _current_turn, _collected_steps

    _written_this_turn = []
    _changes_this_turn = []
    _collected_steps = []
    _current_turn = store.begin_turn()
    turn = _current_turn

    mid = validate_model_id(model_id)
    thinking = bool(thinking_enabled)

    pending: list[dict[str, Any]] = []
    reply_step_id = f"reply-{uuid.uuid4().hex[:8]}"
    reasoning_step_id = f"reasoning-{uuid.uuid4().hex[:8]}"
    reply_step_started = False
    reasoning_acc = ""
    usage_tracker = TurnUsageTracker()

    def emit(step: dict[str, Any]) -> None:
        pending.append(step)

    clear_step_emitter()
    set_step_emitter(emit)

    session = store.get_session()
    messages = list(session.messages)
    full_message = _build_user_message(user_message.strip(), current_file)
    messages.append(HumanMessage(content=full_message))

    final_state: dict[str, Any] | None = None

    try:
        agent = _get_agent(mid, thinking)
        for item in agent.stream(
            {"messages": messages},
            stream_mode=["updates", "values"],
        ):
            mode: str
            chunk: dict[str, Any]
            if isinstance(item, tuple) and len(item) == 2:
                mode, chunk = item
            else:
                mode, chunk = "updates", item

            if mode == "values":
                final_state = chunk
                continue

            yield from _flush_pending(pending)

            for msg in chunk.get("model", {}).get("messages", []):
                if not isinstance(msg, AIMessage):
                    continue
                usage_tracker.absorb_message(msg)
                reasoning_text = _extract_reasoning(msg)
                if reasoning_text and len(reasoning_text) > len(reasoning_acc):
                    reasoning_acc = reasoning_text
                    _publish_reasoning_step(
                        reasoning_step_id, reasoning_acc, running=True
                    )
                    yield from _flush_pending(pending)
                _publish_agent_model_step(msg)
                yield from _flush_pending(pending)
                if (
                    not msg.tool_calls
                    and _extract_ai_text(msg)
                    and not reply_step_started
                ):
                    _step_reply_status(
                        "生成回复…", step_id=reply_step_id, status="running"
                    )
                    reply_step_started = True
                    yield from _flush_pending(pending)

        yield from _flush_pending(pending)

        if not final_state:
            raise RuntimeError("Agent 未返回最终状态")

        out_messages = final_state.get("messages", [])
        session.messages.clear()
        session.messages.extend(out_messages)

        reply = _extract_reply(out_messages)
        written = list(_written_this_turn)
        turn_changes = [c.to_dict() for c in _changes_this_turn]

        if reasoning_acc:
            _publish_reasoning_step(
                reasoning_step_id, reasoning_acc, running=False
            )
            yield from _flush_pending(pending)

        session_title: str | None = None
        if turn == 1 and not session.title_locked:
            yield from _flush_pending(pending)
            session_title = _run_llm_step(
                "generate_title",
                "生成会话标题",
                lambda: _generate_session_title_impl(
                    user_message.strip(), reply, model_id=mid
                ),
            )
            store.set_session_title(session_title, manual=False)
            yield from _flush_pending(pending)

        _step_reply_status(
            "回复生成完成", step_id=reply_step_id, status="done"
        )
        yield from _flush_pending(pending)

        steps_snapshot = [dict(s) for s in _collected_steps]

        _written_this_turn = []
        _changes_this_turn = []

        turn_usage = usage_tracker.to_dict()
        if not turn_usage:
            from backend.context_usage import (
                estimate_session_context_tokens,
                normalize_turn_usage,
            )

            est = estimate_session_context_tokens(out_messages)
            turn_usage = normalize_turn_usage(est, source="estimate")

        done_payload: dict[str, Any] = {
            "type": "done",
            "reply": reply,
            "written_files": written,
            "changes": turn_changes,
            "steps": steps_snapshot,
            "session_id": session.id,
            "turn": turn,
            "usage": turn_usage,
        }
        if reasoning_acc:
            done_payload["reasoning"] = reasoning_acc
        if session_title:
            done_payload["session_title"] = session_title
        yield done_payload
    except Exception as e:
        yield from _flush_pending(pending)
        if reply_step_started:
            _step_reply_status(
                "回复生成失败", step_id=reply_step_id, status="error"
            )
            yield from _flush_pending(pending)
        yield {"type": "error", "detail": str(e), "turn": turn}
    finally:
        clear_step_emitter()


def chat(
    user_message: str,
    current_file: str | None = None,
    *,
    model_id: str | None = None,
    thinking_enabled: bool = False,
) -> tuple[str, list[str], list[dict]]:
    """非流式封装：跑完 chat_stream 只取 done 里的结果（测试或 /api/chat 用）。"""
    reply = ""
    written: list[str] = []
    changes: list[dict] = []
    for event in chat_stream(
        user_message,
        current_file,
        model_id=model_id,
        thinking_enabled=thinking_enabled,
    ):
        if event.get("type") == "done":
            reply = event.get("reply", "")
            written = event.get("written_files", [])
            changes = event.get("changes", [])
        elif event.get("type") == "error":
            raise RuntimeError(event.get("detail", "Agent 调用失败"))
    return reply, written, changes


def new_session() -> str:
    """新建空白 Session，返回 session id。"""
    session = store.new_session()
    return session.id


def switch_session(session_id: str) -> str:
    """切换到已有 Session。"""
    session = store.switch_session(session_id)
    return session.id


def delete_session(session_id: str) -> str:
    """删除 Session，返回新的 active session id。"""
    return store.delete_session(session_id)


def list_sessions() -> list[dict]:
    """列出所有 Session 摘要（供顶栏下拉框）。"""
    return store.list_sessions()


def get_session_info() -> dict:
    """当前 Session 元数据 + 展开后的 chat_log（含变更摘要）。"""
    session = store.get_session()
    info = session.to_dict()
    info["chat_log"] = store.get_chat_log_for_api()
    return info


def get_change(change_id: str) -> FileChange | None:
    """按 id 取一条文件变更（含全文 old/new，供 diff 视图）。"""
    return store.get_change(change_id)


def rollback_change(change_id: str) -> dict:
    """回退到某条变更之前（含磁盘恢复与对话裁剪）。"""
    return store.rollback_to(change_id)


def rollback_turn(turn: int) -> dict:
    """回退到指定轮次之前。"""
    return store.rollback_to_turn(turn)


def rollback_latest(path: str | None = None) -> dict:
    """回退当前文件（或全局）最近一次变更。"""
    return store.rollback_latest(path)


def _generate_session_title_impl(
    user_message: str,
    assistant_reply: str,
    *,
    model_id: str | None = None,
) -> str:
    """
    （内部）单独调用 LLM 生成 Session 标题，不推送步骤。
    由 chat_stream 通过 _run_llm_step 包装后展示在 UI。
    """
    try:
        mid = validate_model_id(model_id or default_model_id())
        model = _create_chat_model(mid, thinking_enabled=False, temperature=0.2)
    except RuntimeError:
        fallback = user_message.strip()
        return (fallback[:20] + "…") if len(fallback) > 20 else fallback or "新对话"
    prompt = (
        "根据下面第一轮对话，为笔记会话起一个简短中文标题。\n"
        "要求：不超过 20 个字；不要引号；不要句号；只输出标题本身。\n\n"
        f"用户：{user_message.strip()[:800]}\n\n"
        f"助手：{assistant_reply.strip()[:800]}"
    )
    try:
        msg = model.invoke(
            [
                SystemMessage(content="你是标题生成器，只输出一个简短中文标题。"),
                HumanMessage(content=prompt),
            ]
        )
        if isinstance(msg, AIMessage):
            raw = _extract_ai_text(msg)
        else:
            raw = str(getattr(msg, "content", msg)).strip()
    except Exception:
        raw = ""

    title = raw.strip().strip("\"'「」『』").split("\n")[0].strip()
    title = title.rstrip("。．.!！?？")
    if not title:
        fallback = user_message.strip()
        title = (fallback[:20] + "…") if len(fallback) > 20 else fallback
    return title[:20] if len(title) > 20 else title


def generate_session_title(user_message: str, assistant_reply: str) -> str:
    """供测试或非流式场景：生成标题（无 UI 步骤）。"""
    return _generate_session_title_impl(user_message, assistant_reply)


def record_manual_change(path: str, old_content: str, new_content: str) -> FileChange | None:
    """用户在中栏点保存时记录 manual 来源的 FileChange。"""
    session = store.get_session()
    return store.record_change(
        path,
        old_content,
        new_content,
        source="manual",
        turn=session.turn,
    )
