# Agent 管理（Web + 飞书统一角色层）— 产品规划

**日期**：2026-05-26（规划，未开发）  
**用途**：明确产品分层——**Agent（租户/角色实例）管理** 套在 **Session（会话）管理** 之上；Web 端可切换 / 新增 / 删除 / 编辑任意 Agent；**Session、记忆、日记 workspace 均按 Agent 隔离**，以便 **单机部署、多人使用**；飞书多机器人是该模型在 IM 侧的延伸。

**关联文档**：

- `2026-06-02-agent-management.md`（**2026-06-02 需求对齐**，以该文档为准）
- `2026-05-26-feishu-multi-bot.md`（多飞书 App 技术落地，术语对齐本文 **Agent**）
- `2026-05-26-feishu-slash-commands.md`（Agent 内的 Session `/` 指令）
- `2026-05-25-feishu-roadmap.md`

**状态标记**：`待办` | `进行中` | `已完成` | `跳过`

---

## 1. 理解确认（产品一句话）

> **DiaryMaster 不再只有「全局一个 Agent + 多段会话 + 一本共享日记」。**  
> 运维者在一台机器部署一次；**每位使用者对应一个 Agent**，其下再有多段 Session。  
> **记忆、日记文件、对话历史、可选飞书机器人** 均在 Agent 边界内隔离，互不可见。

```
服务 (DiaryMaster) — 单实例部署
 ├── 全局：API Key、UI 主题（可选：实例级管理员配置）
 ├── Agent A「张三」              ← 一位使用者 / 一个租户
 │     ├── workspace/             ← 张三的日记与笔记（隔离）
 │     ├── USER.md / MEMORY.md
 │     ├── 人设 / 模型 / 工具策略
 │     ├── Session 1, 2, 3…
 │     └── 飞书 App 绑定（可选，张三私聊此 bot）
 ├── Agent B「李四」
 │     └── workspace/ …           ← 与李四完全隔离
 └── Agent C「默认」              ← 迁移承接现有单用户数据
```

**产品定位调整（2026-05-26）**：

| 原方案 | 新方案 |
| ------ | ------ |
| 多 Agent **共享** 同一 `workspace/`（多角色共写一本日记） | 多 Agent **各用** `data/agents/{agent_id}/workspace/` |
| Agent ≈ 同一人的不同「角色」 | Agent ≈ **一个使用者（租户）**；同一人多种对话风格用 **多 Session**，不必多 Agent |
| 单机只能服务一个「日记主人」 | **一人部署，多人使用**（家人/小团队各 Agent 各日记） |

**已理解并写入本规划的需求**：

| 需求 | 说明 |
| ---- | ---- |
| Web 切换任一 Agent | 顶栏或侧栏 Agent 选择器；切换后 Session 列表、聊天、记忆均 scoped 到该 Agent |
| 增加 Agent | 创建新使用者实例（名称、人设、空 workspace 或从模板复制） |
| 删除 Agent | 删除该使用者全部数据：Session、记忆、**workspace 目录**、飞书绑定（需二次确认） |
| 管理 Agent 内容 | 编辑 role_prompt、USER/MEMORY、模型/工具、飞书卡片行为等 **按 Agent** 配置 |
| 会话管理降级一层 | 「新建对话 / 历史会话 / `/switch`」仅在 **当前 Agent** 内生效 |

---

## 2. 现状 vs 目标

| 层级 | 现状 | 目标 |
| ---- | ---- | ---- |
| **Agent** | 隐含单一（全局 SYSTEM_PROMPT + 一份 MEMORY） | 显式 **Agent 注册表**，多条可 CRUD |
| **Session** | Web 侧栏 / 飞书 `bindings` 直接对 `session_store` | Session **归属 agent_id** |
| **记忆** | `data/memories/` 全局一份 | `data/agents/{agent_id}/memories/` |
| **日记 / workspace** | 全局 `workspace/` | **`data/agents/{agent_id}/workspace/`** |
| **飞书** | 单 App，单绑定文件 | 每个 Agent **可选** 绑定一个飞书 App（建议一人一 App） |
| **Web UI** | 只有 Session tabs + 设置页 | **Agent 切换器** + Agent 设置 + Session（二级） |
| **设置页** | API Key + 单组飞书 + 全局 MEMORY 编辑 | 全局（API Key、主题）+ **选中 Agent** 的配置与记忆 |

