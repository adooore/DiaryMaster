# DeepNote Demo MVP

三栏 IDE 式网页：左侧文件树、中间编辑笔记、右侧与 Agent 对话。Agent 可通过 `write_file` 工具写入 `workspace/` 下的 Markdown 文件。

## 环境

- Python 3.11（建议 `conda activate note_agent`）
- 环境变量 `DEEPSEEK_API_KEY`（系统变量或 `demo/.env`）

## 安装

```powershell
cd C:\Users\MyNotes\demo
pip install -r requirements.txt
```

## 启动

任选一种（需先 `cd C:\Users\MyNotes\demo`，或在项目根用下面第 3 种）：

```powershell
cd C:\Users\MyNotes\demo
python run.py
```

或：

```powershell
cd C:\Users\MyNotes\demo
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8765
```

或从任意目录直接跑 `main.py`（已自动加入模块路径）：

```powershell
python C:\Users\MyNotes\demo\backend\main.py
```

注意：不要在不改路径的情况下只运行 `backend\main.py` 且依赖相对导入；上面三种方式均已支持。

浏览器打开：http://127.0.0.1:8765（默认端口 **8765**，避免与占用 8000 的其他程序冲突）

自定义端口：

```powershell
$env:DEEPNOTE_PORT="9000"
python run.py
```

### 启动报错 `WinError 10013`

多半是 **端口已被占用**。可先查占用：

```powershell
netstat -ano | findstr ":8765"
```

结束旧进程（把 PID 换成上一步最后一列数字）：

```powershell
taskkill /PID <PID> /F
```

或换一个端口：`$env:DEEPNOTE_PORT="9000"` 后再启动。

若 8000 上已有本项目的旧服务在跑，也可直接打开 http://127.0.0.1:8000 使用，无需再启一次。

## 试用

1. 左侧点击 `welcome.md`，中间可编辑，点「保存」写入磁盘。
2. 右侧发送：`请把 welcome.md 改成：今天学习了 LangChain 和 FastAPI。`
3. Agent 调用工具写入后，会自动进入 **「变更」** 视图：绿色为新增行，红色删除线为删除行（类似 Cursor / Git diff）。
4. 手动编辑后点「保存」，若有改动也可点 **「变更」** 查看对比。
5. 对话按轮分段显示；每轮顶部有 **「退回」** 按钮，会同时撤销该轮及之后的**全部对话与文件变更**（变更卡片仅保留「查看变更」）。
6. 点顶部 **「新建 Session」** 会清空对话与变更历史。
7. 中间栏 **「撤销」** 可快速撤销当前文件最近一次变更（含文件、后续变更记录、后续对话与 Agent 上下文）。
8. 发送消息后**立即显示**你的气泡，Agent 回复前显示「思考中…」。

## 数据存在哪里？

| 数据 | 存储位置 | 刷新网页 | 重启后端 |
|------|----------|----------|----------|
| 笔记 `.md` 文件 | `demo/workspace/` 磁盘 | 保留 | 保留 |
| Session（对话 + 变更） | `demo/data/sessions/*.json` + 内存 | 保留 | 保留 |
| 当前选中的 Session | `demo/data/active_session.txt` | 保留 | 保留 |
| Agent 多轮上下文 | 从 Session 对话重建 | 随 Session | 随 Session |

**新建 Session** 不会删除旧 Session，只是切换到新的空白 Session。顶栏下拉框可切回历史 Session。

注意：所有 Session 共用同一个 `workspace/` 笔记目录；切换 Session 不会自动切换笔记快照（文件是全局的）。

## 目录

- `backend/` — FastAPI + LangChain Agent
- `web/` — 前端静态页
- `workspace/` — 笔记工作区（仅此目录可读写）
