from __future__ import annotations

import json
import sys
from pathlib import Path

_DEMO_ROOT = Path(__file__).resolve().parent.parent
if str(_DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import agent, workspace_fs
from backend.config import WEB_DIR
from backend.session_store import store

app = FastAPI(title="DeepNote Demo")


class ChatRequest(BaseModel):
    message: str
    current_file: str | None = None


class ChatResponse(BaseModel):
    reply: str
    written_files: list[str]
    session_id: str
    turn: int
    changes: list[dict]


class FileWriteRequest(BaseModel):
    content: str


class ManualSaveRequest(BaseModel):
    content: str
    record_change: bool = True


class SessionTitleRequest(BaseModel):
    title: str


@app.get("/api/session")
def api_get_session():
    info = agent.get_session_info()
    info["sessions"] = agent.list_sessions()
    info["active_id"] = store.active_id
    return info


@app.get("/api/sessions")
def api_list_sessions():
    from backend.session_store import store

    return {
        "active_id": store.active_id,
        "sessions": store.list_sessions(),
    }


@app.post("/api/session/new")
def api_new_session():
    from backend.session_store import store

    session_id = agent.new_session()
    store.append_chat_message("system", f"已新建 Session: {session_id}")
    return {
        "session_id": session_id,
        "ok": True,
        "sessions": store.list_sessions(),
    }


@app.post("/api/session/{session_id}/activate")
def api_activate_session(session_id: str):
    from backend.session_store import store

    try:
        agent.switch_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    info = agent.get_session_info()
    info["sessions"] = store.list_sessions()
    info["active_id"] = store.active_id
    return info


@app.get("/api/session/changes")
def api_list_changes(path: str | None = None):
    from backend.session_store import store

    changes = store.list_changes(path)
    return {
        "session_id": store.get_session().id,
        "changes": [c.summary() for c in changes],
    }


@app.get("/api/session/changes/{change_id}")
def api_get_change(change_id: str):
    change = agent.get_change(change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="变更记录不存在")
    return change.to_dict()


@app.post("/api/session/turns/{turn}/rollback")
def api_rollback_turn(turn: int):
    try:
        from backend.session_store import store

        result = agent.rollback_turn(turn)
        n_changes = len(result.get("removed_change_ids") or [])
        n_chat = result.get("removed_chat_events") or 0
        store.append_chat_message(
            "system",
            f"已回退到第 {turn} 轮之前（撤销 {n_changes} 条变更、{n_chat} 段对话）",
        )
        return {
            "ok": True,
            "session_id": store.get_session().id,
            **result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except workspace_fs.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/session/changes/{change_id}/rollback")
def api_rollback_change(change_id: str):
    try:
        from backend.session_store import store

        result = agent.rollback_change(change_id)
        turn = result.get("turn", 0)
        n_changes = len(result.get("removed_change_ids") or [])
        n_chat = result.get("removed_chat_events") or 0
        store.append_chat_message(
            "system",
            f"已回退到第 {turn} 轮之前（撤销 {n_changes} 条变更、{n_chat} 段对话）",
        )

        return {
            "ok": True,
            "session_id": store.get_session().id,
            **result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except workspace_fs.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/session/rollback/latest")
def api_rollback_latest(path: str | None = None):
    try:
        from backend.session_store import store

        result = agent.rollback_latest(path)
        turn = result.get("turn", 0)
        n_changes = len(result.get("removed_change_ids") or [])
        n_chat = result.get("removed_chat_events") or 0
        store.append_chat_message(
            "system",
            f"已回退到第 {turn} 轮之前（撤销 {n_changes} 条变更、{n_chat} 段对话）",
        )

        return {
            "ok": True,
            "session_id": store.get_session().id,
            **result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except workspace_fs.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/files")
def api_list_files():
    return {"files": workspace_fs.list_files()}


@app.get("/api/files/{path:path}")
def api_read_file(path: str):
    try:
        content = workspace_fs.read_file(path)
        return {"path": path, "content": content}
    except workspace_fs.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.put("/api/files/{path:path}")
def api_write_file(path: str, body: ManualSaveRequest):
    from backend.session_store import store

    try:
        old_content = ""
        try:
            old_content = workspace_fs.read_file(path)
        except workspace_fs.WorkspaceError:
            pass
        workspace_fs.write_file(path, body.content)
        change_dict = None
        if body.record_change and old_content != body.content:
            change = agent.record_manual_change(path, old_content, body.content)
            if change:
                change_dict = change.to_dict()
                store.append_chat_changes(change.turn, [change.id])

        if change_dict is None:
            store.append_chat_message("system", f"已保存 {path}")

        return {
            "path": path,
            "ok": True,
            "session_id": store.get_session().id,
            "change": change_dict,
        }
    except workspace_fs.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _persist_chat_turn(user_text: str, done: dict) -> str | None:
    """把 chat_stream 的 done 事件写入 session chat_log（含 steps、变更 id）。返回自动生成的标题（若有）。"""
    from backend.session_store import store

    turn = done["turn"]
    store.append_chat_message("user", user_text, turn=turn)
    store.append_chat_message(
        "assistant",
        done.get("reply", ""),
        turn=turn,
        steps=done.get("steps"),
    )
    changes = done.get("changes") or []
    if changes:
        store.append_chat_changes(turn, [c["id"] for c in changes])
    return done.get("session_title")


@app.patch("/api/session/{session_id}/title")
def api_set_session_title(session_id: str, body: SessionTitleRequest):
    """手动重命名 Session；之后不再被首轮自动标题覆盖。"""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    try:
        saved = store.set_session_title(title, manual=True, session_id=session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "ok": True,
        "session_id": session_id,
        "title": saved,
        "sessions": store.list_sessions(),
        "active_id": store.active_id,
    }


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    try:
        user_text = req.message.strip()
        done = None
        for event in agent.chat_stream(user_text, req.current_file):
            if event.get("type") == "done":
                done = event
            elif event.get("type") == "error":
                raise RuntimeError(event.get("detail", "Agent 调用失败"))
        if not done:
            raise RuntimeError("Agent 未返回结果")

        auto_title = _persist_chat_turn(user_text, done)
        session = store.get_session()
        return ChatResponse(
            reply=done["reply"],
            written_files=done.get("written_files", []),
            session_id=session.id,
            turn=done["turn"],
            changes=done.get("changes", []),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent 调用失败: {e}") from e


@app.post("/api/chat/stream")
def api_chat_stream(req: ChatRequest):
    """SSE：执行过程中推送 step，结束时推送 done 并持久化 Session。"""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    def generate():
        user_text = req.message.strip()
        try:
            for event in agent.chat_stream(user_text, req.current_file):
                if event.get("type") == "done":
                    _persist_chat_turn(user_text, event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done" and event.get("session_title"):
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "session_title",
                                "session_id": event.get("session_id"),
                                "title": event["session_title"],
                                "sessions": store.list_sessions(),
                                "active_id": store.active_id,
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat/reset")
def api_chat_reset():
    """兼容旧接口：等价于新建 Session。"""
    session_id = agent.new_session()
    return {"ok": True, "session_id": session_id}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    from backend.config import HOST, PORT

    print(f"DeepNote Demo: http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
