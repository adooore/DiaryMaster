const fileTreeEl = document.getElementById("file-tree");
const editorEl = document.getElementById("editor");
const diffViewEl = document.getElementById("diff-view");
const editorPreviewEl = document.getElementById("editor-preview");
const currentFileLabel = document.getElementById("current-file-label");
const btnSave = document.getElementById("btn-save");
const btnModeEdit = document.getElementById("btn-mode-edit");
const btnModePreview = document.getElementById("btn-mode-preview");
const btnModeDiff = document.getElementById("btn-mode-diff");
const diffStatsEl = document.getElementById("diff-stats");
const chatMessagesEl = document.getElementById("chat-messages");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const btnSend = document.getElementById("btn-send");
const btnNewSession = document.getElementById("btn-new-session");
const sessionTabsEl = document.getElementById("session-tabs");
const appTooltipEl = document.getElementById("app-tooltip");
let appTooltipAnchor = null;
const sessionHistoryListEl = document.getElementById("session-history-list");
const panelHistoryEl = document.getElementById("panel-history");
const btnSessionHistory = document.getElementById("btn-session-history");
const resizeHandleHistory = document.querySelector('[data-resize="chat-history"]');
const layoutEl = document.getElementById("app-layout");
const sessionContextRingEl = document.getElementById("session-context-ring");
const modelPickerEl = document.getElementById("model-picker");
const modelPickerTrigger = document.getElementById("model-picker-trigger");
const modelPickerLabel = document.getElementById("model-picker-label");
const modelPickerMenu = document.getElementById("model-picker-menu");
let composerModelId = "";
const thinkingToggleEl = document.getElementById("thinking-toggle");
const CONTEXT_RING_R = 8;
const CONTEXT_RING_C = 2 * Math.PI * CONTEXT_RING_R;
const MODEL_STORAGE_KEY = "diarymaster-model-id";
const MODEL_STORAGE_KEY_LEGACY = "deepnote-model-id";
const THINKING_STORAGE_KEY = "diarymaster-thinking-enabled";
const THINKING_STORAGE_KEY_LEGACY = "deepnote-thinking-enabled";
const LAYOUT_STORAGE_KEY = "diarymaster-layout-v1";
const LAYOUT_STORAGE_KEY_LEGACY = "deepnote-layout-v1";
const TABS_STORAGE_KEY = "diarymaster-open-tabs";
const TABS_STORAGE_KEY_LEGACY = "deepnote-open-tabs";
const HISTORY_OPEN_STORAGE_KEY = "diarymaster-history-open";
const THEME_STORAGE_KEY = "diarymaster-theme";
const THEME_STORAGE_KEY_LEGACY = "deepnote-theme";

function readStorageItem(primary, legacy) {
  try {
    return localStorage.getItem(primary) || (legacy ? localStorage.getItem(legacy) : null);
  } catch {
    return null;
  }
}

let modelsCatalog = [];
let defaultModelId = "deepseek-v4-flash";

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
/** @type {Array<object>} */
let sessionsList = [];
/** @type {string[]} */
let openTabIds = [];
let historyPanelOpen = false;

function refreshEditorPreview() {
  if (!editorPreviewEl) return;
  const text = editorEl.value;
  if (!text.trim()) {
    editorPreviewEl.innerHTML =
      '<p class="editor-preview-empty">暂无内容，请在「编辑」中输入 Markdown。</p>';
    return;
  }
  editorPreviewEl.innerHTML = renderMarkdownToHtml(text);
}

function setViewMode(mode) {
  viewMode = mode;
  const isEdit = mode === "edit";
  const isPreview = mode === "preview";
  const isDiff = mode === "diff";

  editorEl.classList.toggle("hidden", !isEdit);
  if (editorPreviewEl) editorPreviewEl.classList.toggle("hidden", !isPreview);
  diffViewEl.classList.toggle("hidden", !isDiff);

  btnModeEdit.classList.toggle("active", isEdit);
  if (btnModePreview) btnModePreview.classList.toggle("active", isPreview);
  btnModeDiff.classList.toggle("active", isDiff);

  btnSave.disabled = !currentFile || !isEdit;

  if (isPreview) refreshEditorPreview();
}

function updateEditorViewTabs() {
  const hasFile = Boolean(currentFile);
  btnModeEdit.disabled = !hasFile;
  if (btnModePreview) btnModePreview.disabled = !hasFile;

  const hasDiff = Boolean(currentDiff);
  btnModeDiff.disabled = !hasFile || !hasDiff;
  if (!hasDiff) {
    diffStatsEl.classList.add("hidden");
    if (viewMode === "diff") setViewMode("edit");
  }
}

function updateDiffTabState() {
  updateEditorViewTabs();
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

function configureMarkdownRenderer() {
  if (typeof marked === "undefined") return;
  marked.setOptions({
    gfm: true,
    breaks: true,
    headerIds: false,
    mangle: false,
  });
}
configureMarkdownRenderer();

function renderMarkdownToHtml(text) {
  if (!text) return "";
  if (typeof marked === "undefined") {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\n/g, "<br>");
  }
  const raw = marked.parse(text);
  if (typeof DOMPurify !== "undefined") {
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  }
  return raw;
}

