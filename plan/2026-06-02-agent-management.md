# Agent 管理 — 产品需求（Web 多 Agent）

**日期**：2026-06-02  
**状态**：规划，未开发  
**用途**：对齐下一阶段 **Agent 层** 产品边界与验收标准——Session、工作区、记忆、API Key 按 Agent 分离；Web UI 完成创建 / 删除 / 切换 / 配置。

**关联文档**：

- `2026-05-26-agent-management.md`（2026-05-26 初版规划，部分假设已被本文 supersede）
- `2026-05-26-feishu-multi-bot.md`（飞书多 App 绑定 Agent，后续阶段）
- `2026-05-26-feishu-slash-commands.md`（Agent 内 Session `/` 指令）
- `2026-05-25-feishu-roadmap.md`

**状态标记**：`待办` | `进行中` | `已完成` | `跳过`

---

## 1. 需求对齐（2026-06-02 确认）

下一阶段必须实现以下三项；飞书多 bot、Agent 工具 CRUD 等排在本文 P5 之后。

| # | 需求 | 现状 | 目标 |
| - | ---- | ---- | ---- |
| **一** | **Agent 与 Session 分离** | 隐含单一 Agent；`data/sessions/` 全局一份，Web 侧栏与飞书绑定共用同一 Session 库 | 每个 Agent **独立 Session 库**；切换 Agent 只显示该 Agent 下的对话；新建 / 切换 Session 仅在当前 Agent 内生效 |
| **二** | **工作区分离（可共享）** | 全局 `workspace/`，所有对话共用同一文件树 | 每个 Agent 可绑定 **独立工作区**，也可 **与其他 Agent 共用** 同一工作区根目录；文件 API 与 Agent 工具按当前 Agent 解析路径 |
| **三** | **记忆与 API Key 分离 + Web 配置** | 全局 `data/memories/`；全局 `user_settings.json` 内单一 `deepseek_api_key`；设置页编辑记忆与 Key | 每个 Agent 独立 USER.md / MEMORY.md 与 **可选独立 API Key**；Web UI 支持 **创建、删除、切换、编辑** Agent |

**产品一句话**：

> DiaryMaster 从「单 Agent + 全局 Session / 工作区 / 记忆 / Key」升级为「显式多 Agent」；Agent 是配置与数据隔离的边界，Session 是对话话题的边界；工作区可在 Agent 间共享，Session 与记忆不共享。

---

## 2. 分层模型

```
服务 (DiaryMaster) — 单实例
 ├── 实例级（可选）：UI 主题、默认 API Key（fallback）
 ├── Agent A「写作」
 │     ├── sessions/          ← A 独享
 │     ├── memories/          ← A 独享（USER.md / MEMORY.md）
 │     ├── api_key（可选）     ← A 独享；未配置时继承实例默认
 │     ├── role_prompt / 模型策略
 │     └── workspace → 独立 或 指向共享根
 ├── Agent B「工作」
 │     ├── sessions/ / memories/ / api_key …  ← 与 A 隔离
 │     └── workspace → 可与 A 共用同一目录
 └── Agent default            ← 迁移承接现有单用户数据
```

**边界约定**：

| 资源 | 是否可跨 Agent 共享 | 说明 |
| ---- | ------------------- | ---- |
| Session | **否** | 对话历史、chat_log、变更记录归属创建它的 Agent |
| 记忆（USER / MEMORY） | **否** | 长期偏好按 Agent 隔离 |
| API Key | **否**（按 Agent 存） | 各 Agent 可配不同 Key；见 §4.3 |
| 工作区（workspace） | **是（可选）** | 默认独立；创建或编辑 Agent 时可选择「独立目录」或「共用某 Agent / 指定路径」 |

**同一人多话题**：在同一 Agent 下用 **多 Session**（`/new`、`/switch`），不必为每个话题新建 Agent。

---

## 3. 现状 vs 目标（代码对照）

| 层级 | 现状（代码） | 目标 |
| ---- | ------------ | ---- |
| **Agent** | 无显式实体；`agent.py` 全局 `SYSTEM_PROMPT` | `AgentProfile` 注册表 + `active_agent_id` |
| **Session** | `backend/session_store.py` → `data/sessions/*.json` | `data/agents/{agent_id}/sessions/` |
| **记忆** | `backend/memory/store.py` → `data/memories/` | `data/agents/{agent_id}/memories/` |
| **API Key** | `backend/config.py` → 全局 `deepseek_api_key` | Agent 级字段 + 实例级 fallback |
| **工作区** | `config.WORKSPACE` = `workspace/` | `get_workspace_root(agent_id)`，支持 dedicated / shared |
| **Web UI** | Session tabs + 全局设置页 | **Agent 切换器** + Agent CRUD + 按 Agent 编辑记忆 / Key |
| **飞书** | 单 App，全局 bindings | 后续：App → Agent 映射（见 multi-bot 文档） |

