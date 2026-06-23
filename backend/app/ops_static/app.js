const state = {
  page: pageFromPath(),
  token: localStorage.getItem("ADMIN_TOKEN") || "",
  environment: "staging",
  graph: null,
  prompts: [],
  selectedPrompt: null,
  selectedVersionId: null,
  traces: [],
  selectedTrace: null,
};

const app = document.getElementById("app");
const detail = document.getElementById("detail");

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    setPage(button.dataset.page);
  });
});

render().catch(showError);

function pageFromPath() {
  const path = window.location.pathname;
  if (path.includes("/traces")) return "traces";
  if (path.includes("/prompts")) return "prompts";
  return "agent-flow";
}

function setPage(page) {
  state.page = page;
  const path = page === "agent-flow" ? "/ops/agent-flow" : `/ops/${page}`;
  history.replaceState(null, "", path);
  render().catch(showError);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      authorization: `Bearer ${state.token}`,
      "content-type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(data.detail || text || response.statusText);
  return data;
}

async function render() {
  syncNav();
  document.getElementById("envLabel").textContent = state.environment;
  if (state.page === "agent-flow") return renderAgentFlow();
  if (state.page === "traces") return renderTraces();
  if (state.page === "prompts") return renderPrompts();
}

function syncNav() {
  document.querySelectorAll("nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === state.page);
  });
}

async function renderAgentFlow() {
  state.graph = await api(`/ops/api/agent/graph?environment=${enc(state.environment)}`);
  app.innerHTML = `
    <div class="panel">
      <h2>Agent Flow</h2>
      <p class="muted">点击节点查看职责、prompt scope、active version 和 trace 入口。</p>
    </div>
    <div class="flow">
      ${state.graph.nodes.map(nodeCard).join("")}
    </div>
  `;
  detail.innerHTML = `
    <h2>Graph Manifest</h2>
    <div class="edge-list">
      ${state.graph.edges.map((edge) => `<div>${escapeHtml(edge.source)} → ${escapeHtml(edge.target)} <span class="pill">${escapeHtml(edge.label || "")}</span></div>`).join("")}
    </div>
  `;
  app.querySelectorAll(".node").forEach((node) => {
    node.onclick = () => openNode(node.dataset.id);
  });
}

function nodeCard(node) {
  const prompt = node.active_prompt_version;
  return `
    <div class="node ${escapeAttr(node.type)}" data-id="${escapeAttr(node.id)}">
      <div class="node-title">${escapeHtml(node.label)}</div>
      <div class="node-desc">${escapeHtml(node.description || "")}</div>
      <div class="row-meta" style="margin-top:10px">
        <span class="pill">${escapeHtml(node.type)}</span>
        ${node.prompt_key ? `<span class="pill">${escapeHtml(node.prompt_key)}</span>` : ""}
        ${prompt ? `<span class="pill">v${escapeHtml(prompt.version)}</span>` : ""}
      </div>
    </div>
  `;
}

function openNode(id) {
  const node = state.graph.nodes.find((item) => item.id === id);
  if (!node) return;
  detail.innerHTML = `
    <h2>${escapeHtml(node.label)}</h2>
    <p class="muted">${escapeHtml(node.description || "")}</p>
    <h3>Node</h3>
    <pre>${escapeHtml(json(node))}</pre>
    <div class="actions">
      ${node.prompt_key ? `<button class="primary" id="openPrompt">打开 Prompt Center</button>` : ""}
      <button id="openTraces">打开 Traces</button>
    </div>
  `;
  const openPrompt = document.getElementById("openPrompt");
  if (openPrompt) {
    openPrompt.onclick = async () => {
      state.page = "prompts";
      history.replaceState(null, "", `/ops/prompts?prompt=${enc(node.prompt_key)}`);
      await renderPrompts(node.prompt_key);
    };
  }
  document.getElementById("openTraces").onclick = () => setPage("traces");
}

async function renderTraces(query = "") {
  app.innerHTML = `
    <div class="toolbar">
      <input id="traceQuery" placeholder="agent_run_id / conversation_id" value="${escapeAttr(query)}">
      <button id="traceSearch" class="primary">搜索</button>
      <button id="traceRefresh">刷新</button>
    </div>
    <div class="trace-layout">
      <div class="list" id="traceList"></div>
      <div class="timeline" id="traceTimeline"><p class="muted">选择一个 trace。</p></div>
    </div>
  `;
  document.getElementById("traceSearch").onclick = () => renderTraces(document.getElementById("traceQuery").value.trim());
  document.getElementById("traceRefresh").onclick = () => renderTraces(query);
  const data = await api(`/ops/api/traces?limit=50&query=${enc(query)}`);
  state.traces = data.items || [];
  document.getElementById("traceList").innerHTML = state.traces.map((item) => `
    <button class="row" data-id="${escapeAttr(item.id)}">
      <strong>${escapeHtml(item.graph_name)} · ${escapeHtml(item.status)}</strong>
      <div class="row-meta">
        <span>${escapeHtml(item.id)}</span>
        <span class="pill">${escapeHtml(item.intent || "no-intent")}</span>
      </div>
    </button>
  `).join("") || "<p class='muted'>暂无 trace。</p>";
  document.getElementById("traceList").querySelectorAll(".row").forEach((row) => {
    row.onclick = () => openTrace(row.dataset.id);
  });
  detail.innerHTML = "<h2>Trace Replay</h2><p class='muted'>点击 trace 后，时间线会展示 loop_trace，右侧展示选中 step JSON。</p>";
}

