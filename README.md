# DiaryMaster

**DiaryMaster** 是一款本地 Markdown 日记助手：用对话写笔记、改笔记，并在右侧实时看到 Agent 的每一步操作（读文件、局部修改、写入等）。支持**多 Agent**（各自 Session、记忆、工作区与可选 API Key）、**飞书私聊**与 **Web 同步进度**。笔记保存在你电脑上的工作区目录，不会随 Git 仓库上传。

> 适合：按日期写日记、让 AI 帮忙整理/补全、需要看清「Agent 正在干什么」的用户；也可为不同角色（写作 / 工作 / 飞书机器人）配置独立 Agent。

---

## 功能概览

### 界面

- **三栏布局**：左侧文件树、中间编辑/对比、右侧 Agent 对话。
- **编辑 / 变更**：中间栏可手动改 Markdown；Agent 或手动保存后可查看行级 diff（绿增红删）。
- **多 Agent**：对话栏 **Agent · 名称 ▾** 切换；设置页可创建 / 编辑 / 删除 Agent，配置角色提示、工作区、记忆与飞书。
- **多 Session**：每个 Agent 有独立 Session 库；支持切换、新建、**重命名**；首轮对话结束后由 AI **自动生成会话标题**。
- **模型与思考**：输入框底栏可选 **V4 Flash / V4 Pro** 与**思考模式**（偏好存浏览器，不绑 Session）；开启思考时流式展示思考链。
- **上下文圆环**：底栏显示当前模型上下文占用（优先 API `prompt_tokens`，无数据时字符估算）。
- **主题**：设置页可选浅色 / 深色（存本机与 `user_settings`）。

### Agent 能力

| 能力 | 说明 |
| ---- | ---- |
| **局部修改** | 默认用 `edit_file` 只改匹配的一小段，避免整篇重写误伤原文。 |
| **新建 / 长文写入** | 新建文件或短文可用 `write_file`；已有长文会提示改用局部修改。 |
| **跨文件阅读** | `read_file` / `list_files`，可汇总多篇日记（如周总结）。 |
| **工作区管理** | 新建文件/文件夹、复制、移动、删除（危险操作需 Web 内确认）。 |
| **长期记忆** | 每 Agent 独立 `USER.md` / `MEMORY.md`；Agent 可通过 `memory` 工具读写；设置页可编辑。 |
| **执行过程可见** | 流式展示模型调用、`[read_file]`、`[edit_file]` 等步骤；`read_file` 仅预览前几行。 |
| **多轮对话** | 同一 Session 内连续追问；每轮可 **退回**（撤销该轮及之后的对话与文件变更）。 |
| **跨渠道同步** | 飞书触发的对话会增量写入 Session；Web 打开对应 Session 时可轮询看到相同步骤（约 1.2s）。 |

### 飞书渠道（可选）

- 每个 Agent 可配置独立 **App ID / App Secret**（设置页 → Agent → 飞书）。
- **长连接**收私聊消息 → 跑一轮 Agent → 同一条卡片消息 PATCH 更新进度与最终回复。
- 飞书用户与 Session **一对一绑定**（`open_id` → `session_id`）；换 Agent 后绑定数据按 Agent 隔离。
- 飞书渠道**不支持**危险删除类工具；请在浏览器中操作。
- 保存飞书配置或检测通过后，可调用 `POST /api/feishu/restart-ws` 重连长连接。

### 文件与数据

- 笔记为各 Agent 工作区下的 `.md` 文件，统一存放在 `data/agents/{id}/workspace/`（多个 Agent 也可配置共用同一目录）。
- Session、对话、变更、记忆、飞书绑定在 `data/agents/`（本地 JSON，已加入 `.gitignore`）。
- 首次升级会自动把旧版 `data/sessions/`、`data/memories/` 迁移到 `default` Agent。

---

## 环境要求

