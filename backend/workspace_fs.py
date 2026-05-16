"""
工作区磁盘读写（仅限 workspace/ 目录）。

所有路径为相对路径；_resolve_safe 防止 .. 逃逸到工作区外。
"""

from __future__ import annotations

from pathlib import Path

from backend.config import WORKSPACE


class WorkspaceError(ValueError):
    """路径非法或文件不存在等业务错误。"""


def _resolve_safe(relative_path: str) -> Path:
    """把相对路径解析为绝对 Path，并确认落在 WORKSPACE 根目录内。"""
    rel = relative_path.replace("\\", "/").lstrip("/")
    if not rel or rel.endswith("/"):
        raise WorkspaceError("无效的文件路径")
    if ".." in Path(rel).parts:
        raise WorkspaceError("不允许访问工作区外的路径")

    target = (WORKSPACE / rel).resolve()
    root = WORKSPACE.resolve()
    if not str(target).startswith(str(root)):
        raise WorkspaceError("不允许访问工作区外的路径")
    return target


def list_files() -> list[str]:
    """递归列出工作区内所有文件的相对路径（POSIX 斜杠）。"""
    if not WORKSPACE.exists():
        WORKSPACE.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for p in sorted(WORKSPACE.rglob("*")):
        if p.is_file():
            paths.append(p.relative_to(WORKSPACE).as_posix())
    return paths


def read_file(relative_path: str) -> str:
    """读取 UTF-8 文本；不存在时抛 WorkspaceError。"""
    path = _resolve_safe(relative_path)
    if not path.is_file():
        raise WorkspaceError(f"文件不存在: {relative_path}")
    return path.read_text(encoding="utf-8")


def write_file(relative_path: str, content: str) -> None:
    """写入 UTF-8 文本；父目录不存在则自动创建。"""
    path = _resolve_safe(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