async function openTrace(id) {
  const data = await api(`/ops/api/traces/${enc(id)}`);
  state.selectedTrace = data;
  const steps = traceSteps(data);
  document.getElementById("traceTimeline").innerHTML = steps.map((step, index) => `
    <div class="step ${step.status === "failed" ? "failed" : ""}" data-index="${index}">
      <strong>${escapeHtml(step.label)}</strong>
      <div class="row-meta">
        <span class="pill">${escapeHtml(step.kind)}</span>
        ${step.status ? `<span class="pill">${escapeHtml(step.status)}</span>` : ""}
      </div>
    </div>
  `).join("") || "<p class='muted'>这个 trace 没有 loop_trace。</p>";
  document.getElementById("traceTimeline").querySelectorAll(".step").forEach((step) => {
    step.onclick = () => {
      const item = steps[Number(step.dataset.index)];
      detail.innerHTML = `<h2>${escapeHtml(item.label)}</h2><pre>${escapeHtml(json(item.raw))}</pre>`;
    };
  });
  detail.innerHTML = `
    <h2>Trace ${escapeHtml(id)}</h2>
    <h3>Prompt Versions</h3>
    <pre>${escapeHtml(json(data.prompt_versions || {}))}</pre>
  `;
}

function traceSteps(data) {
  const loop = Array.isArray(data.loop_trace) ? data.loop_trace : [];
  return loop.map((item, index) => {
    const event = item.event || item.name || item.type || `step_${index + 1}`;
    const payload = item.data || item.payload || item;
    return {
      kind: "loop_trace",
      label: `${index + 1}. ${event}`,
      status: payload.status || item.status,
      raw: item,
    };
  });
}

async function renderPrompts(openKey = new URLSearchParams(window.location.search).get("prompt") || "") {
  const data = await api(`/ops/api/prompts?environment=${enc(state.environment)}`);
  state.prompts = data.items || [];
  app.innerHTML = `
    <div class="prompt-layout">
      <div>
        <div class="toolbar" style="grid-template-columns:1fr auto">
          <input id="promptSearch" placeholder="prompt key / scope">
          <button id="promptRefresh">刷新</button>
        </div>
        <div class="list" id="promptList"></div>
      </div>
      <div id="promptEditor"><p class="muted">选择一个 prompt。</p></div>
    </div>
  `;
  document.getElementById("promptRefresh").onclick = () => renderPrompts(openKey);
  document.getElementById("promptSearch").oninput = (event) => fillPromptList(event.target.value);
  fillPromptList("");
  if (openKey) await openPrompt(openKey);
  else detail.innerHTML = "<h2>Prompt Center</h2><p class='muted'>创建 draft，dry-run 通过后才能 publish。</p>";
}

function fillPromptList(filter) {
  const q = String(filter || "").toLowerCase();
  const items = state.prompts.filter((item) => {
    const t = item.template || {};
    return !q || `${t.prompt_key} ${t.scope} ${t.name}`.toLowerCase().includes(q);
  });
  document.getElementById("promptList").innerHTML = items.map((item) => {
    const t = item.template;
    const active = item.active_version;
    return `
      <button class="row" data-key="${escapeAttr(t.prompt_key)}">
        <strong>${escapeHtml(t.prompt_key)}</strong>
        <div class="row-meta">
          <span class="pill">${escapeHtml(t.scope)}</span>
          <span class="pill">active v${escapeHtml(active?.version || "")}</span>
          <span class="pill">${escapeHtml(item.draft_count)} drafts</span>
        </div>
      </button>
    `;
  }).join("") || "<p class='muted'>没有 prompt。</p>";
  document.getElementById("promptList").querySelectorAll(".row").forEach((row) => {
    row.onclick = () => openPrompt(row.dataset.key);
  });
}

