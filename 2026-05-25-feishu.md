# DiaryMaster 飞书机器人渠道 — 开发任务表

**日期**：2026-05-20（配置方案更新：2026-05-25）  
**用途**：接入飞书自建应用机器人；每完成一条，把状态改为 `已完成`，并写上完成日期（可选备注）。

**状态标记**：`待办` | `进行中` | `已完成` | `跳过`

---

## 背景（一句话）

在现有 Web + Agent 之上，新增 `backend/channels/feishu/`：飞书事件订阅（公网 HTTPS 回调）收消息 → 跑一轮 `agent` → 飞书 API 回文本；**复用**已有 OpenClaw 申请的 App ID / Secret（事件 URL 改指向 DiaryMaster）。

**边界（MVP 不做）**：群聊 @、图片/文件消息、飞书卡片、与 OpenClaw 同时收同一应用事件。

**默认技术选择**（未另行约定则按此实现）：

- 子包：`backend/channels/feishu/`（`main.py` 只 `include_router`）
- **配置（与 DeepSeek API Key 同一套）**：本机 `data/user_settings.json`，在现有 **设置** 弹窗（`#settings-form`）中增加「飞书机器人」区块；`GET`/`PUT` **`/api/settings`** 扩展字段（不单独拆 `/api/settings/feishu`，避免两处保存）
- **配置优先级**：环境变量 `FEISHU_*` **可覆盖** 磁盘（便于 CI/脚本）；日常以设置页写入为准
- 绑定数据：`data/feishu/bindings.json`（`open_id` → `session_id`，P1 起用；MVP 可固定单一 Session）
- HTTP 客户端：标准库 `urllib`（不新增依赖）；若实现明显冗长可改 `httpx` 并记入 requirements
- 飞书路径：`POST /channels/feishu/webhook`（与飞书后台「请求网址」一致）
- IM 渠道：`thinking_enabled=false`，`current_file=null`；不推送 SSE `step` 到飞书

**运维前置（非代码，但阻塞联调）**：

- 本机 `python run.py` 可用 + 隧道（ngrok / Cloudflare Tunnel / Tailscale Funnel）提供 **HTTPS**
- 飞书开放平台：事件订阅 URL 指向隧道地址；订阅 `im.message.receive_v1`；机器人能力已发布
- 若 OpenClaw 仍占用同一应用的事件 URL → 改 URL 或停用 OpenClaw 飞书渠道

---

## 任务分布总览

| 阶段 | 任务 ID | 一句话 | 状态 |
| ---- | ------- | ------ | ---- |
| 准备 | F0 | 飞书后台 + 隧道联调清单（凭证、URL 校验） | 待办 |
| P0-1 | F1 | 子包骨架与 `config`（读 `user_settings` + 环境变量覆盖） | 已完成 |
| P0-1b | F1s | 设置页 + `/api/settings` 扩展（App ID / Secret 等，与 API Key 同页） | 已完成 |
| P0-2 | F2 | `tenant_access_token` 获取与缓存 | 已完成 |
| P0-3 | F3 | 验签 / 解密 + URL `challenge` | 已完成 |
| P0-4 | F4 | 飞书发消息 `client` | 已完成 |
| P0-5 | F5 | `agent.chat_once` 非流式单轮入口 | 已完成 |
| P0-6 | F6 | 收事件 → 调 Agent → 回复（`dispatch`） | 已完成 |
| P0-7 | F7 | `router` + `main.py` 挂载 | 已完成 |
| P0-8 | F8 | MVP 端到端验收（私聊一句往返） | 待办 |
| P1-1 | F9 | `open_id` ↔ Session 绑定持久化 | 已完成 |
| P1-2 | F10 | 事件 `message_id` 去重 | 已完成 |
| P1-3 | F11 | 同一用户消息串行锁 | 已完成 |
| P1-4 | F12 | IM 危险工具策略（禁用或拒绝 `delete_path`） | 已完成 |
| P1-5 | F13 | 错误提示 + 超长回复分段 | 已完成 |
| P2-1 | F14 | 可选「处理中」先回一条（防飞书重试） | 待办 |
| P2-2 | F16 | 群聊仅 @ 机器人时回复 | 待办 |
| P2-3 | F17 | 图片 / 文件消息（后置） | 待办 |

