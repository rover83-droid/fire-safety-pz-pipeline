const stages = [
  "fkp_detected",
  "passport_ready",
  "norms_extracted",
  "matrix_ready",
  "draft_ready",
  "audit_passed",
  "docx_ready",
];

const state = {
  projects: [],
  current: null,
  artifacts: {
    passport: null,
    decisions: null,
    norms: [],
    matrix: [],
    draft: "",
    audit: null,
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", async () => {
  wireTabs();
  wireButtons();
  await loadProjects();
});

function wireTabs() {
  $$(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".tab").forEach((tab) => tab.classList.remove("active"));
      $$(".tab-page").forEach((page) => page.classList.remove("active"));
      button.classList.add("active");
      $("#" + button.dataset.tab).classList.add("active");
    });
  });
}

function wireButtons() {
  $("#loadDemoBtn").addEventListener("click", async () => {
    const response = await apiPost("/api/demo", { name: "demo" });
    await loadProjects(response.name);
    toast("Демо-проект создан");
  });

  $("#createProjectBtn").addEventListener("click", async () => {
    const payload = {
      name: $("#newName").value,
      fkp: $("#newFkp").value,
      section: $("#newSection").value,
      object_name: $("#newObject").value,
      description: "",
    };
    const response = await apiPost("/api/project", payload);
    await loadProjects(response.name);
    toast("Проект создан");
  });

  $("#addConfirmed").addEventListener("click", () => {
    const passport = readJsonEditor("passportEditor");
    passport.confirmed = passport.confirmed || {};
    passport.confirmed["new_parameter"] = "";
    state.artifacts.passport = passport;
    renderPassport();
  });

  $("#addNorm").addEventListener("click", () => {
    state.artifacts.norms.push({
      norm_id: "new-norm",
      document: "СП",
      edition_year: 2020,
      point: "п.",
      quote: "",
      subject: "",
      trigger_parameter: "",
      source_file: "",
      collision_with: null,
    });
    renderNorms();
  });

  $$("[data-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      await saveArtifact(button.dataset.save);
    });
  });

  $$("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      await runAction(button.dataset.action);
    });
  });
}

async function loadProjects(preferred = null) {
  const data = await apiGet("/api/projects");
  state.projects = data.projects;
  renderProjects();
  const target = preferred || state.current?.name || state.projects[0]?.name;
  if (target) {
    await selectProject(target);
  }
}

async function selectProject(name) {
  state.current = await apiGet(`/api/project?project=${encodeURIComponent(name)}`);
  await loadArtifacts();
  renderAll();
}

async function loadArtifacts() {
  if (!state.current) return;
  for (const name of Object.keys(state.artifacts)) {
    try {
      const data = await apiGet(`/api/artifact?project=${encodeURIComponent(state.current.name)}&name=${name}`);
      state.artifacts[name] = data.content ?? defaultArtifact(name);
    } catch {
      state.artifacts[name] = defaultArtifact(name);
    }
  }
}

function renderAll() {
  renderProjects();
  renderHeader();
  renderPassport();
  renderDecisions();
  renderNorms();
  renderMatrix();
  renderDraft();
  renderAudit();
}

function renderProjects() {
  const list = $("#projectList");
  list.innerHTML = "";
  if (!state.projects.length) {
    list.innerHTML = `<div class="project-meta">Пока нет проектов</div>`;
    return;
  }
  state.projects.forEach((project) => {
    const button = document.createElement("button");
    button.className = "project-item" + (state.current?.name === project.name ? " active" : "");
    button.innerHTML = `
      <strong>${escapeHtml(project.object_name)}</strong>
      <div class="project-meta">${escapeHtml(project.name)} · ${escapeHtml(project.fkp)} · ${escapeHtml(project.stage)}</div>
    `;
    button.addEventListener("click", () => selectProject(project.name));
    list.appendChild(button);
  });
}

function renderHeader() {
  const current = state.current;
  $("#currentTitle").textContent = current
    ? `${current.state.object_name} · ${current.state.section}`
    : "Не выбран";
  const activeIndex = stages.indexOf(current?.state.stage);
  $("#stageStrip").innerHTML = stages
    .map((stage, index) => `<span class="stage-pill ${index === activeIndex ? "active" : ""}">${stage}</span>`)
    .join("");
}