- Python 3.11+
- [DeepSeek](https://platform.deepseek.com/) API Key（实例默认密钥或各 Agent 独立 Key）
- 飞书（可选）：[飞书开放平台](https://open.feishu.cn/) 自建应用 + 机器人能力 + 事件订阅（长连接）
- 本机已安装 Git（可选，当前版本未集成 Git 功能）

---

## 安装与配置

### 1. 克隆仓库

```bash
git clone https://github.com/adoooore/DiaryMaster.git
cd DiaryMaster
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API Key

在 [DeepSeek 开放平台](https://platform.deepseek.com/) 创建 API Key 后，任选一种方式：

#### 方式 A：应用内设置（推荐）

1. 执行 `python run.py` 并打开浏览器
2. 点击顶栏 **⚙ 设置** → **密钥** 或 **Agent** 页
3. 填写**实例默认密钥**和/或**当前 Agent 专属密钥**并 **保存**

密钥保存在本机 `data/user_settings.json` 与 `data/agents/{id}/meta.json`（均在 `.gitignore` 下）。

**优先级**：Agent 级 Key → 实例 `user_settings` → 环境变量 `DEEPSEEK_API_KEY`。

#### 方式 B：系统环境变量（可选）

仅在未于设置页 / Agent 保存密钥时作为兜底：

**Windows PowerShell**

```powershell
$env:DEEPSEEK_API_KEY="你的密钥"
python run.py
```

**macOS / Linux**

```bash
export DEEPSEEK_API_KEY="你的密钥"
python run.py
```

#### 检查是否生效

```bash
python -c "from backend.config import get_api_key; print('OK' if get_api_key() else 'MISSING')"
```

输出 `OK` 即表示当前 Agent 可用 Key 已就绪。

### 4. 配置飞书（可选）

1. 飞书开放平台创建自建应用，开启机器人与 **长连接** 事件订阅（`im.message.receive_v1`）。
2. DiaryMaster **设置 → Agent** 中填写该 Agent 的 App ID、App Secret，保存。
3. 启动 `python run.py` 后，在设置页使用 **检测**；必要时点 **重启长连接**。
4. 飞书私聊机器人发消息测试；Web 端打开该用户绑定的 Session 可看到同步步骤。

详细任务与路线图见 `plan/` 目录。

### 5. 准备工作区（首次）

启动后会自动创建 Agent 工作区。也可手动在 `data/agents/default/workspace/` 放入 `.md` 日记。

---

## 启动

在项目根目录执行：

```bash
python run.py
```

浏览器打开：**[http://127.0.0.1:8765](http://127.0.0.1:8765)**

### 可选环境变量

| 变量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `DIARYMASTER_HOST` | `127.0.0.1` | 监听地址 |
| `DIARYMASTER_PORT` | `8765` | 端口 |
| `DEEPSEEK_API_KEY` | — | DeepSeek API 密钥（兜底） |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | — | 可覆盖磁盘飞书配置（少见） |

### 端口被占用（Windows）

```powershell
netstat -ano | findstr ":8765"
taskkill /PID <PID> /F
```

---

## 使用指南

### 1. 浏览与手写日记

1. 左侧点击某个 `.md` 文件。
2. 在中间栏编辑内容。
3. 点击 **保存** 写入磁盘（会记录一次「手动」变更，可进 **变更** 视图查看 diff）。

文件树支持右键：新建、重命名、复制、移动、删除等。

### 2. 让 Agent 改日记

在右侧输入自然语言，例如：

- `帮我在今天日记里加一条：晚上吃了火锅。`
- `把 2025-05-14.md 里「优化前端文件树」改成「优化文件树与步骤展示」。`

发送后你会先看到**步骤时间线**（读取、局部修改等），再出现助手文字回复。删除类操作会弹出**确认**框。

### 3. 跨文件 / 周总结

```text
请根据工作区里 2025-05-12 到 2025-05-16 的日记，写一篇本周总结，写入 week-2025-05-16.md
```

### 4. 多 Agent

- **切换**：对话栏 Agent 下拉，或设置页点选 Agent 后 **切换到此**。
- **新建**：设置 → Agent → **+ 新建**，可设名称、角色提示、工作区（独立 / 共用另一 Agent 的目录）、记忆、飞书、专属 API Key。
- **数据隔离**：Session、记忆、飞书绑定按 Agent 分开；工作区可配置为共用。

### 5. 模型、思考与上下文

- **模型**：底栏 `V4 Flash` / `V4 Pro`（存 `localStorage`）。
- **思考**：勾选后流式展示思考过程；关闭则不展示思考链。
- **上下文圆环**：悬停查看 tokens；标注 **API 计量** 或 **字符估算**。

### 6. Session 与标题

- **新建 Session**：在当前 Agent 内开始新对话。
- **重命名**：顶栏 **重命名**；手动命名后不再被自动标题覆盖。
- **自动标题**：每个 Session **第一轮**结束后额外生成简短会话名。

### 7. 撤销与回退

| 操作 | 作用 |
| ---- | ---- |
| 中间栏 **撤销** | 撤销**当前文件**最近一次变更。 |
| 对话区 **退回**（每轮标题旁） | 回退到该轮之前：撤销该轮及之后所有对话与文件变更。 |

### 8. 建议用法

- 日记文件按日期命名，便于 Agent 查找与汇总。
- 改已有内容时优先 **局部修改**；步骤里确认出现 `[edit_file]` 而非整篇 `[write_file]`。
- `data/` 为私人数据，**请勿提交到 Git**。
- 飞书与 Web 看同一会话时，请确保 Web 打开的是飞书用户**已绑定**的那个 Session。

---

## 数据存储位置

| 数据 | 路径 | 提交 Git |
| ---- | ---- | -------- |
| 日记 Markdown | `data/agents/{id}/workspace/` | 否 |
| Agent 注册表 | `data/agents/registry.json` | 否 |
| Session / 对话 / 变更 | `data/agents/{id}/sessions/*.json` | 否 |
| 长期记忆 USER / MEMORY | `data/agents/{id}/memories/` | 否 |
| 飞书绑定 / 去重 / 配置 | `data/agents/{id}/feishu/` | 否 |
| 实例 API Key / UI 主题 | `data/user_settings.json` | 否 |

刷新页面或重启后端后，上述本地数据都会保留。

---

## 项目结构

```
DiaryMaster/
├── backend/
│   ├── agent.py              # Agent 主循环、chat_stream / chat_once
│   ├── agents/               # 多 Agent 注册表、工作区、REST API
│   ├── channels/feishu/      # 飞书长连接、dispatch、卡片状态消息
│   ├── memory/               # USER.md / MEMORY.md 存储与工具
│   ├── session_store.py      # Session chat_log、变更、live 轮次同步
│   └── main.py               # FastAPI 入口
├── web/                      # 前端（对话、文件树、设置、Agent 管理）
├── data/                     # Agent、Session、记忆、工作区（git 忽略）
├── plan/                     # 产品与路线图文档
├── run.py                    # 推荐启动入口
└── requirements.txt
```

---

## 更新记录

| 日期 | 摘要 |
| ---- | ---- |
| 2026-06 | **多 Agent**：Session / 记忆 / 工作区 / API Key / 飞书按 Agent 隔离；Web Agent 管理与对话栏切换；IM 步骤增量同步到 Web |
| 2026-05 | **飞书渠道**：长连接、卡片进度、按 Agent 配置；修复工作区递归错误 |
| 2026-05 | **长期记忆**：`memory` 工具与设置页编辑；跨 Session 检索 |
| 2026-05 | 工作区移删拷、危险操作确认、可编辑预览、右键菜单、多 Session UI |

完整 Git 历史：`git log --oneline`

---

## 许可证

本项目采用 **[MIT License](LICENSE)**。

- **个人 / 商用均可**，可修改、可再分发、可闭源集成。
- **唯一硬性要求**：再分发时须保留版权声明与 MIT 全文。

| 使用场景 | 是否允许 |
| -------- | -------- |
| 个人学习、自用 | ✅ |
| 修改后商用、收费 SaaS | ✅（须保留 LICENSE） |
| 去掉版权与 MIT 声明后分发 | ❌ |

- 英文全文：[LICENSE](LICENSE)
- 中文说明：[LICENSE-CN.md](LICENSE-CN.md)