---

## 3. Agent 实体（数据模型草案）

```python
@dataclass
class AgentProfile:
    agent_id: str              # 稳定 id，如 default / writer / coach
    display_name: str          # 「写作助手」
    description: str           # 简短说明（UI 用）
    role_prompt: str           # 追加 system prompt 的人设与职责
    created_at: str
    updated_at: str
    enabled: bool              # 禁用后 Web 不可选、飞书 WS 不连

    # 可选渠道
    feishu: FeishuBinding | None   # app_id, app_secret, enabled

    # 可选行为
    model_id: str | None
    thinking_enabled: bool | None
    tools_policy: dict | None       # 如禁 delete_path
    feishu_channel_config: dict | None  # reply_display, card_backend（现 config.json）

    # 元数据
    icon: str | None           # emoji 或内置图标 key
    sort_order: int
```

**注册表路径**：`data/agents/registry.json`（Agent 列表 + 摘要）  
**Agent 私有数据**：`data/agents/{agent_id}/`

```text
data/agents/{agent_id}/
  workspace/           # 该 Agent 独占日记树（read_file / 文件树 API 根）
  memories/
    USER.md
    MEMORY.md
  sessions/
    {session_id}.json
  feishu/
    bindings.json
    config.json
    activity.json
  meta.json            # 可选：创建时间、备注
```

**默认 Agent**：首次启动或迁移后保留 `agent_id=default`，现有根目录 `workspace/`、`data/sessions/`、`data/memories/` **迁入** `data/agents/default/`。

---

## 4. Web 端交互（规划）

### 4.1 信息架构

```text
顶栏 / 侧栏
├── [Agent 切换 ▼]  张三 | 李四 | + 新建使用者
├── 文件树（仅当前 Agent 的 workspace/）
├── Session tabs（仅当前 Agent）
├── [+ 新建对话]    → 在当前 Agent 下 new_session
└── [☰ 历史会话]    → 列表 scoped agent_id

设置 / Agent 管理（新入口或设置页 Tab）
├── 全局：API Key、UI 主题
└── Agent「写作助手」
    ├── 名称、描述、人设 prompt
    ├── USER.md / MEMORY.md（迁出全局设置页或按 Agent 切换编辑）
    ├── 模型与工具策略
    ├── 飞书：App ID/Secret、检测连通、卡片后端
    └── 危险：删除此 Agent
```

### 4.2 核心操作

| 操作 | Web 行为 | 后端 |
| ---- | -------- | ---- |
| 切换 Agent | 更新 `active_agent_id`；加载该 Agent 的 Session 列表与 active Session | `PUT /api/agents/active` |
| 新建 Agent | 向导：显示名 + 可选人设 + 空 workspace 或复制模板 | `POST /api/agents` |
| 删除 Agent | 确认后删除 `data/agents/{id}/` 整棵树 | `DELETE /api/agents/{id}` |
| 编辑 Agent | 表单保存 role_prompt、飞书凭证等 | `PUT /api/agents/{id}` |
| 新建 Session | 不变，但 `new_session(agent_id=current)` | 扩展 session API |
| 切换 Session | 不变，scoped 当前 Agent | 扩展 session API |

### 4.3 与现有 UI 的关系

- 现有 **Session tabs / 历史列表 / 上下文圆环** 保留，外层包 **Agent 上下文**。
- 设置页「长期记忆」改为 **随当前 Agent** 或 **Agent 管理子页** 编辑，避免改 A 的记忆误写全局。
- 切换 Agent 时 **文件树、编辑器、Session、聊天** 全部 reload，避免路径串租户。
- localStorage 可存 `diarymaster-active-agent-id`（与后端 `active_agent_id` 同步）。

