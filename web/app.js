const fileTreeEl = document.getElementById("file-tree");
const editorEl = document.getElementById("editor");
const diffViewEl = document.getElementById("diff-view");
const currentFileLabel = document.getElementById("current-file-label");
const btnSave = document.getElementById("btn-save");
const btnModeEdit = document.getElementById("btn-mode-edit");
const btnModeDiff = document.getElementById("btn-mode-diff");
const diffStatsEl = document.getElementById("diff-stats");
const chatMessagesEl = document.getElementById("chat-messages");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const btnSend = document.getElementById("btn-send");
const btnNewSession = document.getElementById("btn-new-session");
const btnRenameSession = document.getElementById("btn-rename-session");
const btnUndo = document.getElementById("btn-undo");
const sessionSelectEl = document.getElementById("session-select");

let currentFile = null;
let viewMode = "edit";
let fileSnapshots = {};
let currentDiff = null;
let sessionId = null;
let sessionTurn = 0;
let sessionChanges = [];
let selectedChangeId = null;
/** @type {Array<object>} */
let chatLog = [];

function setViewMode(mode) {
  viewMode = mode;
  const isEdit = mode === "edit";
  editorEl.classList.toggle("hidden", !isEdit);
  diffViewEl.classList.toggle("hidden", isEdit);
  btnModeEdit.classList.toggle("active", isEdit);
  btnModeDiff.classList.toggle("active", !isEdit);
  btnSave.disabled = !currentFile || !isEdit;
}

function updateDiffTabState() {
  const hasDiff = Boolean(currentDiff);
  btnModeDiff.disabled = !currentFile || !hasDiff;
  if (!hasDiff) {
    diffStatsEl.classList.add("hidden");
    if (viewMode === "diff") setViewMode("edit");
  }
}

function renderDiff(oldText, newText) {
  if (typeof Diff === "undefined") {
    diffViewEl.textContent = "未加载 diff 库，请检查网络。";
    return { added: 0, removed: 0 };
  }

  const parts = Diff.diffLines(oldText || "", newText || "");
  diffViewEl.innerHTML = "";
  let added = 0;
  let removed = 0;
  let newLineNo = 1;

  for (const part of parts) {
    const lines = part.value.split("\n");
    if (lines.length && lines[lines.length - 1] === "") lines.pop();

    for (const line of lines) {
      const row = document.createElement("div");
      row.className = "diff-line";

      const gutter = document.createElement("span");
      gutter.className = "diff-gutter";
      const sign = document.createElement("span");
      sign.className = "diff-sign";
      const text = document.createElement("span");
      text.className = "diff-text";
      text.textContent = line;

      if (part.added) {
        row.classList.add("added");
        sign.textContent = "+";
        gutter.textContent = String(newLineNo++);
        added += 1;
      } else if (part.removed) {
        row.classList.add("removed");
        sign.textContent = "-";
        gutter.textContent = "";
        removed += 1;
      } else {
        row.classList.add("unchanged");
        sign.textContent = " ";
        gutter.textContent = String(newLineNo++);
      }

      row.appendChild(gutter);
      row.appendChild(sign);
      row.appendChild(text);
      diffViewEl.appendChild(row);
    }
  }

  return { added, removed };
}

function showDiff(oldText, newText, changeId = null) {
  currentDiff = { oldText, newText, changeId };
  const { added, removed } = renderDiff(oldText, newText);
  diffStatsEl.textContent = `+${added} -${removed}`;
  diffStatsEl.classList.remove("hidden");
  updateDiffTabState();
  setViewMode("diff");
  selectedChangeId = changeId;
  renderChat();
}

function clearDiff() {
  currentDiff = null;
  selectedChangeId = null;
  diffViewEl.innerHTML = "";
  updateDiffTabState();
  renderChat();
}

function formatChangeMeta(c) {
  const srcMap = { agent: "Agent", manual: "手动", rollback: "回退" };
  const src = srcMap[c.source] || c.source;
  const oldN = c.old_line_count ?? "?";
  const newN = c.new_line_count ?? "?";
  return { src, lines: `${oldN}→${newN} 行` };
}