async function openPrompt(key) {
  const data = await api(`/ops/api/prompts/${enc(key)}?environment=${enc(state.environment)}`);
  state.selectedPrompt = data;
  const active = data.active_version;
  state.selectedVersionId = active?.id || null;
  document.getElementById("promptEditor").innerHTML = `
    <div class="panel">
      <h2>${escapeHtml(data.template.prompt_key)}</h2>
      <p class="muted">${escapeHtml(data.template.description || "")}</p>
      <textarea id="promptContent">${escapeHtml(active?.content || "")}</textarea>
      <div class="actions">
        <button id="createDraft" class="primary">创建 Draft</button>
        <button id="resetActive">恢复线上内容</button>
      </div>
    </div>
  `;
  document.getElementById("createDraft").onclick = createDraft;
  document.getElementById("resetActive").onclick = () => {
    document.getElementById("promptContent").value = active?.content || "";
  };
  renderPromptDetail(data);
}

function renderPromptDetail(data) {
  detail.innerHTML = `
    <h2>Version Panel</h2>
    <div class="actions">
      <button id="dryRun" class="primary" ${state.selectedVersionId ? "" : "disabled"}>Dry-run</button>
      <button id="publish" ${state.selectedVersionId ? "" : "disabled"}>Publish</button>
      <button id="rollback" class="danger">Rollback</button>
    </div>
    <h3>Assignment</h3>
    <pre>${escapeHtml(json(data.assignment))}</pre>
    <h3>Versions</h3>
    ${data.versions.map((version) => `
      <div class="version">
        <label>
          <input type="radio" name="version" value="${escapeAttr(version.id)}" ${version.id === state.selectedVersionId ? "checked" : ""}>
          <strong>v${escapeHtml(version.version)}</strong>
          <span class="status-${escapeAttr(version.status)}">${escapeHtml(version.status)}</span>
        </label>
        <div class="row-meta"><span>${escapeHtml(version.checksum.slice(0, 12))}</span><span>${escapeHtml(version.created_by)}</span></div>
      </div>
    `).join("")}
    <h3>Last Dry-run</h3>
    <pre>${escapeHtml(json(data.last_dry_run || {}))}</pre>
  `;
  detail.querySelectorAll("input[name='version']").forEach((input) => {
    input.onchange = () => {
      state.selectedVersionId = input.value;
      const version = data.versions.find((item) => item.id === input.value);
      if (version) document.getElementById("promptContent").value = version.content;
    };
  });
  document.getElementById("dryRun").onclick = dryRunSelected;
  document.getElementById("publish").onclick = publishSelected;
  document.getElementById("rollback").onclick = rollbackSelected;
}

async function createDraft() {
  const key = state.selectedPrompt.template.prompt_key;
  const content = document.getElementById("promptContent").value;
  const data = await api(`/ops/api/prompts/${enc(key)}/draft?environment=${enc(state.environment)}`, {
    method: "POST",
    body: JSON.stringify({ content, base_version_id: state.selectedVersionId }),
  });
  state.selectedVersionId = data.item.id;
  await openPrompt(key);
}

async function dryRunSelected() {
  const key = state.selectedPrompt.template.prompt_key;
  const data = await api(`/ops/api/prompts/${enc(key)}/dry-run?environment=${enc(state.environment)}`, {
    method: "POST",
    body: JSON.stringify({ version_id: state.selectedVersionId, suite: "prompt_smoke_v0" }),
  });
  detail.innerHTML = `<h2>Dry-run Result</h2><pre>${escapeHtml(json(data))}</pre><div class="actions"><button id="backPrompt">返回版本面板</button></div>`;
  document.getElementById("backPrompt").onclick = () => openPrompt(key);
}

async function publishSelected() {
  const key = state.selectedPrompt.template.prompt_key;
  const data = await api(`/ops/api/prompts/${enc(key)}/publish?environment=${enc(state.environment)}`, {
    method: "POST",
    body: JSON.stringify({ version_id: state.selectedVersionId, rollout_percent: 100 }),
  });
  await openPrompt(key);
  detail.innerHTML = `<h2>Published</h2><pre>${escapeHtml(json(data))}</pre>`;
}

async function rollbackSelected() {
  const key = state.selectedPrompt.template.prompt_key;
  const data = await api(`/ops/api/prompts/${enc(key)}/rollback?environment=${enc(state.environment)}`, {
    method: "POST",
    body: JSON.stringify({ version_id: state.selectedVersionId }),
  });
  await openPrompt(key);
  detail.innerHTML = `<h2>Rolled Back</h2><pre>${escapeHtml(json(data))}</pre>`;
}

function showError(error) {
  app.innerHTML = `<p class="error">${escapeHtml(error.message || String(error))}</p>`;
}

function enc(value) {
  return encodeURIComponent(value || "");
}

function json(value) {
  return JSON.stringify(value, null, 2);
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