function renderPassport() {
  const passport = state.artifacts.passport || defaultArtifact("passport");
  $("#passportEditor").value = stringify(passport);
  const container = $("#confirmedFields");
  container.innerHTML = "";
  Object.entries(passport.confirmed || {}).forEach(([key, value]) => {
    const row = document.createElement("div");
    row.className = "kv-row";
    row.innerHTML = `
      <input value="${escapeAttr(key)}" data-kv-key>
      <input value="${escapeAttr(formatValue(value))}" data-kv-value>
      <button class="small-button" title="Удалить">×</button>
    `;
    row.querySelector("[data-kv-key]").addEventListener("input", syncConfirmedFromFields);
    row.querySelector("[data-kv-value]").addEventListener("input", syncConfirmedFromFields);
    row.querySelector("button").addEventListener("click", () => {
      delete passport.confirmed[key];
      state.artifacts.passport = passport;
      renderPassport();
    });
    container.appendChild(row);
  });
}

function renderDecisions() {
  $("#decisionsEditor").value = stringify(state.artifacts.decisions || defaultArtifact("decisions"));
}

function renderNorms() {
  const container = $("#normRows");
  container.innerHTML = "";
  state.artifacts.norms.forEach((norm, index) => {
    const row = document.createElement("article");
    row.className = "norm-row";
    row.innerHTML = `
      <div class="row-head">
        <strong>${escapeHtml(norm.norm_id || `Норма ${index + 1}`)}</strong>
        <button class="small-button" data-remove>×</button>
      </div>
      <div class="grid-3">
        ${field("norm_id", "ID", norm.norm_id)}
        ${field("document", "Документ", norm.document)}
        ${field("edition_year", "Год", norm.edition_year)}
      </div>
      <div class="grid-3">
        ${field("point", "Пункт", norm.point)}
        ${field("subject", "Предмет", norm.subject)}
        ${field("trigger_parameter", "Триггер", norm.trigger_parameter)}
      </div>
      <div class="grid-2">
        ${field("source_file", "Источник", norm.source_file)}
        ${field("collision_with", "Коллизия", norm.collision_with || "")}
      </div>
      <label class="full">Цитата<textarea data-field="quote">${escapeHtml(norm.quote || "")}</textarea></label>
    `;
    bindRow(row, state.artifacts.norms, index);
    container.appendChild(row);
  });
}

function renderMatrix() {
  const container = $("#matrixRows");
  container.innerHTML = "";
  state.artifacts.matrix.forEach((entry, index) => {
    const row = document.createElement("article");
    row.className = "matrix-row";
    row.innerHTML = `
      <div class="row-head">
        <strong>${escapeHtml(entry.norm_id || `Строка ${index + 1}`)}</strong>
        <button class="small-button" data-remove>×</button>
      </div>
      <div class="grid-2">
        ${field("norm_id", "ID нормы", entry.norm_id)}
        ${field("document_point", "Документ и пункт", entry.document_point)}
      </div>
      <div class="grid-3">
        <label>Статус
          <select data-field="status">
            ${statusOption("применимо", entry.status)}
            ${statusOption("неприменимо", entry.status)}
            ${statusOption("требует инженерной проверки", entry.status)}
          </select>
        </label>
        ${field("numeric_thresholds", "Пороги", entry.numeric_thresholds)}
        ${field("collisions", "Коллизии", entry.collisions)}
      </div>
      <label>Основание<textarea data-field="passport_basis">${escapeHtml(entry.passport_basis || "")}</textarea></label>
      <label>Параметры для текста<textarea data-field="text_parameters">${escapeHtml(entry.text_parameters || "")}</textarea></label>
    `;
    bindRow(row, state.artifacts.matrix, index);
    container.appendChild(row);
  });
}

function renderDraft() {
  $("#draftEditor").value = state.artifacts.draft || "";
}

function renderAudit() {
  const issues = state.current?.issues || [];
  const list = $("#issueList");
  list.innerHTML = "";
  if (!issues.length) {
    list.innerHTML = `<div class="issue"><div class="issue-code">Проверка без замечаний</div></div>`;
  } else {
    issues.forEach((issue) => {
      const item = document.createElement("div");
      item.className = `issue ${issue.severity}`;
      item.innerHTML = `
        <div class="issue-code">${escapeHtml(issue.artifact)} · ${escapeHtml(issue.code)}</div>
        <div class="issue-text">${escapeHtml(issue.message)}</div>
      `;
      list.appendChild(item);
    });
  }
  $("#auditReport").textContent = stringify(state.artifacts.audit || {});
}

