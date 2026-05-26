# Agent 管理（Web + 飞书统一角色层）— 产品规划

**日期**：2026-05-26（规划，未开发）  
**用途**：明确产品分层——**Agent（角色）管理** 套在 **Session（会话）管理** 之上；Web 端可切换 / 新增 / 删除 / 编辑任意 Agent；飞书多机器人是该模型在 IM 侧的延伸，而非另一套平行概念。

**关联文档**：

- `2026-05-26-feishu-multi-bot.md`（多飞书 App 技术落地，术语对齐本文 **Agent**）
- `2026-05-26-feishu-slash-commands.md`（Agent 内的 Session `/` 指令）
- `2026-05-25-feishu-roadmap.md`

**状态标记**：`待办` | `进行中` | `已完成` | `跳过`

---

## 1. 理解确认（产品一句话）

> **DiaryMaster 不再只有「全局一个 Agent + 多段会话」。**  
> 用户先选 **Agent（角色实例）**，再在角色下管理 **多段 Session**；Web 与飞书共用同一 Agent _registry，仅渠道不同。

```
服务 (DiaryMaster)
 └── Agent A「写作助手」          ← 新增：可 CRUD、可切换
 │     ├── 长期记忆 USER / MEMORY   ← 归属 Agent，非全局
 │     ├── 人设 / 工具策略 / 可选飞书 App
 │     ├── Session 1, 2, 3…         ← 现有会话管理能力下沉到这一层
 │     └── 飞书 bindings（若有）
 └── Agent B「复盘教练」
 └── Agent C「默认 Web」           ← 可无飞书，仅浏览器使用
 └── workspace/（共享日记文件）     ← 所有 Agent 共用
```

**已理解并写入本规划的需求**：

| 需求 | 说明 |
| ---- | ---- |
| Web 切换任一 Agent | 顶栏或侧栏 Agent 选择器；切换后 Session 列表、聊天、记忆均 scoped 到该 Agent |
| 增加 Agent | 创建新角色（名称、人设、可选绑定飞书凭证） |
| 删除 Agent | 删除角色及其 Session / 记忆 / 绑定（需确认弹窗；workspace 文件不删） |
| 管理 Agent 内容 | 编辑 role_prompt、USER/MEMORY、模型/工具、飞书卡片行为等 **按 Agent** 配置 |
| 会话管理降级一层 | 「新建对话 / 历史会话 / `/switch`」仅在 **当前 Agent** 内生效 |

---

## 2. 现状 vs 目标

| 层级 | 现状 | 目标 |
| ---- | ---- | ---- |
| **Agent** | 隐含单一（全局 SYSTEM_PROMPT + 一份 MEMORY） | 显式 **Agent 注册表**，多条可 CRUD |
| **Session** | Web 侧栏 / 飞书 `bindings` 直接对 `session_store` | Session **归属 agent_id** |
| **记忆** | `data/memories/` 全局一份 | `data/agents/{agent_id}/memories/` |
| **飞书** | 单 App，单绑定文件 | 每个 Agent **可选** 绑定一个飞书 App |
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
**Agent 私有数据**：`data/agents/{agent_id}/`（memories、sessions、feishu/bindings、activity…）

**默认 Agent**：首次启动或迁移后保留一条 `agent_id=default`（承接现有全部 Session / 记忆 / 飞书配置）。

---

## 4. Web 端交互（规划）

### 4.1 信息架构