/** Agent 回复用 Markdown；用户消息保持纯文本 */
function setMessageBody(el, text, role) {
  if (!text) return;
  if (role === "assistant") {
    el.classList.add("markdown-body");
    el.innerHTML = renderMarkdownToHtml(text);
  } else {
    el.classList.remove("markdown-body");
    el.textContent = text;
  }
}

const TOOL_LABELS = {
  list_files: "list_files",
  read_file: "read_file",
  edit_file: "edit_file",
  write_file: "write_file",
  generate_title: "generate_title",
  agent: "agent",
};

function effectiveAssistantSteps(item) {
  const steps = item.steps ? [...item.steps] : [];
  if (!item.reasoning) return steps;
  if (steps.some((s) => s.kind === "reasoning")) return steps;
  return [
    {
      id: `reasoning-${item.turn || "hist"}`,
      kind: "reasoning",
      status: "done",
      label: "思考过程",
      detail: item.reasoning,
    },
    ...steps,
  ];
}

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

function partitionSteps(steps) {
  const merged = mergeStepsById(steps);
  const header = merged.filter((s) => s.kind === "reply_status");
  const main = merged.filter((s) => s.kind !== "reply_status");
  return { main, header };
}

function isStepsFlowComplete(steps) {
  const { header } = partitionSteps(steps);
  return header.some(
    (s) =>
      s.kind === "reply_status" && (s.status === "done" || s.status === "error")
  );
}

/** 完成后默认折叠；进行中始终展开 */
function resolveStepsCollapsed(item) {
  if (item._pending) return false;
  const steps = item.steps || [];
  const { main } = partitionSteps(steps);
  if (!main.length || !isStepsFlowComplete(steps)) return false;
  if (item.stepsCollapsed === undefined) return true;
  return Boolean(item.stepsCollapsed);
}

function createAgentStepRow(step) {
  const row = document.createElement("div");
  const kind = step.kind || "tool";
  const tool = step.tool ? ` agent-step-tool-${step.tool}` : "";
  row.className = `agent-step agent-step-${kind} agent-step-${step.status || "done"}${tool}`;
  if (kind === "llm") row.classList.add("agent-step-llm");
  if (kind === "reasoning") row.classList.add("agent-step-reasoning");
  if (kind === "reply_status") row.classList.add("agent-step-reply-status");
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

  if (step.detail && (step.status !== "running" || kind === "reasoning")) {
    const detail = document.createElement("span");
    detail.className = "agent-step-detail";
    detail.textContent = step.detail;
    body.appendChild(detail);
  }

  row.appendChild(icon);
  row.appendChild(body);
  return row;
}

