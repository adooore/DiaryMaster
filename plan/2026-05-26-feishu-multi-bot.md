# 多飞书机器人（多角色）— 架构规划

**日期**：2026-05-26（规划，未开发）  
**用途**：记录后续目标——**一个 DiaryMaster 服务绑定多个飞书自建应用**，各 App 对应一个 **Agent（使用者/租户）**；**Session、记忆、日记 workspace 全隔离**，支持 **单机部署、多人使用**。

**关联文档**：

- `2026-06-02-agent-management.md`（**总纲**，2026-06-02 需求对齐；Session / 工作区 / 记忆 / Key 按 Agent）
- `2026-05-26-agent-management.md`（2026-05-26 初版，已被 6-2 文档 supersede 部分章节）
- `done-2026-05-25-feishu.md` / `2026-05-25-feishu-roadmap.md`（单机器人现状）
- `2026-05-26-feishu-slash-commands.md`（Agent **内** Session `/` 指令）

**状态标记**：`待办` | `进行中` | `已完成` | `跳过`

---

## 1. 产品目标（一句话）

同一台 DiaryMaster 进程里跑 **N 个飞书机器人**，每个 App 绑定一个 **Agent**（见 `2026-06-02-agent-management.md`）：**人设、记忆、Session 隔离**；workspace 可独立或共用；典型场景为 **家人/同事各用一个 Agent + 各绑一个飞书 bot**。

> **术语**：下文 `bot_id` 与 Agent 文档中的 **`agent_id` 同义**；实现时统一用 `agent_id`。

---

## 2. 现状与差距

| 维度 | 现状（单 bot） | 多 bot 目标 |
| ---- | -------------- | ----------- |
| 飞书凭证 | `user_settings.json` 单个 `feishu.app_id/secret` | 多个 App，各独立凭证 |
| 长连接 | `ws_client` 单例，连一个 App | **每 App 一条** WebSocket |
| 事件路由 | 不区分 `app_id` | 按事件头 **app_id → bot 配置** |
| Session | 全局 `data/sessions/`，`open_id` 绑定 | **按 bot 隔离**（同用户在 bot A/B 各有一条 active 线） |
| 长期记忆 | 全局 `data/memories/USER.md` + `MEMORY.md` | **每 bot 一套** USER/MEMORY（或按 role_id） |
| 记忆快照 | `session_id → snapshot` | **`(bot_id, session_id)`** 二维键 |
| 工作区 | 全局 `workspace/` | **`data/agents/{agent_id}/workspace/`** |
| System Prompt | 全局 `SYSTEM_PROMPT` + 记忆块 | **每 bot 可配** role_prompt / 名称 / 工具策略 |
| Web 设置页 | 一组飞书凭证 | **机器人列表** CRUD + 角色说明 |
| Agent 工具 | 单渠道 `channel=feishu` | 工具调用需带 **bot 上下文**（写记忆时不串 bot） |

---

## 3. 核心概念

### 3.1 术语

| 术语 | 含义 |
| ---- | ---- |
| **服务实例** | 一个 `python run.py` 进程（本规划默认单实例） |
| **Bot / 角色** | 飞书开放平台上的一个自建应用 + DiaryMaster 内一条配置（`bot_id`） |
| **bot_id** | 本机稳定标识，如 `writer`、`reviewer`（与飞书 `app_id` 一一对应） |
| **共享层** | DeepSeek API Key、可选全局 UI 主题（实例级） |
| **隔离层** | 各 Agent 的 Session、bindings、USER/MEMORY、**workspace**、role prompt |

### 3.2 隔离原则（2026-05-26 更新：workspace 亦隔离）

```
                    ┌─────────────────────────────────────┐
                    │         DiaryMaster 服务             │
                    │  （全局：API Key、UI 主题）           │
                    └─────────────────────────────────────┘
         完全隔离 per Agent
  ┌──────────────┐    ┌──────────────┐
  │ Agent A      │    │ Agent B      │
  │ · workspace  │    │ · workspace  │
  │ · 记忆       │    │ · 记忆       │
  │ · Session    │    │ · Session    │
  │ · 飞书 App A │    │ · 飞书 App B │
  └──────────────┘    └──────────────┘
```

**刻意隔离**：日记、记忆、对话——避免多人共用一实例时互相读写。

**刻意共享（实例级）**：模型 API Key、部署配置；**不共享**日记目录。

**边界 case（产品需定）**：