### 4.4 单机多人使用（部署视角）

| 角色 | 行为 |
| ---- | ---- |
| **部署者** | 本机 `python run.py`，配置全局 API Key；创建 Agent「张三」「李四」 |
| **张三** | Web 选 Agent 张三，或飞书私聊绑定张三的 bot；只见张三的日记与对话 |
| **李四** | 同上，数据与张三完全隔离 |
| **同一人要多个话题** | 在同一 Agent 下 **多 Session**（`/new`、`/switch`），**不要**为同一用户建多个 Agent |

后续若需 **登录鉴权**（Web 密码 / 飞书 open_id 白名单），在 Agent 层之上加 **访问控制**，不改变「一 Agent 一 workspace」模型。

---

## 5. 飞书 / Agent 工具 / `/` 指令（统一上下文）

| 入口 | Agent 上下文来源 |
| ---- | ---------------- |
| Web 聊天 | 用户当前选中的 `active_agent_id` |
| 飞书消息 | 事件 `app_id` → 查 Agent.feishu.app_id → `agent_id` |
| `/sessions` 等指令 | 当前消息所属 Agent |
| Agent `@tool` | `_chat_context.agent_id`（与 channel、open_id 并列） |

**工具扩展（规划）**：

- `list_agents` / `get_current_agent` / `create_agent` / `update_agent` / `delete_agent`（删除需确认或仅允许删非 default）
- 现有 `list_chat_sessions` / `new_chat_session` 等 **必须带 agent_id**（默认当前上下文）

详见 `2026-05-26-feishu-slash-commands.md`（Session 层）与 `2026-05-26-feishu-multi-bot.md`（飞书连接层）。

---

## 6. 隔离 workspace（日记与工作区）

每个 Agent 拥有 **独立 workspace 根目录**；`read_file` / `edit_file` / `write_file` / 文件树 API 在运行时解析为：

```text
effective_root = data/agents/{current_agent_id}/workspace/
```

- **产品含义**：一人部署，多人各写各的日记，Agent 工具不会跨租户读写路径。
- **实现要点**：
  - `backend/config.py` 或 `backend/agents/context.py` 提供 `get_workspace_root(agent_id)`，替代全局 `WORKSPACE` 常量。
  - `workspace_fs`、文件 API、`current_file` 均在 **当前 agent 上下文** 下解析相对路径。
  - 切换 Agent 时前端清空已打开文件 tab，防止编辑路径残留。
- **复制 / 模板**：新建 Agent 时可选择「空目录」或「从 default 复制 workspace 骨架」（不复制 Session/记忆，除非显式勾选）。

**跨 Agent 共享文件**：首版 **不做**。若将来需要「家庭公共目录」，另增 **实例级** `data/shared/` 与只读工具，不破坏租户隔离。

> **2026-06-02 更新**：工作区改为 **可独立可共用**，见 `2026-06-02-agent-management.md` §1、§4.2。

---

## 7. API 草案（Web Agent 管理）

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | `/api/agents` | 列表 + 当前 active 标记 |
| GET | `/api/agents/{id}` | 详情（含脱敏飞书、记忆占用） |
| POST | `/api/agents` | 新建 |
| PUT | `/api/agents/{id}` | 更新配置 |
| DELETE | `/api/agents/{id}` | 删除（禁止删最后一个；default 可禁删） |
| PUT | `/api/agents/active` | `{ "agent_id": "writer" }` |
| GET | `/api/agents/{id}/sessions` | 该 Agent 下 Session 列表（替代或包装全局 list） |
| GET | `/api/agents/{id}/workspace` | 文件树（scoped） |
| GET/PUT | `/api/agents/{id}/memories` | 该 Agent USER/MEMORY |

现有 `/api/files/*` 逐步改为依赖 **active agent**（Query `agent_id` 或 Header `X-Agent-Id`）。

---

## 8. 后端模块归属