**建议开发顺序**：F0 → **F1 → F1s** → F2 → F3 → F7（仅 challenge）→ F4 → F5 → F6 → F8（P0 闭环）→ F9 → F10 → F11 → F12 → F13 → F14+。

**依赖简图**：

```
F0（运维）
F1 → F1s（设置页写入后 F1 可读盘）
F1 → F2 → F3 → F7
F2 → F4
F5 → F6 → F7
F6 依赖 F3、F4、F5
F8 依赖 P0 全部（含 F1s：凭证建议用设置页录入）
F9～F13 依赖 P0；彼此可部分并行（F10/F11 建议先于 F12）
```

---

## 准备 — 飞书后台与隧道（F0）

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 待办 |
| **完成日** | |
| **主要产出** | 本文件「F0 检查清单」全部勾选；隧道 HTTPS URL 可访问 |
| **依赖** | 无 |

**检查清单**

- [ ] 飞书开放平台 → 应用 → **凭证**：确认 App ID、App Secret（与 OpenClaw 一致即可）
- [ ] **事件订阅**：请求网址 = `https://<隧道域名>/channels/feishu/webhook`
- [ ] **事件订阅**：已添加 `im.message.receive_v1`；Verification Token、Encrypt Key 记入 **设置页 → 飞书机器人**（或临时用环境变量）
- [ ] **权限**：机器人发消息、读消息等已申请并 **发布版本**
- [ ] 本机：`DIARYMASTER_HOST`/`PORT` 与隧道转发端口一致
- [ ] 机器人已与测试账号 **单聊** 或拉群（MVP 仅单聊）
- [ ] OpenClaw 已停止占用同一应用的事件 URL（或已换新应用）

**验收**：浏览器或 `curl` 访问隧道根路径不报错；飞书后台保存事件 URL 时 **校验通过**（需 F3+F7 已部署；可先占位实现 challenge）。

---

## P0 — MVP：私聊一句 ↔ Agent 一句

### F1 — 子包骨架与配置

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `backend/channels/__init__.py`、`backend/channels/feishu/__init__.py`、`config.py` |
| **依赖** | 无 |

**需求**

- `config.py` 提供：`get_feishu_config()` → `app_id`、`app_secret`、`verification_token`、`encrypt_key`；`is_enabled()`（四项齐全且 `app_secret` 非空）
- **读取顺序**（与 API Key 思路一致）：
  1. 若环境变量 `FEISHU_APP_ID` 等已设置 → 使用环境变量（覆盖磁盘）
  2. 否则读 `data/user_settings.json` 内 **`feishu` 对象**（由 F1s 写入）
- `__init__.py` 仅导出对外符号（如 `router`、`is_enabled`）
- 函数带中文 docstring

**验收**

- 无配置时 `is_enabled()` 为 False；仅写入 `user_settings.json` 或仅设环境变量后均为 True

---

### F1s — 设置页与 `/api/settings`（与 API Key 同页）

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `backend/channels/feishu/settings_api.py`（或 `credentials.py`）；`backend/main.py`；`web/index.html`；`web/app.js` |
| **依赖** | F1（`config` 能读盘）；可参考现有 `api_key_status` / `set_api_key` |

**需求**

**磁盘结构**（`data/user_settings.json`，已在 `.gitignore` 的 `data/` 下）：

```json
{
  "deepseek_api_key": "sk-…",
  "feishu": {
    "app_id": "cli_xxxxxxxx",
    "app_secret": "xxxxxxxx",
    "verification_token": "xxxxxxxx",
    "encrypt_key": "xxxxxxxx"
  }
}
```

**后端**

- 扩展 `SettingsUpdateRequest`：保留 `api_key`；增加可选对象 `feishu`（字段均可选）
- `GET /api/settings` 响应在现有 `configured` / `masked` / `provider` 之外增加 **`feishu`**：
  - `app_id`：明文展示（非密钥）
  - `app_secret`、`verification_token`、`encrypt_key`：仅 **`masked`** + `configured` 布尔（与 API Key 相同「留空不修改」语义）
  - `enabled`：是否四项齐全可启用 webhook
