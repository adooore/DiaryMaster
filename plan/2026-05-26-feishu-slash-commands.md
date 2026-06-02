# 飞书端 `/` 指令与会话管理 — 开发计划

**日期**：2026-05-26（计划）  
**用途**：明日开发任务说明。在飞书 IM 中支持 `/` 系列指令管理 Session，并将同等能力暴露为 Agent `@tool`，与 Web UI 共用 `session_store`。

**关联文档**：

- `done-2026-05-25-feishu.md`、`2026-05-25-feishu-roadmap.md`
- `2026-06-02-agent-management.md`（Agent 层总纲；Session 指令 scoped 到当前 Agent）

**状态标记**：`待办` | `进行中` | `已完成` | `跳过`

---

## 1. 背景与动机

### 1.1 现状（2026-05-25 止）

| 项 | 行为 |
| -- | ---- |
| 绑定 | `data/feishu/bindings.json`：`open_id` → **唯一** `session_id` |
| 首条消息 | 无绑定则 `new_session()` 并写入绑定 |
| 后续消息 | 永远 `switch_session(已绑定 id)`，对话续在同一 Session |
| 与 Web | 共用 `session_store`，飞书处理时会改全局 `active_session_id`，**不与 Web 当前选中会话自动同步** |
| 换会话 | **无**用户侧入口（只能改 bindings 或删 Session 文件） |

### 1.2 目标

1. 飞书用户发送 **`/` 开头指令**时，走**指令分支**，不调用 Agent（除非设计成「未知指令当普通聊天」——默认 **不** 当聊天）。
2. 支持至少：**查会话列表、切换会话、新建会话**（可选：`/current`、`/help`）。
3. 同一套逻辑封装为 **Agent 工具**，Web / 飞书 Agent 均可调用（飞书侧需同步更新 `bindings.json` 中的 active 会话）。
4. 指令回复仍走现有飞书卡片/文本通道，短文本即可（不必跑完整 Agent 流）。

---

## 2. 指令设计（草案）

前缀：行首 `/`（可 trim）；**仅处理纯文本消息**。

| 指令 | 别名（可选） | 作用 | 示例 |
| ---- | ------------ | ---- | ---- |
| `/help` | `/帮助` | 列出可用指令 | `/help` |
| `/sessions` | `/会话` `/列表` | 列出 Session 摘要（当前项标记 ★） | `/sessions` |
| `/new` | `/新建` | 新建 Session 并设为该用户当前会话 | `/new` |
| `/switch` | `/切换` | 切换到指定 Session | `/switch abc123` 或 `/switch 2` |
| `/current` | `/当前` | 显示当前 Session id、标题、轮次 | `/current` |

### 2.1 `/switch` 参数规则

- **完整 id**：匹配 `session_id`（支持前缀匹配，如 Web 侧常用前 8 位，需与 `session_store` 一致）。
- **序号**：`/switch 2` 表示 `/sessions` 列表中的第 2 条（1-based，与列表展示顺序一致：`list_sessions` 按创建时间倒序）。
- 无效 id / 序号：回复中文错误，不切换。

### 2.2 `/sessions` 展示格式（飞书文本/卡片）

建议每条一行，控制长度（最多展示 15～20 条 + 「共 N 条」）：

```text
★ [3] diary-abc123… | 日记草稿 | turn=5
  [2] def456… | 飞书问答 | turn=12
  [1] …
当前：第 1 条为默认激活（★）。切换：/switch 2 或 /switch <id前缀>
```

### 2.3 未识别指令

- 回复：`未知指令，发送 /help 查看帮助。`  
- **不**进入 Agent（避免 `/foo` 被当成写作题目）。

---

## 3. Session 绑定模型（演进）

### 3.1 现状结构

```json
{
  "ou_xxxxxxxx": "session-uuid-aaa"
}
```

### 3.2 建议结构（向后兼容）

```json
{
  "ou_xxxxxxxx": {
    "active_session_id": "session-uuid-aaa",
    "updated_at": "2026-05-26T12:00:00+00:00"
  }
}
```

- 读取时：若为 string，视为 `active_session_id`（兼容旧文件）。
- 写入时：统一用 object。
- **不**强制维护「飞书专属 Session 列表」：列表仍用全局 `store.list_sessions()`（本机单用户场景）；若未来多租户再加分域。

### 3.3 核心 API（`bind.py` 扩展）

| 函数 | 说明 |
| ---- | ---- |
| `get_active_session_id(open_id)` | 读当前绑定 |
| `set_active_session(open_id, session_id)` | 切换并持久化；校验 Session 存在 |
| `create_and_bind_session(open_id)` | `new_session()` + 写入 active |
| `activate_session_for_open_id(open_id)` | **保留**；行为改为「ensure active 存在且可 switch」，无绑定则 `create_and_bind` |

`dispatch._process_message` 在调用 Agent 前：

```text
若 text 匹配 slash 指令 → handle_slash_command(...) → return
否则 → activate_session_for_open_id → chat_once
```

---

## 4. Agent 工具（与指令共用实现）

原则：**业务逻辑放 `backend/channels/feishu/session_ops.py`（或 `backend/session_ops.py`）**，`dispatch` 与 `@tool` 只调同一层。

### 4.1 建议工具

| 工具名 | 参数 | 返回 | 飞书 open_id |
| ------ | ---- | ---- | ------------ |
| `list_chat_sessions` | `limit: int = 15` | 格式化 Session 列表文本 | 不需要 |
| `get_current_chat_session` | — | 当前 active Session 摘要 | 不需要 |
| `new_chat_session` | — | 新 Session id + 标题 | **若 `channel=feishu`**：从上下文取 `open_id` 并 `set_active` |
| `switch_chat_session` | `session_id_or_index: str` | 切换结果说明 | 同上 |

