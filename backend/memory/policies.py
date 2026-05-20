"""注入 Agent SYSTEM_PROMPT 的记忆与历史检索策略说明（与 @tool docstring 互补）。"""

MEMORY_TOOL_POLICY = """
长期记忆（memory 工具，data/memories/USER.md 与 MEMORY.md）：
- **应记**：用户偏好、纠正、长期习惯、工作区整理/命名等元约定（简短一句，非笔记正文）。
- **user** store：偏好、称呼、纠正类；**memory** store：习惯、工作区约定类。
- **不记**：笔记全文、当前任务进度、临时 TODO、会话内一次性上下文。
- 占用超过约 80% 时，先用 replace/remove 合并或精简相近条目（consolidate），再 add 新条。
- 笔记正文仍用 read_file / edit_file；长期事实用 memory，不要用 write_file 写入 memories 目录。"""

SEARCH_TOOL_POLICY = """
历史对话检索（search_past_chats）：
- **应用**：用户问「之前哪次说过 X」「以前聊过什么」等跨 Session 回忆；在 data/sessions 的 chat_log 里做关键词搜索。
- **不用**：查笔记正文（用 read_file）、查长期偏好/习惯（用 memory）、切换会话（本工具只读，不调用 switch_session）。"""