function buildChangeRow(c) {
  const row = document.createElement("div");
  row.className = "chat-change-row";
  if (c.id === selectedChangeId) row.classList.add("active");
  row.dataset.changeId = c.id;

  const { src, lines } = formatChangeMeta(c);
  const info = document.createElement("span");
  info.className = "chat-change-info";
  info.textContent = `${c.path} · ${src} · ${lines}`;

  const actions = document.createElement("span");
  actions.className = "chat-change-actions";

  const btnView = document.createElement("button");
  btnView.type = "button";
  btnView.className = "btn-link";
  btnView.textContent = "查看变更";
  btnView.addEventListener("click", () => viewChange(c.id));

  actions.appendChild(btnView);
  row.appendChild(info);
  row.appendChild(actions);
  return row;
}

function createChangeBlockElement(turn, changes, { compact = false } = {}) {
  const block = document.createElement("div");
  block.className = "msg msg-changes";
  block.dataset.turn = String(turn);

  const title = document.createElement("div");
  title.className = "chat-change-title";
  title.textContent = compact ? "文件变更" : `第 ${turn} 轮 · 文件变更`;

  const list = document.createElement("div");
  list.className = "chat-change-list";
  for (const c of changes) {
    list.appendChild(buildChangeRow(normalizeChange(c)));
  }

  block.appendChild(title);
  block.appendChild(list);
  return block;
}

function normalizeChange(c) {
  const oldText = c.old_content ?? "";
  const newText = c.new_content ?? "";
  return {
    id: c.id,
    turn: c.turn,
    path: c.path,
    source: c.source || "agent",
    old_line_count: c.old_line_count ?? (oldText ? oldText.split("\n").length : 0),
    new_line_count: c.new_line_count ?? (newText ? newText.split("\n").length : 0),
    old_content: c.old_content,
    new_content: c.new_content,
  };
}

function maxTurnFromChatLog(log) {
  let max = 0;
  for (const item of log) {
    const t = item.turn;
    if (t != null) max = Math.max(max, Number(t));
  }
  return max;
}

function nextChatTurn() {
  return Math.max(sessionTurn, maxTurnFromChatLog(chatLog)) + 1;
}

function groupChatLogIntoTurns(log) {
  const preamble = [];
  const byTurn = new Map();

  for (const item of log) {
    if (item.type === "message" && (item.role === "system" || item.turn == null)) {
      preamble.push(item);
      continue;
    }
    if (item.type === "message") {
      const t = item.turn;
      if (!byTurn.has(t)) byTurn.set(t, { turn: t, messages: [], changes: [] });
      byTurn.get(t).messages.push(item);
    } else if (item.type === "changes") {
      const t = item.turn;
      if (!byTurn.has(t)) byTurn.set(t, { turn: t, messages: [], changes: [] });
      for (const c of item.changes || []) {
        byTurn.get(t).changes.push(normalizeChange(c));
      }
    }
  }

  const turns = [...byTurn.keys()]
    .sort((a, b) => a - b)
    .map((t) => byTurn.get(t));
  return { preamble, turns };
}

const TOOL_LABELS = {
  list_files: "list_files",
  read_file: "read_file",
  edit_file: "edit_file",
  write_file: "write_file",
  generate_title: "generate_title",
  agent: "agent",
};

function mergeStepsById(steps) {
  const order = [];
  const map = new Map();
  for (const s of steps || []) {
    if (!s || !s.id) continue;
    if (!map.has(s.id)) order.push(s.id);
    map.set(s.id, s);
  }
  return order.map((id) => map.get(id));
}

function stepStatusIcon(status) {
  if (status === "running") return "◌";
  if (status === "error") return "✕";
  return "✓";
}