- `PUT /api/settings`：同一请求可只改 API Key、只改飞书、或两者一起改；**空字符串表示不修改**对应密钥字段；提供逻辑 **清除飞书配置**（删除 `feishu` 键或清空对象）
- 保存后：使 `token.py` 内存缓存失效（若已实现 F2）
- 复用 `user_settings.load_settings` / `save_settings`；敏感字段写入磁盘，**勿**打日志

**前端（同一 `#settings-form`）**

- 在 API Key 与「长期记忆」之间增加 `<hr>` + 标题 **飞书机器人**
- 字段：`App ID`（`type=text`）、`App Secret`、`Verification Token`、`Encrypt Key`（后三个 `type=password`）
- 提示文案：说明在 [飞书开放平台](https://open.feishu.cn/) → 应用凭证 / 事件订阅 中复制；仅本机保存
- 状态行：已配置时显示脱敏（如 `app_secret_masked`）；未配置时警告
- 按钮：**清除飞书配置**（与「清除密钥」并列，仅清 `feishu` 块）
- **保存**：沿用表单底部「保存」一次提交 `api_key` + `feishu`（与记忆区不同，记忆仍走 `/api/memories`）

**验收**

- [ ] 设置页填入 OpenClaw 用过的 App ID / Secret 等 → 保存 → 刷新后 hint 显示已配置
- [ ] `GET /api/settings` 不返回明文 Secret
- [ ] 保存后 `config.is_enabled()` 为 True，F2 能取到 token（F2 完成后测）

---

### F2 — `tenant_access_token`

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `backend/channels/feishu/token.py` |
| **依赖** | F1、F1s（凭证来源）

**需求**

- 调用飞书 `auth/v3/tenant_access_token/internal`
- 内存缓存 token + 过期时间（提前 60s 刷新）
- 失败抛清晰异常供 dispatch 捕获

**验收**

- 配置真实凭证后 `python -c` 能打印 token 前几位（勿提交日志）

---

### F3 — 验签与事件解密

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `backend/channels/feishu/crypto.py` |
| **依赖** | F1、F1s（凭证来源）

**需求**

- URL 校验：解析 `challenge`，原样 JSON 返回
- 加密事件：按飞书文档 AES 解密 + 签名校验（`X-Lark-Signature` 等，以当前文档为准）
- 解密后得到事件 JSON；非法请求返回 4xx

**验收**

- 单元测试或手动：用飞书后台「保存事件配置」通过校验
- 伪造 body 返回 401/403

---

### F4 — 发送消息客户端

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `backend/channels/feishu/client.py` |
| **依赖** | F2 |

**需求**

- `send_text(receive_id, receive_id_type, text)`：调用发消息 Open API
- 使用 F2 的 token；错误码转中文摘要

**验收**

- 脚本或临时路由能向自己的 `open_id` 发一条「ping」

---

### F5 — `agent.chat_once`

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `backend/agent.py` 新增 `chat_once`（或 `run_turn`） |
| **依赖** | 无（与 F1 可并行） |

**需求**

- 签名：`chat_once(user_message, *, model_id=None, current_file=None, thinking_enabled=False) -> dict`
- 内部消费 `_chat_stream_events` 或等价逻辑，**不**注册 `ConfirmRegistry`（IM 无 UI 确认）
- 返回 `{"type":"done", ...}` 或 `{"type":"error", "detail":...}`
- 持久化：与 Web 一致调用 `_persist_chat_turn` 逻辑（可抽共用函数避免重复）

**验收**

- `python -c` 从项目根调用一轮对话，得到 `reply` 字符串

---

### F6 — 事件分发与回复

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `backend/channels/feishu/dispatch.py` |
| **依赖** | F3、F4、F5 |

**需求**

- 处理 `im.message.receive_v1`：仅 **文本**；忽略机器人自己发的消息
- MVP：`store.get_session()` 使用当前 active Session（不建 bind）
- 调用 `chat_once` → `client.send_text` 回复
- 异常时向用户发简短错误（如未配置 API Key）

**验收**

- 飞书私聊发「你好」→ 收到 Agent 中文回复

---

### F7 — 路由与 `main` 挂载

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `backend/channels/feishu/router.py`；`backend/main.py` 改动 |
| **依赖** | F3、F6 |

**需求**

- `APIRouter(prefix="/channels/feishu")`，`POST /webhook`
- `enabled=false` 时返回 503 或静默 200（择一并在注释说明）
- `main.py`：`app.include_router(...)`（**已完成**：子包就绪时自动挂载）

**验收**

- `POST /channels/feishu/webhook` 在 OpenAPI 中可见；飞书 challenge 通过

---

### F8 — P0 端到端验收

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 待办 |
| **完成日** | |
| **主要产出** | 本表 P0 备注栏记录测试结果 |
| **依赖** | F0～F7、**F1s** |

**验收**

- [ ] **设置页**已保存 App ID、App Secret、Verification Token、Encrypt Key（或环境变量覆盖）
- [ ] 隧道 HTTPS + 飞书事件 URL 保存成功
- [ ] 私聊文本 → DiaryMaster 回复 → 飞书显示
- [ ] 回复内容写入 Session `chat_log` / `messages`
- [ ] Agent 调用 `write_file` 后工作区确有文件（可选测一条「新建笔记 test.md」）

---

## P1 — 隔离、稳定与安全

### F9 — `open_id` ↔ Session 绑定

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `backend/channels/feishu/bind.py` |
| **依赖** | F8 |

**需求**

- `data/feishu/bindings.json`：`{open_id: session_id}`
- 首次消息：新建 Session 并绑定；之后 `store.activate(session_id)` 再跑 Agent
- 与 Web `active_session` 互不强制同步（文档说明）

**验收**

- 两个不同 `open_id`（可用飞书测试号 + 同事）对应两个 Session，对话历史不串

---

### F10 — 事件去重

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `dispatch` 或 `dedupe.py`；内存 + 可选 `data/feishu/processed.json` |
| **依赖** | F8 |

**需求**

- 以 `message_id` 为键；TTL 或最多保留 N 条
- 重复事件直接 200，不再调 Agent

**验收**

- 模拟同一 `message_id` POST 两次，仅一次 Agent 调用

---

### F11 —  per-open_id 串行锁

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `dispatch` 内锁或队列 |
| **依赖** | F9 |

**需求**

- 同一 `open_id` 同时只跑一轮 `chat_once`；后续消息排队或回复「上一条处理中」

**验收**

- 快速连发两条，不出现交叉回复或 Session 写乱

---

### F12 — IM 危险工具策略

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 待办 |
| **完成日** | |
| **主要产出** | `dispatch` 传入渠道标记，或 `agent` 侧 `channel="feishu"` |
| **依赖** | F8 |

**需求**

- 飞书渠道：**禁止** `delete_path` 执行（工具层返回「飞书渠道不支持删除，请在浏览器操作」）或等价
- 文档写入本文件「已选方案」

**验收**

- 飞书发「删除某文件」→ 不删文件，回复说明

---

### F13 — 错误提示与长回复分段

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 已完成 |
| **完成日** | 2026-05-25 |
| **主要产出** | `client.py` / `dispatch.py` 增强 |
| **依赖** | F4、F6 |

**需求**

- API Key 缺失、飞书 token 失败、Agent 异常 → 用户可见中文
- 回复超飞书单条上限时分段发送（查当前文档字符限制）

**验收**

- 故意清空 API Key → 飞书收到明确提示；长文回复多条消息

---

## P2 — 体验与扩展（后置）

### F14 — 「处理中」占位回复

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 待办 |
| **完成日** | |
| **主要产出** | `dispatch.py` |
| **依赖** | P1 |

**需求**

- 收到消息后先 `send_text("处理中…")` 或飞书 typing（若 API 支持），再跑 Agent
- 避免慢任务触发飞书重复推送

---

### F16 — 群聊 @ 机器人

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 待办 |
| **完成日** | |
| **主要产出** | `dispatch.py` 解析 `chat_type`、mentions |
| **依赖** | P1 |

---

### F17 — 图片 / 文件消息

| 字段 | 内容 |
| ---- | ---- |
| **状态** | 待办 |
| **完成日** | |
| **主要产出** | 下载飞书资源 → 临时文件或描述进 Agent |
| **依赖** | P1 |

---

## 文件结构（目标树）

```text
backend/channels/
  __init__.py
  feishu/
    __init__.py           # 导出 router, is_enabled
    config.py             # F1：读 user_settings + 环境变量
    settings_api.py       # F1s：feishu_status / apply_feishu_settings（供 main 调用）
    token.py              # F2
    crypto.py             # F3
    client.py             # F4
    bind.py               # F9
    dispatch.py           # F6, F10–F14
    router.py             # F7
backend/agent.py          # F5 chat_once
backend/main.py           # F1s 扩展 GET/PUT /api/settings；F7 include_router
backend/user_settings.py  # 已有；F1s 写入 feishu 对象
web/index.html            # F1s 设置表单区块
web/app.js                # F1s 加载/保存/清除飞书字段
data/user_settings.json   # deepseek_api_key + feishu（gitignore）
data/feishu/              # bindings.json、processed（若用）
```

---

## 配置说明（App ID / Secret 放哪）

与 **DeepSeek API Key** 相同：**优先本机设置页 → `data/user_settings.json`**，不强制环境变量。

| 配置项 | 飞书后台位置 | 设置页字段 | 是否密钥（脱敏） |
| ------ | ------------ | ---------- | ---------------- |
| App ID | 凭证与基础信息 | `app_id`（明文） | 否 |
| App Secret | 凭证与基础信息 | `app_secret` | 是 |
| Verification Token | 事件订阅 | `verification_token` | 是 |
| Encrypt Key | 事件订阅 | `encrypt_key` | 是 |

**读取优先级**（`config.get_feishu_config`）：

1. 环境变量 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_VERIFICATION_TOKEN`、`FEISHU_ENCRYPT_KEY`（任一用途：部署脚本覆盖本机文件）
2. `user_settings.json` → `feishu` 对象

**API 契约（扩展 `/api/settings`，与 API Key 同接口）**

`GET /api/settings` 示例（字段名以实现为准）：

```json
{
  "configured": true,
  "masked": "sk-…abcd",
  "provider": "deepseek",
  "feishu": {
    "enabled": true,
    "configured": true,
    "app_id": "cli_xxxxxxxx",
    "app_secret_masked": "xxx…yyyy",
    "verification_token_masked": "xxx…yyyy",
    "encrypt_key_masked": "xxx…yyyy"
  }
}
```

`PUT /api/settings` 示例：

```json
{
  "api_key": "",
  "feishu": {
    "app_id": "cli_xxxxxxxx",
    "app_secret": "新 secret 或留空表示不修改",
    "verification_token": "",
    "encrypt_key": ""
  }
}
```

- 与现有 API Key 行为一致：**密钥类字段留空 = 不覆盖旧值**；`app_id` 可整段替换。
- 清除：前端「清除飞书配置」→ `PUT` 时传 `feishu: null` 或专用 `clear_feishu: true`（实现时二选一并在 F1s 写死）。

**UI 位置**：顶栏 **设置** → 同一面板内顺序建议为 **DeepSeek API Key → 飞书机器人 → 长期记忆**（记忆仍单独调 `/api/memories`，避免一次保存误改密钥）。

---

## 环境变量（可选覆盖）

| 变量 | 必填 | 说明 |
| ---- | ---- | ---- |
| `FEISHU_APP_ID` | 否 | 设则覆盖磁盘中的 `app_id` |
| `FEISHU_APP_SECRET` | 否 | 设则覆盖磁盘中的 `app_secret` |
| `FEISHU_VERIFICATION_TOKEN` | 否 | 设则覆盖磁盘 |
| `FEISHU_ENCRYPT_KEY` | 否 | 设则覆盖磁盘 |

未设环境变量时，以设置页保存的 `user_settings.json` 为准。

---

## 变更记录

| 日期 | 说明 |
| ---- | ---- |
| 2026-05-20 | 初版任务表：P0 MVP + P1 稳定 + P2 扩展 |
| 2026-05-25 | 配置并入设置页：新增 **F1s**，扩展 `/api/settings`；原 P2 **F15** 合并删除；`user_settings.feishu` 与 API Key 同文件 |
| 2026-05-25 | **F5** `chat_once`、**F1s** 设置 API/前端、`main` 条件挂载 feishu_router 已完成 |
| 2026-05-25 | **channels/feishu** 子包：F1–F4、F6–F7、F9–F13、`settings_api.py`；依赖 `pycryptodome` 解密 |