- Web 端不再使用单独的 `bot_id=web` 虚拟 bot，而由 **Agent 注册表** 中「未绑飞书」的 Agent 供浏览器使用（见 agent-management §4）。
- 用户是否希望 **跨 Agent 检索历史 Session**？MVP：**否**，仅在本 Agent 内 `/sessions`。

---

## 4. 数据布局（建议）

```text
data/
  user_settings.json          # 全局 API Key、ui_theme
  agents/
    registry.json
    {agent_id}/
      workspace/              # 该 Agent 独占日记树
      memories/
      sessions/
      feishu/
        bindings.json
        config.json
```

**迁移**：现有根目录 `workspace/` → `data/agents/default/workspace/`。

---

## 5. 运行时架构

### 5.1 配置模型

```python
@dataclass
class FeishuBotProfile:
    bot_id: str              # 本机唯一
    display_name: str        # 「写作助手」
    app_id: str
    app_secret: str          # 磁盘加密可选；设置页 masked
    role_prompt: str         # 追加到 system prompt 的人设段
    enabled: bool
    model_id: str | None     # 可选覆盖全局默认模型
    tools_allowlist: list[str] | None  # 可选：如教练 bot 禁 write_file
```

- 注册表：`data/feishu/bots.json`
- 凭证：**禁止**多 bot 共用同一 `app_id`（启动时校验）

### 5.2 连接与分发

```text
startup:
  for each enabled bot in bots.json:
    start_ws_client(bot_profile)   # 线程或 asyncio 任务，独立 lark WS

on im.message.receive_v1:
  app_id = header.app_id
  bot = registry.get_by_app_id(app_id)
  dispatch.handle(event, bot=bot)  # 后续 bind / memory / session 均带 bot_id
```

- `dispatch` / `chat_once(..., bot_id=..., feishu_open_id=...)`
- `memory` 子包：`store.read(bot_id, "user")` 或 `MemoriesScope(bot_id)`

### 5.3 Agent 与工具

- `_chat_channel` 扩展为 `(channel, bot_id)` 或 `ChatContext` 小对象。
- `memory` 工具：写入 **当前 bot** 的 USER/MEMORY，不可跨 bot 读除非显式加「全局记忆」产品（**不做**）。
- `read_file` / `edit_file`：路径相对于 **`data/agents/{agent_id}/workspace/`**（与 agent-management §6 一致）。
- 危险工具策略：可按 `bot_id` 配置（如某角色只读日记、不允许 `delete_path`）。

### 5.4 Web UI

- 设置页：**飞书机器人列表**（添加 / 启用 / 检测连通 / 编辑 role_prompt）
- 可选：顶栏或 Session 侧栏显示「当前渠道：Web / 写作 bot / …」
- Session 列表 API：`GET /api/sessions?bot_id=writer`

---

## 6. 与「/ 指令」、Agent 工具的关系

| 能力 | 单 bot 阶段（明日文档） | 多 bot 阶段 |
| ---- | ----------------------- | ----------- |
| `/sessions` | 列出全局 Session | 仅列出 **当前 bot** 下 Session |
| `/switch` | 改本 bot 的 active + binding | 不变，scope 含 bot_id |
| `list_chat_sessions` | 全局 | 参数 `bot_id` 或从上下文 |
| 新建 bot | — | 设置页添加后 **自动起 WS**，无需重启（理想）或提示重启 |

实现 `/` 指令时，**session_ops 建议预留 `bot_id` 参数**，避免二次重构。

---

## 7. 分阶段交付（建议）

### 阶段 M0 — 设计与迁移脚本（0.5～1 天）

| ID | 任务 | 状态 |
| -- | ---- | ---- |
| M0-1 | 定稿 `bot_id`、目录布局、Web 虚拟 bot 策略 | 待办 |
| M0-2 | 单 bot 数据 → `default` 迁移脚本（sessions / memories / bindings） | 待办 |
| M0-3 | `FeishuBotRegistry` 读写在 `backend/channels/feishu/bots/` | 待办 |

### 阶段 M1 — 双 bot 跑通（2～3 天）

| ID | 任务 | 状态 |
| -- | ---- | ---- |
| M1-1 | 多 `ws_client` 实例 + 按 `app_id` 路由 dispatch | 待办 |
| M1-2 | `SessionStore` 或外层 `BotSessionStore` 按 bot 分目录 | 待办 |
| M1-3 | `memory/store` 按 bot 分 USER/MEMORY；snapshot 键 `(bot_id, session_id)` | 待办 |
| M1-4 | `bind.py` 路径改为 `bots/{bot_id}/bindings.json` | 待办 |
| M1-5 | `chat_once` / Agent 缓存键含 `bot_id` + role_prompt | 待办 |
| M1-6 | 设置页：第二 bot 凭证 + 角色名 + 简短人设 | 待办 |
| M1-7 | 验收：两 App 私聊各记不同 MEMORY，**各自 workspace 互不可见** | 待办 |