function buildAgentStepsElement(steps, { active = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "agent-steps";
  const merged = mergeStepsById(steps);
  if (!merged.length && active) {
    const row = document.createElement("div");
    row.className = "agent-step agent-step-thinking agent-step-running";
    row.innerHTML =
      '<span class="agent-step-icon">◌</span><span class="agent-step-label">思考中…</span>';
    wrap.appendChild(row);
    return wrap;
  }
  for (const step of merged) {
    const row = document.createElement("div");
    const kind = step.kind || "tool";
    const tool = step.tool ? ` agent-step-tool-${step.tool}` : "";
    row.className = `agent-step agent-step-${kind} agent-step-${step.status || "done"}${tool}`;
    if (kind === "llm") row.classList.add("agent-step-llm");
    row.dataset.stepId = step.id;

    const icon = document.createElement("span");
    icon.className = "agent-step-icon";
    icon.textContent = stepStatusIcon(step.status);

    const body = document.createElement("span");
    body.className = "agent-step-body";

    const label = document.createElement("span");
    label.className = "agent-step-label";
    let labelText = step.label || "";
    if (step.tool && TOOL_LABELS[step.tool]) {
      labelText = `[${step.tool}] ${labelText}`;
    }
    label.textContent = labelText;
    body.appendChild(label);

    if (step.detail && step.status !== "running") {
      const detail = document.createElement("span");
      detail.className = "agent-step-detail";
      detail.textContent = step.detail;
      body.appendChild(detail);
    }

    row.appendChild(icon);
    row.appendChild(body);
    wrap.appendChild(row);
  }
  return wrap;
}

function findPendingAssistant(pendingId) {
  return chatLog.find((m) => m._pending === pendingId);
}

function upsertAgentStep(pendingId, step) {
  const msg = findPendingAssistant(pendingId);
  if (!msg) return;
  if (!msg.steps) msg.steps = [];
  const idx = msg.steps.findIndex((s) => s.id === step.id);
  if (idx >= 0) msg.steps[idx] = step;
  else msg.steps.push(step);
  renderChat();
}

function finalizePendingAssistant(pendingId, { text, steps }) {
  const msg = findPendingAssistant(pendingId);
  if (!msg) return;
  delete msg._pending;
  if (text != null) msg.text = text;
  if (steps) msg.steps = steps;
  renderChat();
}

function appendMessageElement(parent, item) {
  const div = document.createElement("div");
  div.className = `msg ${item.role}`;
  if (item._pending) div.classList.add("pending");

  const hasSteps = item.role === "assistant" && (item.steps?.length || item._pending);
  if (hasSteps) {
    div.appendChild(
      buildAgentStepsElement(item.steps || [], { active: Boolean(item._pending) })
    );
    const textEl = document.createElement("div");
    textEl.className = "msg-text";
    const bodyText =
      item.text ||
      (item._pending && !(item.steps && item.steps.length) ? "等待 Agent…" : "");
    if (bodyText) {
      textEl.textContent = bodyText;
      div.appendChild(textEl);
    }
  } else {
    div.textContent = item.text;
  }
  parent.appendChild(div);
}

function renderChat() {
  chatMessagesEl.innerHTML = "";
  const { preamble, turns } = groupChatLogIntoTurns(chatLog);

  for (const item of preamble) {
    appendMessageElement(chatMessagesEl, item);
  }

  for (const block of turns) {
    const section = document.createElement("div");
    section.className = "chat-turn-block";
    section.dataset.turn = String(block.turn);

    const divider = document.createElement("hr");
    divider.className = "chat-turn-divider";
    section.appendChild(divider);

    const header = document.createElement("div");
    header.className = "chat-turn-header";

    const hasPending = block.messages.some((m) => m._pending);
    const label = document.createElement("span");
    label.className = "chat-turn-label";
    label.textContent = hasPending ? `第 ${block.turn} 轮 · 进行中` : `第 ${block.turn} 轮`;

    if (!hasPending) {
      const btnRollback = document.createElement("button");
      btnRollback.type = "button";
      btnRollback.className = "btn-turn-rollback";
      btnRollback.textContent = "退回";
      btnRollback.title = `回退到第 ${block.turn} 轮之前（含对话与文件变更）`;
      btnRollback.addEventListener("click", () => rollbackToTurn(block.turn));
      header.appendChild(btnRollback);
    }
    header.appendChild(label);
    section.appendChild(header);

    for (const item of block.messages) {
      appendMessageElement(section, item);
    }

    if (block.changes.length) {
      section.appendChild(createChangeBlockElement(block.turn, block.changes, { compact: true }));
    }

    chatMessagesEl.appendChild(section);
  }

  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

function pushMessage(role, text, turn = null) {
  const entry = { type: "message", role, text };
  if (turn != null) entry.turn = turn;
  chatLog.push(entry);
  renderChat();
}

function pushChangeBlock(turn, changes) {
  if (!changes || !changes.length) return;
  const normalized = changes.map(normalizeChange);
  chatLog.push({ type: "changes", turn, changes: normalized });
  renderChat();
}

function syncChatLogChangesFromSession() {
  const validIds = new Set(sessionChanges.map((c) => c.id));
  chatLog = chatLog
    .map((item) => {
      if (item.type !== "changes") return item;
      const filtered = item.changes.filter((c) => validIds.has(c.id));
      if (!filtered.length) return null;
      return { ...item, changes: filtered.map((c) => {
        const fresh = sessionChanges.find((s) => s.id === c.id);
        return fresh ? { ...c, ...fresh } : c;
      }) };
    })
    .filter(Boolean);
  renderChat();
}

function rebuildHistoricalChangeBlocks() {
  if (chatLog.length > 0) return;
  const byTurn = new Map();
  for (const c of sessionChanges) {
    if (!byTurn.has(c.turn)) byTurn.set(c.turn, []);
    byTurn.get(c.turn).push(c);
  }
  const turns = [...byTurn.keys()].sort((a, b) => a - b);
  for (const turn of turns) {
    pushChangeBlock(turn, byTurn.get(turn));
  }
}

function hasChangesForFile(path) {
  if (!path) return sessionChanges.length > 0;
  return sessionChanges.some((c) => c.path === path);
}

function updateUndoButton() {
  btnUndo.disabled = !hasChangesForFile(currentFile);
}

async function handleRollbackResult(data) {
  clearDiff();
  await loadSession();
  await loadFileTree();
  const restored = data.restored_files || {};
  const paths = Object.keys(restored);
  const path =
    (data.path && paths.includes(data.path) ? data.path : null) ||
    (currentFile && paths.includes(currentFile) ? currentFile : null) ||
    paths[0];
  if (path) {
    const content = restored[path] ?? data.content ?? "";
    await openFile(path, { keepDiff: false });
    editorEl.value = content;
    fileSnapshots[path] = content;
  }
  setViewMode("edit");
  updateUndoButton();
}

async function rollbackToTurn(turn) {
  const msg =
    `确定回退到第 ${turn} 轮之前？\n` +
    `将撤销第 ${turn} 轮及之后的全部对话与文件变更，并恢复相关笔记内容。`;
  if (!confirm(msg)) return;

  const res = await fetch(`/api/session/turns/${turn}/rollback`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    alert("回退失败: " + (data.detail || res.statusText));
    return;
  }
  await handleRollbackResult(data);
}

async function rollbackLatest() {
  if (!currentFile && !sessionChanges.length) return;
  if (!confirm("确定撤销最近一轮对话及其文件变更？")) return;

  const url = currentFile
    ? `/api/session/rollback/latest?path=${encodeURIComponent(currentFile)}`
    : "/api/session/rollback/latest";
  const res = await fetch(url, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    alert("撤销失败: " + (data.detail || res.statusText));
    return;
  }
  await handleRollbackResult(data);
}

async function viewChange(changeId) {
  const res = await fetch(`/api/session/changes/${encodeURIComponent(changeId)}`);
  if (!res.ok) {
    alert("无法加载变更记录");
    return;
  }
  const data = await res.json();
  if (currentFile !== data.path) {
    await openFile(data.path, { keepDiff: true });
  }
  showDiff(data.old_content, data.new_content, changeId);
}

function getCurrentSessionTitle() {
  const opt = sessionSelectEl?.selectedOptions?.[0];
  if (!opt) return "新对话";
  const text = opt.textContent || "";
  const m = text.match(/^[●\s]*(.+?)\s+\([0-9a-f]+\)/i);
  return m ? m[1].trim() : text;
}

function applySessionsList(sessions, activeId) {
  renderSessionSelect(sessions, activeId || sessionId);
}

function formatSessionOption(s) {
  const title = s.title || "新对话";
  const meta = `${s.change_count || 0} 条变更`;
  const mark = s.is_active ? "● " : "";
  return `${mark}${title} (${s.id}) · ${meta}`;
}

function renderSessionSelect(sessions, activeId) {
  if (!sessionSelectEl) return;
  sessionSelectEl.innerHTML = "";
  for (const s of sessions || []) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = formatSessionOption({ ...s, is_active: s.id === activeId });
    if (s.id === activeId) opt.selected = true;
    sessionSelectEl.appendChild(opt);
  }
}

function syncDiffWithSession() {
  if (!currentDiff?.changeId) return;
  const stillExists = sessionChanges.some((c) => c.id === currentDiff.changeId);
  if (!stillExists) {
    clearDiff();
    if (currentFile) setViewMode("edit");
  }
}

function applySessionPayload(data) {
  sessionId = data.id || data.session_id;
  sessionTurn = Number(data.turn) || 0;
  sessionChanges = data.changes || [];
  if (Array.isArray(data.chat_log)) {
    chatLog = data.chat_log;
    sessionTurn = Math.max(sessionTurn, maxTurnFromChatLog(chatLog));
    renderChat();
  } else {
    chatLog = [];
    renderChat();
  }
  syncDiffWithSession();
  if (data.sessions) {
    renderSessionSelect(data.sessions, data.active_id || sessionId);
  }
  updateUndoButton();
}

async function loadSession() {
  const res = await fetch("/api/session");
  if (!res.ok) return;
  const data = await res.json();
  applySessionPayload(data);
}

async function activateSession(targetId) {
  if (!targetId || targetId === sessionId) return;
  const res = await fetch(`/api/session/${encodeURIComponent(targetId)}/activate`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("切换 Session 失败: " + (err.detail || res.statusText));
    return;
  }
  const data = await res.json();
  clearDiff();
  applySessionPayload(data);
  await loadFileTree();
  if (currentFile) {
    await openFile(currentFile, { keepDiff: false });
  }
}

async function newSession() {
  const res = await fetch("/api/session/new", { method: "POST" });
  if (!res.ok) {
    alert("新建 Session 失败");
    return;
  }
  clearDiff();
  await loadSession();
}

async function loadFileTree() {
  const res = await fetch("/api/files");
  const data = await res.json();
  fileTreeEl.innerHTML = "";
  for (const path of data.files || []) {
    const li = document.createElement("li");
    li.textContent = path;
    li.dataset.path = path;
    if (path === currentFile) li.classList.add("active");
    li.addEventListener("click", () => openFile(path));
    fileTreeEl.appendChild(li);
  }
}

async function fetchFileContent(path) {
  const res = await fetch(`/api/files/${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()).content;
}

async function openFile(path, options = {}) {
  const { keepDiff = false } = options;
  let content;
  try {
    content = await fetchFileContent(path);
  } catch (e) {
    alert("读取失败: " + e.message);
    return;
  }

  currentFile = path;
  editorEl.value = content;
  currentFileLabel.textContent = path;
  fileSnapshots[path] = content;

  if (!keepDiff) clearDiff();

  document.querySelectorAll(".file-tree li").forEach((li) => {
    li.classList.toggle("active", li.dataset.path === path);
  });

  btnSave.disabled = false;
  btnModeEdit.disabled = false;
  setViewMode(keepDiff && currentDiff ? "diff" : "edit");
  updateUndoButton();
}

async function applyLatestChangeForFile(path, changes) {
  const forFile = changes.filter((c) => c.path === path);
  if (!forFile.length) return;
  const latest = forFile[forFile.length - 1];
  let oldContent = latest.old_content;
  let newContent = latest.new_content;
  if (oldContent === undefined || newContent === undefined) {
    const detail = await fetch(`/api/session/changes/${latest.id}`).then((r) => r.json());
    oldContent = detail.old_content;
    newContent = detail.new_content;
  }
  await openFile(path, { keepDiff: true });
  editorEl.value = newContent;
  fileSnapshots[path] = newContent;
  showDiff(oldContent, newContent, latest.id);
}

async function saveFile() {
  if (!currentFile) return;
  const before = editorEl.value;
  btnSave.disabled = true;
  const res = await fetch(`/api/files/${encodeURIComponent(currentFile)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: before, record_change: true }),
  });
  btnSave.disabled = false;
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("保存失败: " + (err.detail || res.statusText));
    return;
  }

  const data = await res.json();
  fileSnapshots[currentFile] = before;

  await loadSession();

  if (data.change) {
    await applyLatestChangeForFile(currentFile, [data.change]);
  }
}