### 4.2 飞书上下文传递

- `dispatch` 已有 `open_id`；`chat_once` 可增加可选 `feishu_open_id: str | None`，或在模块级 `_feishu_open_id`（与现有 `_chat_channel` 类似，仅 IM 回合内有效）。
- Agent 工具内：若 `_chat_channel == "feishu"` 且存在 `open_id`，则 `switch` / `new` 同步写 `bindings.json`；Web 渠道只改 `store.active_id`。

### 4.3 注册位置

- 工具定义：`backend/channels/feishu/session_tool.py`（或并入 `tool.py` 若文件不大）。
- `agent.py` `_build_agent` tools 列表追加上述 4 个（与 `configure_feishu_channel` 并列）。

Docstring 用中文，说明 Web/飞书均可调用、飞书会同步绑定。

---

## 5. 代码结构（建议）

```text
backend/channels/feishu/
  bind.py              # 扩展 active_session 读写、兼容旧 JSON
  session_ops.py       # NEW：list / current / new / switch 纯逻辑 + 格式化
  slash.py             # NEW：解析 /help、/sessions…，调 session_ops，返回回复文本
  session_tool.py      # NEW：@tool 包装 session_ops
  dispatch.py          # 消息入口：slash 分支 → 否则 Agent
  tool.py              # 已有 configure_feishu_channel

backend/agent.py       # 注册 session 工具；chat_once 传入 feishu open_id（可选）
```

**不新建**根目录 `session_ops.py`（遵循 backend 子包分层：飞书会话操作归 `channels/feishu/`；若 Web 也要工具，工具内部仍调 `session_store`，飞书绑定仅在 `channel=feishu` 分支写 bind）。

---

## 6. 任务拆分

| ID | 任务 | 状态 | 依赖 |
| -- | ---- | ---- | ---- |
| S1 | `bind.py` 演进 + 读写兼容测试（手工） | 待办 | — |
| S2 | `session_ops.py`：list / current / new / switch | 待办 | S1 |
| S3 | `slash.py` 解析与中文回复模板 | 待办 | S2 |
| S4 | `dispatch.py` 接入 slash（指令不走 Agent） | 待办 | S3 |
| S5 | `session_tool.py` + `agent.py` 注册 | 待办 | S2 |
| S6 | `chat_once` / `_chat_stream` 传递 `feishu_open_id` | 待办 | S5 |
| S7 | 联调：飞书 `/sessions` `/new` `/switch` | 待办 | S4 |
| S8 | 联调：飞书对话中让 Agent「帮我新建一个会话」走 tool | 待办 | S5,S6 |
| S9 | 更新 `2026-05-25-feishu-roadmap.md` 变更记录（可选） | 待办 | S7 |

**建议顺序**：S1 → S2 → S3 → S4 → S7；并行 S5 → S6 → S8。

---

## 7. 验收标准

### 7.1 飞书指令

- [ ] `/help` 返回指令列表（中文）。
- [ ] `/sessions` 列出本机 Session，当前绑定项有明确标记。
- [ ] `/new` 后下一条普通消息进入**新** Session（`turn` 从 0/1 开始，与旧 Session 隔离）。
- [ ] `/switch <id>` 与 `/switch <序号>` 均可切换，之后 Agent 回复写入目标 Session。
- [ ] `/current` 与切换后状态一致。
- [ ] 未知 `/xxx` 不调用模型，有友好提示。

### 7.2 Agent 工具

- [ ] Web 对话：Agent 调用 `new_chat_session` / `switch_chat_session` 改变 Web 当前 Session（与侧边栏行为一致或说明差异）。
- [ ] 飞书对话：同上工具调用后，该用户 `bindings.json` 的 active 与 `store.active_id` 一致。
- [ ] `list_chat_sessions` 输出与 `/sessions` 信息等价（格式可略不同）。

### 7.3 边界

- [ ] 切换不存在的 Session：中文错误，active 不变。
- [ ] 删除 Session 后绑定失效：`activate_session_for_open_id` 自动新建（现有逻辑保留）。
- [ ] 同用户并发：仍受 `open_id` 锁约束；指令处理应快速完成，不长时间占锁。

---

## 8. 非目标（明日不做）

- 群聊独立 Session 策略（roadmap B3）——仍按发送者 `open_id` 绑定 active；群上下文策略另开任务。
- 指令权限分级（管理员才能 `/switch` 别人的 Session）——本机单用户无需。
- Web UI 设置页管理飞书绑定关系——可后续做。
- `/delete` 删除 Session——可 S2 后按需加。

---

## 9. 实现备注

### 9.1 与 Web Session 列表对齐

- 列表数据源：`backend.session_store.store.list_sessions()`（已含 `is_active`）。
- 序号：与 API `GET /api/sessions` 排序一致（创建时间倒序），避免飞书 `/switch 2` 与 Web 列表对不上。

### 9.2 回复形式

- MVP：指令回复用 **`send_text` 短文本**即可（无需卡片），降低明日工作量。
- 若需统一品牌：可后续改为简单卡片或引用当前 CardKit 主题。

### 9.3 测试建议

1. 飞书私聊：`/sessions` → `/new` → 发「记住数字 42」→ `/switch` 回旧 Session → 问「刚才数字」应无 42。
2. 飞书：对 Agent 说「列出所有会话并切换到第 2 个」→ 应触发 tool 而非幻觉。
3. 改 `bindings.json` 为旧 string 格式 → 仍能 `/current` 正常。

---

## 10. 变更记录

| 日期 | 说明 |
| ---- | ---- |
| 2026-05-26 | 初版：/` 指令（查/切/新建会话）+ Agent tool 共用 session_ops；绑定 JSON 演进方案 |