```text
顶栏 / 侧栏
├── [Agent 切换 ▼]  写作助手 | 复盘教练 | + 新建 Agent
├── Session tabs（仅当前 Agent 的已打开会话）
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
| 新建 Agent | 向导：名称 + 人设 + 是否复制某 Agent 记忆 | `POST /api/agents` |
| 删除 Agent | 确认后删目录；若删的是当前 Agent 则切到 default | `DELETE /api/agents/{id}` |
| 编辑 Agent | 表单保存 role_prompt、飞书凭证等 | `PUT /api/agents/{id}` |
| 新建 Session | 不变，但 `new_session(agent_id=current)` | 扩展 session API |
| 切换 Session | 不变，scoped 当前 Agent | 扩展 session API |

### 4.3 与现有 UI 的关系

- 现有 **Session tabs / 历史列表 / 上下文圆环** 保留，外层包 **Agent 上下文**。
- 设置页「长期记忆」改为 **随当前 Agent** 或 **Agent 管理子页** 编辑，避免改 A 的记忆误写全局。
- localStorage 可存 `diarymaster-active-agent-id`（与后端 `active_agent_id` 同步，类似 theme）。

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

## 6. 共享 workspace（不变）

所有 Agent 的 `read_file` / `edit_file` / `write_file` 仍指向 **同一 `workspace/`**。

- 产品含义：多个「角色」共同维护同一本日记 / 项目文件。
- 实现注意：并发写同一文件需保留 workspace 锁；Agent 间不隔离路径。

若未来需要「某 Agent 只读日记」，在 **Agent.tools_policy** 限制写工具，而非拆 workspace。

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
| GET/PUT | `/api/agents/{id}/memories` | 该 Agent USER/MEMORY |

Session 相关现有 `/api/session/*` 逐步改为 **隐式或显式 agent_id**（Query 或 Header `X-Agent-Id`，默认 active）。

---

## 8. 后端模块归属

| 模块 | 建议路径 | 职责 |
| ---- | -------- | ---- |
| Agent 注册表 | `backend/agents/` 子包 | registry、profile、CRUD API |
| Session | `backend/session_store.py` → 收编或包一层 | `agent_id` scoped 读写 |
| Memory | `backend/memory/store.py` | 路径含 `agent_id` |
| 飞书 | `backend/channels/feishu/` | dispatch 解析 app_id → agent；WS 按 Agent 列表启动 |
| Agent 循环 | `backend/agent.py` | `ChatContext(agent_id, channel, open_id)` |
| Web | `web/app.js` | Agent 切换器、管理 UI |

遵循仓库分层：**Agent 领域新建 `backend/agents/`**，不散落 `agent_registry.py` 于根目录。

---

## 9. 迁移与实施顺序（建议）

与飞书多 bot、slash 指令的推荐顺序：

| 阶段 | 内容 | 文档 |
| ---- | ---- | ---- |
| **P0** | 单 Agent 内 Session `/` 指令 + session_ops 预留 `agent_id` | slash-commands |
| **P1** | 引入 `AgentProfile` + 迁移 default Agent；Session/Memory 路径加 agent_id（仅 default 可见） | 本文 §9 |
| **P2** | Web Agent 切换器 + CRUD UI + API | 本文 §4、§7 |
| **P3** | 第二 Agent + 记忆/Session 隔离验收 | 本文 + multi-bot M1 |
| **P4** | 多飞书 App 各绑一 Agent + 多 WS | multi-bot |

**不必等 P4 才做 Web Agent 管理**：Web 可先支持多 Agent（仅浏览器），飞书后绑。

---

## 10. 验收标准（P2 完成时）

- [ ] Web 顶栏可切换 Agent；切换后会话列表、聊天区、记忆编辑均对应该 Agent。
- [ ] 可新建 Agent（至少：名称 + 人设），新建后自动成为 active。
- [ ] 可编辑 Agent 名称、人设、该 Agent 的 USER/MEMORY。
- [ ] 可删除非 default Agent（有确认）；其 Session/记忆目录清除，workspace 不动。
- [ ] Agent A / B 各建 Session 并写入不同对话内容，切换 Agent 后互不可见。
- [ ] Agent A / B 的 MEMORY 独立；切换后 Agent 行为符合各自记忆。
- [ ] 两 Agent 均可读写同一 `workspace/` 文件且内容一致。
- [ ] （若已接飞书）飞书 App 仅路由到绑定 Agent；未绑定 App 的 Agent 仅 Web 可用。

---

## 11. 非目标（首版 Agent 管理不做）

- Agent 之间 **自动同步/合并记忆**
- 每 Agent 独立 workspace
- Agent 分组、权限、多用户
- 拖拽排序 Session 跨 Agent 移动（可后续加「迁移 Session 到另一 Agent」）

---

## 12. 术语对照（避免文档混用）

| 用户说法 | 统一术语 | 备注 |
| -------- | -------- | ---- |
| Agent / 角色 / 助手 | **Agent**（`agent_id`） | Web + 飞书统一 |
| 飞书机器人 | Agent 的 **渠道绑定** | 一 Agent 最多绑一个飞书 App（MVP） |
| 对话 / 会话 / Session | **Session** | 归属某 Agent |
| bot_id（旧规划） | **agent_id** | `feishu-multi-bot.md` 中 bot_id 与 agent_id 同义，以本文为准 |

---

## 13. 变更记录

| 日期 | 说明 |
| ---- | ---- |
| 2026-05-26 | 初版：Agent 层套 Session 层；Web CRUD/切换/内容管理；与多飞书、slash 指令对齐 |