function syncConfirmedFromFields() {
  const passport = readJsonEditor("passportEditor");
  passport.confirmed = {};
  $$("#confirmedFields .kv-row").forEach((row) => {
    const key = row.querySelector("[data-kv-key]").value.trim();
    const value = row.querySelector("[data-kv-value]").value.trim();
    if (key) passport.confirmed[key] = parseScalar(value);
  });
  state.artifacts.passport = passport;
  $("#passportEditor").value = stringify(passport);
}

async function saveArtifact(name) {
  requireProject();
  let content;
  if (name === "passport") content = readJsonEditor("passportEditor");
  if (name === "decisions") content = readJsonEditor("decisionsEditor");
  if (name === "norms") content = state.artifacts.norms.map(cleanNorm);
  if (name === "matrix") content = state.artifacts.matrix.map(cleanMatrix);
  if (name === "draft") content = $("#draftEditor").value;
  await apiPost("/api/artifact", { project: state.current.name, name, content });
  await selectProject(state.current.name);
  toast("Сохранено");
}

async function runAction(action) {
  requireProject();
  const response = await apiPost("/api/action", { project: state.current.name, action });
  await selectProject(state.current.name);
  toast(response.result.message);
}

function bindRow(row, collection, index) {
  row.querySelectorAll("[data-field]").forEach((input) => {
    input.addEventListener("input", () => {
      const fieldName = input.dataset.field;
      collection[index][fieldName] = fieldName === "edition_year" ? Number(input.value) || 0 : input.value;
    });
  });
  row.querySelector("[data-remove]").addEventListener("click", () => {
    collection.splice(index, 1);
    renderNorms();
    renderMatrix();
  });
}

function field(name, label, value) {
  return `<label>${escapeHtml(label)}<input data-field="${name}" value="${escapeAttr(formatValue(value))}"></label>`;
}

function statusOption(value, current) {
  return `<option ${value === current ? "selected" : ""}>${value}</option>`;
}

function cleanNorm(norm) {
  return {
    norm_id: norm.norm_id || "",
    document: norm.document || "",
    edition_year: Number(norm.edition_year) || 0,
    point: norm.point || "",
    quote: norm.quote || "",
    subject: norm.subject || "",
    trigger_parameter: norm.trigger_parameter || "",
    source_file: norm.source_file || "",
    collision_with: norm.collision_with || null,
  };
}

function cleanMatrix(entry) {
  return {
    norm_id: entry.norm_id || "",
    document_point: entry.document_point || "",
    status: entry.status || "требует инженерной проверки",
    passport_basis: entry.passport_basis || "",
    numeric_thresholds: entry.numeric_thresholds || "",
    collisions: entry.collisions || "",
    text_parameters: entry.text_parameters || "",
  };
}

function defaultArtifact(name) {
  if (name === "passport") return { object_name: "", description: "", confirmed: {}, clarifying: {}, missing: {} };
  if (name === "decisions") return { standard_editions: [], collisions: [], assumptions: [], system_algorithms: [] };
  if (name === "norms" || name === "matrix") return [];
  if (name === "audit") return {};
  return "";
}

function readJsonEditor(id) {
  try {
    return JSON.parse($("#" + id).value || "{}");
  } catch (error) {
    throw new Error(`Ошибка JSON в поле ${id}: ${error.message}`);
  }
}

function parseScalar(value) {
  if (value === "true") return true;
  if (value === "false") return false;
  if (value !== "" && !Number.isNaN(Number(value))) return Number(value);
  return value;
}

function formatValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

async function apiGet(path) {
  const response = await fetch(path);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Ошибка запроса");
  return data;
}

async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Ошибка запроса");
  return data;
}

function requireProject() {
  if (!state.current) throw new Error("Проект не выбран");
}

function stringify(value) {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

let toastTimer = null;
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("visible"), 2600);
}

window.addEventListener("error", (event) => {
  toast(event.error?.message || event.message);
});