| 模块 | 建议路径 | 职责 |
| ---- | -------- | ---- |
| Agent 注册表 | `backend/agents/` 子包 | registry、profile、CRUD API |
| Session | `backend/session_store.py` → 收编或包一层 | `agent_id` scoped 读写 |
| Memory | `backend/memory/store.py` | 路径含 `agent_id` |
| Workspace | `backend/workspace_fs.py` + `config` | **`get_workspace_root(agent_id)`** |
| 飞书 | `backend/channels/feishu/` | dispatch 解析 app_id → agent |
| Agent 循环 | `backend/agent.py` | `ChatContext(agent_id, channel, open_id)` |
| Web | `web/app.js` | Agent 切换器、管理 UI |

遵循仓库分层：**Agent 领域新建 `backend/agents/`**，不散落 `agent_registry.py` 于根目录。

---

## 9. 迁移与实施顺序（建议）

与飞书多 bot、slash 指令的推荐顺序：

| 阶段 | 内容 | 文档 |
| ---- | ---- | ---- |
| **P0** | 单 Agent 内 Session `/` 指令 + session_ops 预留 `agent_id` | slash-commands |
| **P1** | 引入 `AgentProfile` + 迁移 default；Session/Memory/**workspace** 路径加 agent_id | 本文 §9 |
| **P2** | Web Agent 切换器 + CRUD；**切换 Agent 时文件树 reload** | 本文 §4、§7 |
| **P3** | 第二 Agent + 全隔离验收（含 workspace 互不可见） | 本文 + multi-bot M1 |
| **P4** | 多飞书 App 各绑一 Agent + 多 WS | multi-bot |

**不必等 P4 才做 Web Agent 管理**：Web 可先支持多 Agent（仅浏览器），飞书后绑。

> **2026-06-02**：实施顺序与验收以 `2026-06-02-agent-management.md` §7、§8 为准。

---

## 10. 验收标准（P2 完成时）

- [ ] Web 顶栏可切换 Agent；切换后会话列表、聊天区、记忆编辑均对应该 Agent。
- [ ] 可新建 Agent（至少：名称 + 人设），新建后自动成为 active。
- [ ] 可编辑 Agent 名称、人设、该 Agent 的 USER/MEMORY。
- [ ] 可删除非 default Agent（有确认）；其 Session、记忆、**workspace 目录** 一并删除。
- [ ] Agent A / B 各建 Session，切换后对话互不可见。
- [ ] Agent A / B 的 MEMORY 独立。
- [ ] Agent A 创建 `日记.md`，Agent B 文件树与 read_file **不可见**该文件；各自编辑互不影响。
- [ ] （若已接飞书）各 App 仅路由到对应 Agent。

---

## 11. 非目标（首版 Agent 管理不做）

- Agent 之间 **共享或自动同步** workspace / 记忆
- Agent 分组、组织级权限、计费
- Web 登录鉴权（可 P5 单独做 open_id / 密码与 Agent 绑定）
- 拖拽 Session 跨 Agent 迁移
- 跨 Agent 的全局全文检索

---

## 12. 术语对照（避免文档混用）

| 用户说法 | 统一术语 | 备注 |
| -------- | -------- | ---- |
| Agent / 使用者 / 租户 | **Agent**（`agent_id`） | 一人一 Agent（单机多人） |
| 飞书机器人 | Agent 的 **渠道绑定** | 建议一人一 App |
| 对话 / Session | **Session** | 同一 Agent 内多话题 |
| 日记 / 工作区 | **agent workspace** | `data/agents/{id}/workspace/` |

---

## 13. 变更记录

| 日期 | 说明 |
| ---- | ---- |
| 2026-05-26 | 初版：Agent 层套 Session 层；Web CRUD/切换/内容管理；与多飞书、slash 指令对齐 |
| 2026-05-26 | **workspace 改为按 Agent 隔离**，支持单机多人部署；Agent 语义对齐「使用者/租户」 |
| 2026-06-02 | 需求对齐迁至 `2026-06-02-agent-management.md`；本文保留历史规划并指向新文档 |