---

## 4. Agent 实体（数据模型）

### 4.1 AgentProfile

```python
@dataclass
class AgentProfile:
    agent_id: str              # 稳定 id：default / writer / work
    display_name: str          # UI 显示名
    description: str = ""      # 简短说明
    role_prompt: str = ""      # 追加 system prompt 的人设
    created_at: str = ""
    updated_at: str = ""
    enabled: bool = True

    # 模型（可选覆盖）
    model_id: str | None = None
    thinking_enabled: bool | None = None

    # API Key（Agent 级）
    api_key: str | None = None             # 明文仅存磁盘，API 返回 masked
    api_provider: str | None = "deepseek"  # 预留多 Provider

    # 工作区
    workspace_mode: str = "dedicated"        # dedicated | shared
    workspace_path: str | None = None        # dedicated：agents/{id}/workspace
    shared_workspace_ref: str | None = None  # shared：另一 agent_id 或路径 key

    # 渠道（后续）
    feishu: FeishuBinding | None = None

    icon: str | None = None
    sort_order: int = 0
```

### 4.2 目录布局

**注册表**：`data/agents/registry.json`（Agent 列表 + 当前 `active_agent_id`）

**单 Agent 数据**：

```text
data/agents/{agent_id}/
  meta.json                 # AgentProfile 持久化
  sessions/
    {session_id}.json
    active_session.txt
  memories/
    USER.md
    MEMORY.md
  workspace/                # workspace_mode=dedicated 时使用
```

**工作区共用示例**：

| Agent | workspace_mode | 实际根路径 |
| ----- | -------------- | ---------- |
| A | dedicated | `data/agents/A/workspace/` |
| B | dedicated | `data/agents/B/workspace/` |
| C | shared → A | `data/agents/A/workspace/` |
| D | shared → path | `workspace/`（legacy 根或多 Agent 共用命名路径） |

**约束**：

- 共用工作区时，**文件内容**多 Agent 可见可写；**Session 与记忆仍隔离**。
- 删除 Agent：若其他 Agent 仍引用其 workspace，**只删元数据与 sessions/memories**，不删共用目录（UI 需提示）。
- 独立工作区随 Agent 删除一并移除（二次确认）。

### 4.3 API Key 策略

| 场景 | 行为 |
| ---- | ---- |
| Agent 已配置 Key | 该 Agent 对话使用 **Agent Key** |
| Agent 未配置 Key | **继承**实例级默认 Key（`user_settings.json` 或环境变量） |
| Web 设置页 | 编辑 **当前 Agent** 的 Key；保留「实例默认 Key」区块（fallback） |
| 安全 | 磁盘存储；GET 仅 `masked` + `configured`；PUT 空字符串表示不修改 |

---

## 5. Web UI 需求

### 5.1 信息架构

```text
顶栏
├── [Agent 切换 ▼]  默认 | 写作 | 工作 | + 新建 Agent
├── 文件树（当前 Agent 解析后的 workspace 根）
├── Session tabs（仅当前 Agent）
└── [+ 新建对话] / [历史会话]

Agent 管理（设置页新 Tab 或独立入口）
├── Agent 列表
├── [新建 Agent]  → 名称、人设、工作区（独立 / 共用…）、可选 Key
├── [编辑 Agent]  → 同上 + USER/MEMORY
├── [切换为当前]
└── [删除 Agent]  → 二次确认；说明共用工作区时的保留策略

实例设置（保留）
└── 默认 API Key（fallback）、UI 主题等
```

### 5.2 核心操作（必须 Web 可完成）

| 操作 | 行为 | API（草案） |
| ---- | ---- | ----------- |
| **切换 Agent** | 更新 active；reload Session、文件树、聊天、记忆 | `PUT /api/agents/active` |
| **创建 Agent** | 必填 display_name；可选 role_prompt、工作区模式、API Key | `POST /api/agents` |
| **删除 Agent** | 禁止删最后一个；`default` 可禁删 | `DELETE /api/agents/{id}` |
| **编辑 Agent** | 名称、人设、工作区绑定、Key、USER/MEMORY | `PUT /api/agents/{id}` |
| **新建 / 切换 Session** | 仅作用于当前 Agent | session API 带 agent 上下文 |

