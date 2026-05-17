"""
工作区磁盘读写（仅限 workspace/ 目录）。

所有路径为相对路径；_resolve_safe 防止 .. 逃逸到工作区外。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from backend.config import WORKSPACE


class WorkspaceError(ValueError):
    """路径非法或文件不存在等业务错误。"""


def _normalize_rel(relative_path: str) -> str:
    """规范化相对路径：正斜杠、去首尾 /、禁止 .. 与空段。"""
    rel = relative_path.replace("\\", "/").strip()
    while "//" in rel:
        rel = rel.replace("//", "/")
    rel = rel.strip("/")
    if not rel:
        raise WorkspaceError("路径不能为空")
    parts = Path(rel).parts
    if ".." in parts or any(p in (".", "") for p in parts):
        raise WorkspaceError("无效的文件路径")
    return rel


def _resolve_safe(relative_path: str) -> Path:
    """把相对路径解析为绝对 Path，并确认落在 WORKSPACE 根目录内。"""
    rel = _normalize_rel(relative_path)
    target = (WORKSPACE / rel).resolve()
    root = WORKSPACE.resolve()
    if not str(target).startswith(str(root)):
        raise WorkspaceError("不允许访问工作区外的路径")
    return target


def _ensure_workspace() -> Path:
    """确保 workspace 目录存在并返回其 Path。"""
    if not WORKSPACE.exists():
        WORKSPACE.mkdir(parents=True, exist_ok=True)
    return WORKSPACE


def list_files() -> list[str]:
    """递归列出工作区内所有文件的相对路径（POSIX 斜杠）。"""
    root = _ensure_workspace()
    paths: list[str] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not _is_ignored(p):
            paths.append(p.relative_to(root).as_posix())
    return paths


def _is_ignored(path: Path) -> bool:
    """是否忽略该路径（以 . 开头的目录/文件，如 .git）。"""
    return any(part.startswith(".") for part in path.parts)


def list_tree() -> list[dict[str, Any]]:
    """工作区目录树（含空文件夹）。"""

    def walk_dir(dir_path: Path, prefix: str) -> list[dict[str, Any]]:
        """递归构建单层目录下的文件/子目录节点列表。"""
        items: list[dict[str, Any]] = []
        try:
            entries = sorted(
                dir_path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            return items
        for entry in entries:
            if entry.name.startswith("."):
                continue
            rel = f"{prefix}/{entry.name}" if prefix else entry.name
            if entry.is_dir():
                items.append(
                    {
                        "type": "dir",
                        "name": entry.name,
                        "path": rel,
                        "children": walk_dir(entry, rel),
                    }
                )
            elif entry.is_file():
                items.append(
                    {"type": "file", "name": entry.name, "path": rel}
                )
        return items

    return walk_dir(_ensure_workspace(), "")


def create_directory(relative_path: str) -> str:
    """在工作区内新建文件夹（可多级，如 notes/周报）。返回规范化相对路径。"""
    rel = _normalize_rel(relative_path)
    path = _resolve_safe(rel)
    if path.exists():
        if path.is_dir():
            raise WorkspaceError(f"文件夹已存在: {rel}")
        raise WorkspaceError(f"同名文件已存在: {rel}")
    path.mkdir(parents=True, exist_ok=True)
    return rel


def create_file(relative_path: str, content: str = "") -> str:
    """新建文件；父目录不存在则自动创建。已存在则抛 WorkspaceError。"""
    rel = _normalize_rel(relative_path)
    path = _resolve_safe(rel)
    if path.exists():
        raise WorkspaceError(f"已存在: {rel}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8")
    return rel


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


def delete_path(relative_path: str) -> str:
    """删除工作区内的文件或文件夹（目录递归删除）。返回被删路径。"""
    rel = _normalize_rel(relative_path)
    path = _resolve_safe(rel)
    root = WORKSPACE.resolve()
    if path.resolve() == root:
        raise WorkspaceError("不能删除工作区根目录")
    if not path.exists():
        raise WorkspaceError(f"不存在: {rel}")
    if path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        raise WorkspaceError(f"无法删除: {rel}")
    return rel