function buildAgentStepsElement(
  steps,
  { active = false, collapsed = false, onToggle = null } = {}
) {
  const wrap = document.createElement("div");
  wrap.className = "agent-steps";
  const { main, header } = partitionSteps(steps);
  if (!main.length && !header.length && active) {
    const row = document.createElement("div");
    row.className = "agent-step agent-step-thinking agent-step-running";
    row.innerHTML =
      '<span class="agent-step-icon">◌</span><span class="agent-step-label">思考中…</span>';
    wrap.appendChild(row);
    return wrap;
  }
  if (header.length) {
    const canToggle = Boolean(onToggle) && main.length > 0;
    const headerWrap = document.createElement("div");
    headerWrap.className = "agent-steps-header";
    if (canToggle) {
      headerWrap.classList.add("agent-steps-toggle");
      headerWrap.setAttribute("role", "button");
      headerWrap.tabIndex = 0;
      headerWrap.setAttribute("aria-expanded", collapsed ? "false" : "true");
      headerWrap.dataset.tooltip = collapsed ? "点击展开执行过程" : "点击折叠执行过程";

      const chevron = document.createElement("span");
      chevron.className = "agent-steps-chevron";
      chevron.setAttribute("aria-hidden", "true");
      chevron.textContent = collapsed ? "▸" : "▾";
      headerWrap.appendChild(chevron);

      const activateToggle = (e) => {
        if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        onToggle();
      };
      headerWrap.addEventListener("click", activateToggle);
      headerWrap.addEventListener("keydown", activateToggle);
    }

    const headerInner = document.createElement("div");
    headerInner.className = "agent-steps-header-inner";
    for (const step of header) {
      headerInner.appendChild(createAgentStepRow(step));
    }
    headerWrap.appendChild(headerInner);
    wrap.appendChild(headerWrap);
  }

  if (main.length) {
    const body = document.createElement("div");
    body.className = "agent-steps-body";
    for (const step of main) {
      body.appendChild(createAgentStepRow(step));
    }
    wrap.appendChild(body);
  }

  if (collapsed && main.length) {
    wrap.classList.add("agent-steps-collapsed");
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

function finalizePendingAssistant(pendingId, { text, steps, reasoning }) {
  const msg = findPendingAssistant(pendingId);
  if (!msg) return;
  delete msg._pending;
  if (text != null) msg.text = text;
  if (steps) msg.steps = steps;
  if (reasoning) msg.reasoning = reasoning;
  if (isStepsFlowComplete(msg.steps || [])) {
    msg.stepsCollapsed = true;
  }
  renderChat();
}

function appendMessageElement(parent, item) {
  const div = document.createElement("div");
  div.className = `msg ${item.role}`;
  if (item._pending) div.classList.add("pending");

  const hasSteps =
    item.role === "assistant" &&
    (item.steps?.length || item.reasoning || item._pending);
  if (hasSteps) {
    const steps = effectiveAssistantSteps(item);
    const collapsed = resolveStepsCollapsed(item);
    const canToggle =
      !item._pending && isStepsFlowComplete(steps) && partitionSteps(steps).main.length > 0;
    div.appendChild(
      buildAgentStepsElement(steps, {
        active: Boolean(item._pending),
        collapsed,
        onToggle: canToggle
          ? () => {
              item.stepsCollapsed = !resolveStepsCollapsed(item);
              renderChat();
            }
          : null,
      })
    );
    const textEl = document.createElement("div");
    textEl.className = "msg-text";
    const bodyText =
      item.text ||
      (item._pending && !(item.steps && item.steps.length) ? "等待 Agent…" : "");
    if (bodyText) {
      setMessageBody(textEl, bodyText, item.role);
      div.appendChild(textEl);
    }
  } else if (item.text) {
    if (item.role === "assistant") {
      const textEl = document.createElement("div");
      textEl.className = "msg-text";
      setMessageBody(textEl, item.text, item.role);
      div.appendChild(textEl);
    } else {
      div.textContent = item.text;
    }
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
      btnRollback.dataset.tooltip = `回退到第 ${block.turn} 轮之前（含对话与文件变更）`;
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
  const s = sessionsList.find((x) => x.id === sessionId);
  return s?.title?.trim() || "新对话";
}

function formatTokenCount(n) {
  if (n >= 10000) return `${(n / 1000).toFixed(1)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function updateContextRing(ctx) {
  if (!sessionContextRingEl) return;
  const progress = sessionContextRingEl.querySelector(".context-ring-progress");
  if (!ctx?.limit_tokens || !progress) {
    sessionContextRingEl.classList.add("hidden");
    delete sessionContextRingEl.dataset.tooltip;
    return;
  }

  const pct = Math.min(100, Math.max(0, Number(ctx.percent) || 0));
  const filled = (CONTEXT_RING_C * pct) / 100;
  progress.setAttribute("stroke-dasharray", `${filled} ${CONTEXT_RING_C}`);

  const used = formatTokenCount(ctx.used_tokens);
  const limit = formatTokenCount(ctx.limit_tokens);
  const sourceNote =
    ctx.used_tokens === 0
      ? ""
      : ctx.is_estimate
        ? " · 字符估算"
        : ctx.source === "api"
          ? " · API 计量"
          : "";
  const modelNote = ctx.model ? ` · ${ctx.model}` : "";

  sessionContextRingEl.dataset.tooltip =
    ctx.used_tokens === 0
      ? `尚未占用上下文 · 发送首条消息后显示${modelNote}`
      : `${pct}% 上下文已用 · ${used} / ${limit} tokens${sourceNote}${modelNote}`;
  sessionContextRingEl.dataset.tooltipPlacement = "above";

  sessionContextRingEl.setAttribute(
    "aria-label",
    `上下文已用 ${pct}%，约 ${used} / ${limit} tokens`
  );
  sessionContextRingEl.classList.remove("hidden", "ctx-warn", "ctx-critical");
  if (pct >= 95) sessionContextRingEl.classList.add("ctx-critical");
  else if (pct >= 80) sessionContextRingEl.classList.add("ctx-warn");
}

function updateSessionMeta(_sessions, _activeId, contextUsage) {
  if (contextUsage) updateContextRing(contextUsage);
}

function getSelectedModelId() {
  if (composerModelId) return composerModelId;
  try {
    return (
      readStorageItem(MODEL_STORAGE_KEY, MODEL_STORAGE_KEY_LEGACY) || defaultModelId
    );
  } catch {
    return defaultModelId;
  }
}

function setComposerModelId(modelId, { persist = true } = {}) {
  const id = modelId || defaultModelId;
  composerModelId = id;
  if (persist) {
    try {
      localStorage.setItem(MODEL_STORAGE_KEY, id);
    } catch {
      /* ignore */
    }
  }
  const spec = modelsCatalog.find((m) => m.id === id);
  if (modelPickerLabel) {
    modelPickerLabel.textContent = spec?.label || id;
  }
  if (modelPickerMenu) {
    modelPickerMenu.querySelectorAll(".model-picker-option").forEach((el) => {
      const selected = el.dataset.id === id;
      el.setAttribute("aria-selected", selected ? "true" : "false");
    });
  }
  syncThinkingToggleForModel(id);
}

function setModelPickerOpen(open) {
  if (!modelPickerEl || !modelPickerTrigger || !modelPickerMenu) return;
  const isOpen = Boolean(open);
  if (isOpen) hideAppTooltip();
  modelPickerEl.classList.toggle("is-open", isOpen);
  modelPickerTrigger.setAttribute("aria-expanded", isOpen ? "true" : "false");
  modelPickerMenu.classList.toggle("hidden", !isOpen);
}

function toggleModelPicker() {
  setModelPickerOpen(!modelPickerEl?.classList.contains("is-open"));
}

function isThinkingEnabled() {
  if (thinkingToggleEl) return thinkingToggleEl.checked;
  try {
    return readStorageItem(THINKING_STORAGE_KEY, THINKING_STORAGE_KEY_LEGACY) === "1";
  } catch {
    return false;
  }
}

function syncThinkingToggleForModel(modelId) {
  if (!thinkingToggleEl || !modelPickerEl) return;
  const spec = modelsCatalog.find((m) => m.id === modelId);
  const supported = spec?.supports_thinking !== false;
  thinkingToggleEl.disabled = !supported;
  if (!supported) thinkingToggleEl.checked = false;
}

async function refreshContextUsage() {
  const modelId = getSelectedModelId();
  const res = await fetch(
    `/api/session/context-usage?model_id=${encodeURIComponent(modelId)}`
  );
  if (!res.ok) return;
  const ctx = await res.json();
  updateContextRing(ctx);
}

function applyContextUsageFromDone(usage) {
  if (!usage?.prompt_tokens) {
    refreshContextUsage();
    return;
  }
  const modelId = getSelectedModelId();
  const spec = modelsCatalog.find((m) => m.id === modelId);
  const limit = spec?.context_limit || usage.prompt_tokens * 2;
  const used = usage.prompt_tokens;
  const pct = Math.min(100, Math.round((used / limit) * 1000) / 10);
  updateContextRing({
    used_tokens: used,
    limit_tokens: limit,
    percent: pct,
    model: spec?.label || modelId,
    model_id: modelId,
    source: usage.source || "api",
    is_estimate: usage.source === "estimate",
  });
}

async function loadModelsCatalog() {
  const res = await fetch("/api/models");
  if (!res.ok) return;
  const data = await res.json();
  modelsCatalog = data.models || [];
  defaultModelId = data.default_model_id || defaultModelId;

  let saved = defaultModelId;
  try {
    saved =
      readStorageItem(MODEL_STORAGE_KEY, MODEL_STORAGE_KEY_LEGACY) || defaultModelId;
  } catch {
    /* ignore */
  }
  if (!modelsCatalog.some((m) => m.id === saved)) saved = defaultModelId;

  if (modelPickerMenu) {
    modelPickerMenu.innerHTML = "";
    for (const m of modelsCatalog) {
      const li = document.createElement("li");
      li.className = "model-picker-option";
      li.setAttribute("role", "option");
      li.dataset.id = m.id;
      li.textContent = m.label || m.id;
      li.addEventListener("click", (e) => {
        e.stopPropagation();
        setComposerModelId(m.id);
        setModelPickerOpen(false);
        refreshContextUsage();
      });
      modelPickerMenu.appendChild(li);
    }
  }

  setComposerModelId(saved, { persist: false });
}

function initComposerPrefs() {
  if (!thinkingToggleEl) return;

  try {
    thinkingToggleEl.checked =
      readStorageItem(THINKING_STORAGE_KEY, THINKING_STORAGE_KEY_LEGACY) === "1";
  } catch {
    thinkingToggleEl.checked = false;
  }

  if (modelPickerTrigger) {
    modelPickerTrigger.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleModelPicker();
    });
  }

  document.addEventListener("click", (e) => {
    if (!modelPickerEl?.classList.contains("is-open")) return;
    if (modelPickerEl.contains(e.target)) return;
    setModelPickerOpen(false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") setModelPickerOpen(false);
  });

  thinkingToggleEl.addEventListener("change", () => {
    try {
      localStorage.setItem(
        THINKING_STORAGE_KEY,
        thinkingToggleEl.checked ? "1" : "0"
      );
    } catch {
      /* ignore */
    }
  });
}

function formatSessionTitle(s) {
  return (s?.title || "").trim() || "新对话";
}

function loadOpenTabs() {
  try {
    const raw = readStorageItem(TABS_STORAGE_KEY, TABS_STORAGE_KEY_LEGACY);
    openTabIds = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(openTabIds)) openTabIds = [];
  } catch {
    openTabIds = [];
  }
}

function saveOpenTabs() {
  try {
    localStorage.setItem(TABS_STORAGE_KEY, JSON.stringify(openTabIds));
  } catch {
    /* ignore */
  }
}

function ensureTabOpen(id) {
  if (!id || openTabIds.includes(id)) return;
  openTabIds.push(id);
  saveOpenTabs();
}

function pruneOpenTabs() {
  const valid = new Set((sessionsList || []).map((s) => s.id));
  openTabIds = openTabIds.filter((id) => valid.has(id));
  if (sessionId && !openTabIds.includes(sessionId)) {
    openTabIds.push(sessionId);
  }
  if (!openTabIds.length && sessionId) openTabIds.push(sessionId);
  saveOpenTabs();
}

function closeTab(id, ev) {
  ev?.stopPropagation();
  ev?.preventDefault();
  const idx = openTabIds.indexOf(id);
  if (idx < 0) return;
  openTabIds.splice(idx, 1);
  if (!openTabIds.length && sessionId) {
    openTabIds.push(sessionId);
  }
  saveOpenTabs();
  if (id === sessionId) {
    const next = openTabIds[Math.min(idx, openTabIds.length - 1)] || openTabIds[0];
    if (next && next !== sessionId) activateSession(next);
    else renderSessionTabs();
  } else {
    renderSessionTabs();
  }
}

function formatSessionDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString("zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function hideAppTooltip() {
  if (!appTooltipEl) return;
  appTooltipEl.classList.add("hidden");
  appTooltipEl.setAttribute("aria-hidden", "true");
  if (appTooltipAnchor) {
    appTooltipAnchor.removeAttribute("aria-describedby");
    appTooltipAnchor = null;
  }
}

function layoutAppTooltip(anchor, placement) {
  if (!appTooltipEl || !anchor) return;
  const gap = 8;
  const margin = 8;
  const rect = anchor.getBoundingClientRect();
  appTooltipEl.classList.remove("app-tooltip-above", "app-tooltip-below");
  appTooltipEl.classList.add(placement === "above" ? "app-tooltip-above" : "app-tooltip-below");
  appTooltipEl.classList.remove("hidden");
  const tipRect = appTooltipEl.getBoundingClientRect();
  let left = rect.left + (rect.width - tipRect.width) / 2;
  let top =
    placement === "above" ? rect.top - gap - tipRect.height : rect.bottom + gap;
  left = Math.max(margin, Math.min(left, window.innerWidth - tipRect.width - margin));
  top = Math.max(margin, Math.min(top, window.innerHeight - tipRect.height - margin));
  appTooltipEl.style.left = `${Math.round(left)}px`;
  appTooltipEl.style.top = `${Math.round(top)}px`;
  const anchorCenterX = rect.left + rect.width / 2;
  appTooltipEl.style.setProperty("--arrow-x", `${Math.round(anchorCenterX - left)}px`);
}

function showAppTooltip(anchor, text, placement = "below") {
  if (!appTooltipEl || !anchor || !text) return;
  if (modelPickerEl?.classList.contains("is-open") && modelPickerEl.contains(anchor)) return;
  hideAppTooltip();
  appTooltipAnchor = anchor;
  appTooltipEl.textContent = text;
  appTooltipEl.setAttribute("aria-hidden", "false");
  layoutAppTooltip(anchor, placement);
  anchor.setAttribute("aria-describedby", "app-tooltip");
}

function tooltipHostFromTarget(target) {
  if (!target?.closest) return null;
  return target.closest("[data-tooltip]");
}

function migrateNativeTitles(root = document) {
  root.querySelectorAll("[title]").forEach((el) => {
    const native = el.getAttribute("title")?.trim();
    if (!native) return;
    if (!el.dataset.tooltip) el.dataset.tooltip = native;
    el.removeAttribute("title");
  });
}

function initAppTooltip() {
  if (!appTooltipEl) return;
  migrateNativeTitles();

  document.addEventListener("mouseover", (e) => {
    const host = tooltipHostFromTarget(e.target);
    if (!host?.dataset.tooltip || host.contains(e.relatedTarget)) return;
    const placement = host.dataset.tooltipPlacement || "below";
    showAppTooltip(host, host.dataset.tooltip, placement);
  });

  document.addEventListener("mouseout", (e) => {
    const host = tooltipHostFromTarget(e.target);
    if (!host) return;
    const rel = e.relatedTarget;
    if (rel && host.contains(rel)) return;
    if (appTooltipAnchor === host) hideAppTooltip();
  });

  document.addEventListener("focusin", (e) => {
    const host = tooltipHostFromTarget(e.target);
    if (!host?.dataset.tooltip) return;
    showAppTooltip(host, host.dataset.tooltip, host.dataset.tooltipPlacement || "below");
  });

  document.addEventListener("focusout", (e) => {
    const host = tooltipHostFromTarget(e.target);
    if (host && appTooltipAnchor === host) hideAppTooltip();
  });

  window.addEventListener("scroll", hideAppTooltip, { passive: true, capture: true });
  window.addEventListener("resize", hideAppTooltip);
}

function renderSessionTabs() {
  if (!sessionTabsEl) return;
  hideAppTooltip();
  sessionTabsEl.innerHTML = "";
  const active = sessionId;
  for (const id of openTabIds) {
    const s = sessionsList.find((x) => x.id === id);
    if (!s) continue;
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "session-tab" + (id === active ? " active" : "");
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", id === active ? "true" : "false");
    tab.dataset.id = id;
    tab.setAttribute("aria-label", formatSessionTitle(s));

    const title = document.createElement("span");
    title.className = "session-tab-title";
    title.textContent = formatSessionTitle(s);

    if (s.change_count > 0) {
      const badge = document.createElement("span");
      badge.className = "session-tab-badge";
      badge.textContent = String(s.change_count);
      badge.dataset.tooltip = `${s.change_count} 条文件变更`;
      tab.appendChild(title);
      tab.appendChild(badge);
    } else {
      tab.appendChild(title);
    }

    const closeBtn = document.createElement("span");
    closeBtn.className = "session-tab-close";
    closeBtn.setAttribute("role", "button");
    closeBtn.setAttribute("aria-label", "关闭标签");
    closeBtn.textContent = "×";

    tab.appendChild(closeBtn);

    tab.addEventListener("click", () => {
      if (id !== sessionId) activateSession(id);
    });
    closeBtn.addEventListener("click", (e) => closeTab(id, e));

    sessionTabsEl.appendChild(tab);
  }
}

function renderHistoryList() {
  if (!sessionHistoryListEl) return;
  sessionHistoryListEl.innerHTML = "";
  const items = [...(sessionsList || [])].sort((a, b) =>
    (b.created_at || "").localeCompare(a.created_at || "")
  );
  for (const s of items) {
    const li = document.createElement("li");
    li.className = "session-history-item" + (s.id === sessionId ? " active" : "");
    li.dataset.id = s.id;

    const titleEl = document.createElement("div");
    titleEl.className = "session-history-title";
    titleEl.textContent = formatSessionTitle(s);

    const meta = document.createElement("div");
    meta.className = "session-history-meta";
    const parts = [];
    if (s.turn) parts.push(`${s.turn} 轮`);
    const when = formatSessionDate(s.created_at);
    if (when) parts.push(when);
    meta.textContent = parts.join(" · ") || s.id;

    const main = document.createElement("button");
    main.type = "button";
    main.className = "session-history-main";
    main.appendChild(titleEl);
    main.appendChild(meta);
    main.addEventListener("click", () => selectSessionFromHistory(s.id));

    const actions = document.createElement("div");
    actions.className = "session-history-actions";

    const renameBtn = document.createElement("button");
    renameBtn.type = "button";
    renameBtn.className = "session-history-action icon-btn";
    renameBtn.dataset.tooltip = "重命名";
    renameBtn.setAttribute("aria-label", "重命名对话");
    renameBtn.textContent = "✎";
    renameBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      renameSession(s.id);
    });

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "session-history-action session-history-delete icon-btn";
    deleteBtn.dataset.tooltip = "删除对话";
    deleteBtn.setAttribute("aria-label", "删除对话");
    deleteBtn.textContent = "×";
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteSession(s.id);
    });

    actions.appendChild(renameBtn);
    actions.appendChild(deleteBtn);

    li.appendChild(main);
    li.appendChild(actions);
    sessionHistoryListEl.appendChild(li);
  }
}

async function selectSessionFromHistory(id) {
  ensureTabOpen(id);
  if (id !== sessionId) await activateSession(id);
  else syncSessionsUI();
}

async function deleteSession(targetId) {
  const res = await fetch(`/api/session/${encodeURIComponent(targetId)}`, {
    method: "DELETE",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    alert("删除失败: " + (data.detail || res.statusText));
    return;
  }

  openTabIds = openTabIds.filter((id) => id !== targetId);
  saveOpenTabs();

  clearDiff();
  applySessionPayload(data);
  await loadFileTree();
  if (currentFile) {
    await openFile(currentFile, { keepDiff: false });
  }
}

async function renameSession(targetId) {
  const s = sessionsList.find((x) => x.id === targetId);
  const current = formatSessionTitle(s);
  const next = prompt("会话名称", current);
  if (next == null) return;
  const title = next.trim();
  if (!title) {
    alert("标题不能为空");
    return;
  }
  const res = await fetch(`/api/session/${encodeURIComponent(targetId)}/title`, {
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
}

function setHistoryPanelOpen(open) {
  historyPanelOpen = Boolean(open);
  if (!layoutEl) return;

  layoutEl.classList.toggle("history-open", historyPanelOpen);
  if (panelHistoryEl) panelHistoryEl.classList.toggle("hidden", !historyPanelOpen);
  if (resizeHandleHistory) {
    resizeHandleHistory.classList.toggle("hidden", !historyPanelOpen);
  }
  if (btnSessionHistory) {
    btnSessionHistory.classList.toggle("active", historyPanelOpen);
    btnSessionHistory.setAttribute("aria-pressed", historyPanelOpen ? "true" : "false");
  }

  if (historyPanelOpen) {
    let w = readCssPx(layoutEl, "--col-history", 300);
    if (w < 200) w = 300;
    layoutEl.style.setProperty("--col-history", `${Math.round(w)}px`);
  } else {
    layoutEl.style.setProperty("--col-history", "0px");
  }

  try {
    localStorage.setItem(HISTORY_OPEN_STORAGE_KEY, historyPanelOpen ? "1" : "0");
  } catch {
    /* ignore */
  }

  renderHistoryList();
  clampLayoutWidths();
}

function toggleHistoryPanel() {
  setHistoryPanelOpen(!historyPanelOpen);
}

function applySessionsList(sessions, activeId, contextUsage) {
  sessionsList = sessions || [];
  const active = activeId || sessionId;
  pruneOpenTabs();
  ensureTabOpen(active);
  renderSessionTabs();
  renderHistoryList();
  updateSessionMeta(sessionsList, active, contextUsage);
}

function syncSessionsUI() {
  applySessionsList(sessionsList, sessionId);
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
    applySessionsList(data.sessions, data.active_id || sessionId);
  } else {
    syncSessionsUI();
  }
  refreshContextUsage();
}

async function loadSession() {
  const res = await fetch("/api/session");
  if (!res.ok) return;
  const data = await res.json();
  applySessionPayload(data);
}

async function activateSession(targetId) {
  if (!targetId || targetId === sessionId) {
    ensureTabOpen(targetId);
    syncSessionsUI();
    return;
  }
  ensureTabOpen(targetId);
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
  updateEditorViewTabs();
  setViewMode(keepDiff && currentDiff ? "diff" : "edit");
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
          reasoning: event.reasoning,
        });
        if (event.usage) applyContextUsageFromDone(event.usage);
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
      body: JSON.stringify({
        message,
        current_file: currentFile,
        model_id: getSelectedModelId(),
        thinking_enabled: isThinkingEnabled(),
      }),
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
btnModePreview?.addEventListener("click", () => currentFile && setViewMode("preview"));
btnModeDiff.addEventListener("click", () => currentDiff && setViewMode("diff"));

btnSessionHistory?.addEventListener("click", () => toggleHistoryPanel());

btnNewSession.addEventListener("click", async () => {
  await newSession();
});

const VALID_THEMES = ["dark", "blossom"];

function initTheme() {
  const root = document.documentElement;
  const buttons = document.querySelectorAll(".theme-btn[data-theme]");
  if (!buttons.length) return;

  function apply(theme) {
    const next = VALID_THEMES.includes(theme) ? theme : "dark";
    root.setAttribute("data-theme", next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
    buttons.forEach((btn) => {
      const on = btn.dataset.theme === next;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  const saved = readStorageItem(THEME_STORAGE_KEY, THEME_STORAGE_KEY_LEGACY);
  apply(saved || root.getAttribute("data-theme") || "dark");

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => apply(btn.dataset.theme));
  });
}

function clamp(n, min, max) {
  return Math.min(max, Math.max(min, n));
}

function readCssPx(layoutEl, name, fallback) {
  const raw = getComputedStyle(layoutEl).getPropertyValue(name).trim();
  if (!raw) return fallback;
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : fallback;
}

function saveLayoutWidths(treePx, chatPx, historyPx) {
  try {
    const payload = {
      tree: Math.round(treePx),
      chat: Math.round(chatPx),
    };
    if (historyPx != null && historyPx > 0) {
      payload.history = Math.round(historyPx);
    }
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* ignore quota */
  }
}

function historyPanelWidthPx() {
  if (!layoutEl || !historyPanelOpen) return 0;
  return readCssPx(layoutEl, "--col-history", 0);
}

function layoutHandleCount() {
  let n = 2;
  if (historyPanelOpen) n += 1;
  return n;
}

function clampLayoutWidths() {
  if (!layoutEl) return;
  const treeMin = readCssPx(layoutEl, "--tree-min", 160);
  const treeMax = readCssPx(layoutEl, "--tree-max", 420);
  const chatMin = readCssPx(layoutEl, "--chat-min", 300);
  const chatMax = Math.min(
    readCssPx(layoutEl, "--chat-max", 720),
    Math.floor(window.innerWidth * 0.55)
  );
  const historyMin = readCssPx(layoutEl, "--history-min", 220);
  const historyMax = readCssPx(layoutEl, "--history-max", 480);
  const editorMin = readCssPx(layoutEl, "--editor-min", 280);
  const handleWidth = 5;
  const handles = layoutHandleCount() * handleWidth;

  const tree = readCssPx(layoutEl, "--col-tree", 240);
  const chat = readCssPx(layoutEl, "--col-chat", 400);
  let history = historyPanelWidthPx();

  const maxTree = clamp(
    layoutEl.clientWidth - chat - history - editorMin - handles,
    treeMin,
    treeMax
  );
  const maxChat = clamp(
    layoutEl.clientWidth - tree - history - editorMin - handles,
    chatMin,
    chatMax
  );
  const maxHistory = historyPanelOpen
    ? clamp(
        layoutEl.clientWidth - tree - chat - editorMin - handles,
        historyMin,
        historyMax
      )
    : 0;

  layoutEl.style.setProperty("--col-tree", `${clamp(tree, treeMin, maxTree)}px`);
  layoutEl.style.setProperty("--col-chat", `${clamp(chat, chatMin, maxChat)}px`);
  if (historyPanelOpen) {
    layoutEl.style.setProperty(
      "--col-history",
      `${clamp(history, historyMin, maxHistory)}px`
    );
  }
}

function initLayoutResize() {
  if (!layoutEl) return;

  const treeMin = readCssPx(layoutEl, "--tree-min", 160);
  const treeMax = readCssPx(layoutEl, "--tree-max", 420);
  const chatMin = readCssPx(layoutEl, "--chat-min", 300);
  const chatMax = Math.min(
    readCssPx(layoutEl, "--chat-max", 720),
    Math.floor(window.innerWidth * 0.55)
  );
  const historyMin = readCssPx(layoutEl, "--history-min", 220);
  const historyMax = readCssPx(layoutEl, "--history-max", 480);
  const editorMin = readCssPx(layoutEl, "--editor-min", 280);
  const handleWidth = 5;

  let saved = {};
  try {
    saved = JSON.parse(
      readStorageItem(LAYOUT_STORAGE_KEY, LAYOUT_STORAGE_KEY_LEGACY) || "{}"
    );
  } catch {
    saved = {};
  }
  if (saved.tree) layoutEl.style.setProperty("--col-tree", `${saved.tree}px`);
  if (saved.chat) layoutEl.style.setProperty("--col-chat", `${saved.chat}px`);
  if (saved.history) {
    layoutEl.style.setProperty("--col-history", `${saved.history}px`);
  }

  function persistLayout() {
    const tree = readCssPx(layoutEl, "--col-tree", 240);
    const chat = readCssPx(layoutEl, "--col-chat", 400);
    const history = historyPanelOpen ? readCssPx(layoutEl, "--col-history", 300) : 0;
    saveLayoutWidths(tree, chat, historyPanelOpen ? history : null);
  }

  function maxTreeWidth() {
    const chat = readCssPx(layoutEl, "--col-chat", 400);
    const history = historyPanelWidthPx();
    return clamp(
      layoutEl.clientWidth - chat - history - editorMin - layoutHandleCount() * handleWidth,
      treeMin,
      treeMax
    );
  }

  function maxChatWidth() {
    const tree = readCssPx(layoutEl, "--col-tree", 240);
    const history = historyPanelWidthPx();
    return clamp(
      layoutEl.clientWidth - tree - history - editorMin - layoutHandleCount() * handleWidth,
      chatMin,
      chatMax
    );
  }

  function maxHistoryWidth() {
    const tree = readCssPx(layoutEl, "--col-tree", 240);
    const chat = readCssPx(layoutEl, "--col-chat", 400);
    return clamp(
      layoutEl.clientWidth - tree - chat - editorMin - layoutHandleCount() * handleWidth,
      historyMin,
      historyMax
    );
  }

  function onPointerDown(e, mode) {
    if (e.button !== 0) return;
    e.preventDefault();
    const handle = e.currentTarget;
    handle.classList.add("dragging");
    document.body.classList.add("layout-resizing");

    const startX = e.clientX;
    const startTree = readCssPx(layoutEl, "--col-tree", 240);
    const startChat = readCssPx(layoutEl, "--col-chat", 400);
    const startHistory = readCssPx(layoutEl, "--col-history", 300);

    function onMove(ev) {
      const dx = ev.clientX - startX;
      if (mode === "tree-editor") {
        const next = clamp(startTree + dx, treeMin, maxTreeWidth());
        layoutEl.style.setProperty("--col-tree", `${next}px`);
      } else if (mode === "editor-chat") {
        const next = clamp(startChat - dx, chatMin, maxChatWidth());
        layoutEl.style.setProperty("--col-chat", `${next}px`);
      } else if (mode === "chat-history") {
        const next = clamp(startHistory - dx, historyMin, maxHistoryWidth());
        layoutEl.style.setProperty("--col-history", `${next}px`);
      }
    }

    function onUp() {
      handle.classList.remove("dragging");
      document.body.classList.remove("layout-resizing");
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("pointercancel", onUp);
      persistLayout();
    }

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onUp);
  }

  layoutEl.querySelectorAll(".resize-handle").forEach((handle) => {
    const mode = handle.dataset.resize;
    if (!mode) return;
    handle.addEventListener("pointerdown", (e) => onPointerDown(e, mode));
  });

  window.addEventListener("resize", () => clampLayoutWidths());
}

(async function init() {
  loadOpenTabs();
  initTheme();
  initLayoutResize();
  initAppTooltip();
  initComposerPrefs();
  await loadModelsCatalog();
  await loadSession();
  if (readStorageItem(HISTORY_OPEN_STORAGE_KEY) === "1") {
    setHistoryPanelOpen(true);
  }
  await loadFileTree();
  const first = fileTreeEl.querySelector("li");
  if (first) await openFile(first.dataset.path);
})();