async function consumeChatStream(response, pendingId, pendingTurn) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let donePayload = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part
        .split("\n")
        .find((l) => l.startsWith("data:"));
      if (!line) continue;
      const jsonText = line.slice(5).trim();
      if (!jsonText) continue;
      let event;
      try {
        event = JSON.parse(jsonText);
      } catch {
        continue;
      }
      if (event.type === "step") {
        upsertAgentStep(pendingId, event);
      } else if (event.type === "error") {
        throw new Error(event.detail || "Agent 错误");
      } else if (event.type === "session_title") {
        if (event.sessions) {
          applySessionsList(event.sessions, event.active_id || sessionId);
        }
      } else if (event.type === "done") {
        donePayload = event;
        finalizePendingAssistant(pendingId, {
          text: event.reply,
          steps: event.steps,
        });
        if (event.session_title && event.sessions) {
          applySessionsList(event.sessions, event.active_id || sessionId);
        }
      }
    }
  }
  return donePayload;
}

async function afterChatDone(data) {
  sessionId = data.session_id;
  sessionTurn = data.turn ?? sessionTurn;
  await loadSession();
  await loadFileTree();

  if (data.written_files && data.written_files.length) {
    const written = data.written_files;
    const focus =
      currentFile && written.includes(currentFile)
        ? currentFile
        : written.length === 1
          ? written[0]
          : null;

    if (focus && data.changes && data.changes.length) {
      await applyLatestChangeForFile(focus, data.changes);
    } else if (focus) {
      clearDiff();
      await openFile(focus);
      setViewMode("edit");
    }
  } else {
    syncDiffWithSession();
  }
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  chatInput.value = "";
  btnSend.disabled = true;
  const pendingTurn = nextChatTurn();
  pushMessage("user", message, pendingTurn);

  const pendingId = "pending-" + Date.now();
  chatLog.push({
    type: "message",
    role: "assistant",
    text: "",
    steps: [],
    turn: pendingTurn,
    _pending: pendingId,
  });
  renderChat();

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, current_file: currentFile }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      chatLog = chatLog.filter((item) => item._pending !== pendingId);
      renderChat();
      pushMessage("assistant", "错误: " + (data.detail || res.statusText), pendingTurn);
      return;
    }

    const donePayload = await consumeChatStream(res, pendingId, pendingTurn);
    if (!donePayload) {
      chatLog = chatLog.filter((item) => item._pending !== pendingId);
      renderChat();
      pushMessage("assistant", "错误: 未收到完整响应", pendingTurn);
      return;
    }

    await afterChatDone(donePayload);
  } catch (err) {
    chatLog = chatLog.filter((item) => item._pending !== pendingId);
    renderChat();
    pushMessage("assistant", "请求失败: " + err.message, pendingTurn);
  } finally {
    btnSend.disabled = false;
  }
});

btnSave.addEventListener("click", saveFile);
btnModeEdit.addEventListener("click", () => currentFile && setViewMode("edit"));
btnModeDiff.addEventListener("click", () => currentDiff && setViewMode("diff"));
btnUndo.addEventListener("click", rollbackLatest);

sessionSelectEl.addEventListener("change", () => {
  activateSession(sessionSelectEl.value);
});

btnNewSession.addEventListener("click", async () => {
  await newSession();
});

btnRenameSession?.addEventListener("click", async () => {
  if (!sessionId) {
    alert("请先选择或新建 Session");
    return;
  }
  const current = getCurrentSessionTitle();
  const next = prompt("会话名称", current);
  if (next == null) return;
  const title = next.trim();
  if (!title) {
    alert("标题不能为空");
    return;
  }
  const res = await fetch(`/api/session/${encodeURIComponent(sessionId)}/title`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    alert("重命名失败: " + (data.detail || res.statusText));
    return;
  }
  if (data.sessions) {
    applySessionsList(data.sessions, data.active_id || sessionId);
  } else {
    await loadSession();
  }
});

(async function init() {
  await loadSession();
  await loadFileTree();
  const first = fileTreeEl.querySelector("li");
  if (first) await openFile(first.dataset.path);
})();