### 阶段 M2 — 体验与运维（1～2 天）

| ID | 任务 | 状态 |
| -- | ---- | ---- |
| M2-1 | 每 bot 独立 diagnostics / activity | 待办 |
| M2-2 | 卡片主题、reply_display  per bot（已有 config.json 雏形） | 待办 |
| M2-3 | Agent 工具：`list_feishu_bots`、`get_bot_role`（可选） | 待办 |
| M2-4 | 启动时重复 app_id、缺权限统一告警 | 待办 |

### 阶段 M3 — 增强（可选）

- 群聊：`chat_id` 绑定按 **bot + chat** 二维（与 roadmap B3 合并）
- 每 bot 不同模型 / thinking 开关
- 只读 bot：仅 `read_file` + 记忆，不写 workspace

---

## 8. 非目标（首版多 bot 不做）

- 多 **DiaryMaster 进程** 水平扩展（本规划仅单进程多 App）
- 云端多租户 SaaS、账号体系与计费（单机多人 = 多个 Agent，无登录亦可先用）
- 跨 Agent **共享** 同一本日记（见 agent-management §6）
- 飞书一个 App 内多个「虚拟角色」（必须多 App 才能区分租户）

---

## 9. 风险与约束

| 风险 | 说明 | 缓解 |
| ---- | ---- | ---- |
| 并发写文件 | 同一 Agent 内 workspace 锁 | 沿用现有锁；**不再跨 Agent 争用同一文件** |
| Agent 缓存 | `_agent_cache` 键需含 bot + role_prompt | M1-5 一并改 |
| 全局 `store.active_id` | 多 bot 并发 switch 互抢 | SessionStore 改为 **按 bot 维护 active**，或 dispatch 内局部 context 不依赖全局 |
| 飞书后台 | 每个角色需单独建应用、开权限、长连接 | 设置页文档化 checklist |
| 记忆重复 | 用户偏好需在 Web 与多 bot 各写一遍 | 可选「全局 USER 只读引用」远期项，**M1 不做** |

---

## 10. 验收标准（M1 完成时）

- [ ] 配置两个飞书 App，服务同时维持两条 WS，日志可区分 bot 名。
- [ ] 用户分别私聊 bot A / B：对话历史互不可见（不同 Session 文件）。
- [ ] 在 A 的 MEMORY 写入「称呼老板」；B 的 MEMORY 无此项；B 对话中 Agent 不应假定该偏好。
- [ ] A 在 workspace 写 `日记.md`，B **读不到**；B 的文件树无 A 的文件。
- [ ] Web 设置页可禁用某一 bot，禁用后不再收消息且 WS 断开。
- [ ] 升级旧数据后，原单 bot 对话与记忆仍在 `default`（或 `main`）下可用。

---

## 11. 模块归属（backend 分层）

| 模块 | 路径 | 职责 |
| ---- | ---- | ---- |
| Bot 注册表 | `backend/channels/feishu/bots/` | registry、profile、CRUD API |
| 连接池 | `backend/channels/feishu/ws_pool.py` | 多 WS 生命周期 |
| 分发 | `backend/channels/feishu/dispatch.py` | 增加 `bot: FeishuBotProfile` |
| 绑定 | `backend/channels/feishu/bind.py` | `bot_id`  scoped |
| 记忆 | `backend/memory/store.py` | 增加 `scope: str`（bot_id） |
| Session | `backend/session_store.py` 或 `backend/session/` 子包 | 分 bot 目录或 scoped store |
| 设置 API | `main.py` + `settings_api` | 多 bot CRUD |
| Agent | `agent.py` | `ChatContext(bot_id, channel, open_id)` |

遵循仓库 `backend-module-layout`：**多 bot 飞书逻辑集中在 `channels/feishu/bots/`**，不把 `feishu_bot_registry.py` 堆在 backend 根目录。

---

## 12. 变更记录

| 日期 | 说明 |
| ---- | ---- |
| 2026-05-26 | 初版：单服务多飞书 App、记忆/Session 按 bot 隔离、workspace 共享；分 M0～M3 阶段 |
| 2026-05-26 | 对齐 agent-management：**workspace 按 Agent 隔离**，支持单机多人 |