### 5.3 切换 Agent 时的 UI 行为

- 清空或关闭当前打开的文件 tab。
- 聊天区加载该 Agent 的 active Session。
- 记忆编辑区加载该 Agent 的 USER / MEMORY。
- `localStorage` 同步 `diarymaster-active-agent-id`。

---

## 6. 后端改造要点

| 模块 | 路径 | 改动 |
| ---- | ---- | ---- |
| Agent 注册表 | `backend/agents/` **新子包** | registry、profile CRUD、active 切换 |
| Session | `backend/session_store.py` | 构造时传入 `agent_id`，路径 scoped |
| Memory | `backend/memory/store.py` | 路径含 `agent_id`；快照键 `(agent_id, session_id)` |
| API Key | `backend/config.py` | `get_api_key(agent_id)`：Agent 优先，再 fallback |
| Workspace | `backend/workspace_fs.py` + config | `get_workspace_root(agent_id)` |
| Agent 循环 | `backend/agent.py` | `ChatContext(agent_id, session_id, channel, …)` |
| 主入口 | `backend/main.py` | Agent CRUD 路由 |
| 前端 | `web/app.js` / `index.html` | Agent 切换器与管理表单 |

**迁移（首次启动）**：

1. 创建 `agent_id=default`。
2. `data/sessions/` → `data/agents/default/sessions/`。
3. `data/memories/` → `data/agents/default/memories/`。
4. `workspace/` 作为 default 的 dedicated 根（或 shared 指向 legacy 路径）。
5. 全局 `deepseek_api_key` 保留为实例 fallback。

---

## 7. 实施阶段

| 阶段 | 范围 | 交付 |
| ---- | ---- | ---- |
| **P1** | 数据模型 + 迁移 + Session/Memory/Workspace/Key scoped | default 迁移；单 Agent 行为与现网一致 |
| **P2** | Web Agent 切换 + CRUD + 按 Agent 编辑记忆与 Key | 需求 **三** |
| **P3** | 第二 Agent + 独立 Session / 记忆 / Key 验收 | 需求 **一、三** |
| **P4** | 工作区独立 + 共用配置与验收 | 需求 **二** |
| **P5** | 飞书 app_id → Agent、slash scoped | 见关联文档 |

**建议顺序**：P1 → P2 → P3 → P4。

---

## 8. 验收标准

### 8.1 Session 分离（需求一）

- [ ] Agent A、B 各新建 Session，切换 Agent 后会话列表互不可见。
- [ ] Agent A 的 chat_log 不会出现在 Agent B 的历史中。

### 8.2 工作区（需求二）

- [ ] Agent A **dedicated**：文件树仅显示 `data/agents/A/workspace/`。
- [ ] Agent B **共用 A 的工作区**：文件树与 A 一致；A 写入的文件 B 可读。
- [ ] Agent C **独立**：与 A/B 无交集（未共用前提下）。
- [ ] 切换 Agent 时文件树与 `current_file` 正确 reload。

### 8.3 记忆与 API Key + Web 配置（需求三）

- [ ] Agent A、B 的 USER / MEMORY 独立；Web 编辑互不影响。
- [ ] Agent A 配 Key₁、B 配 Key₂ 时各自对话走对应 Key。
- [ ] Agent 未配 Key 时使用实例默认 Key。
- [ ] Web 可 **创建、删除、切换、编辑** Agent。

### 8.4 迁移

- [ ] 升级后现有数据进入 `default` Agent，行为与升级前一致。

---

## 9. 非目标（本阶段不做）

- Agent 之间 **共享 Session 或记忆**
- Web 登录鉴权 / 多用户权限
- Session 跨 Agent 迁移
- 飞书多 App 全量落地（P5）
- Agent 分组、计费

---

## 10. 术语

| 说法 | 术语 | 备注 |
| ---- | ---- | ---- |
| Agent | `agent_id` | Session / 记忆 / Key 的隔离边界 |
| Session | `session_id` | 同一 Agent 内的对话话题 |
| 工作区 | workspace root | dedicated 或 shared |
| 实例默认 Key | fallback api key | `user_settings` 或环境变量 |

---

## 11. 变更记录

| 日期 | 说明 |
| ---- | ---- |
| 2026-06-02 | 初版：对齐 Session 分离、工作区可共用、记忆与 API Key 按 Agent + Web CRUD |
