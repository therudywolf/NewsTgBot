// NewsTgBot admin panel — tab-routed, lazy-loaded, store-driven.
// Each page hooks into the global store on first activation; data is
// fetched once and cached, then refreshed on demand or after mutations.

"use strict";

// ---- Utilities -------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const qs = (sel, root = document) => root.querySelector(sel);
const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const rootPath = (() => {
  const path = window.location.pathname;
  if (!path || path === "/") return "";
  return path.endsWith("/") ? path.slice(0, -1) : path;
})();

function apiUrl(path) {
  return `${rootPath}${path}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.add("visible");
  window.clearTimeout(node._timer);
  node._timer = window.setTimeout(() => node.classList.remove("visible"), 4200);
}

async function api(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

async function withBusy(button, fn) {
  if (!button) return fn();
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "⏳";
  try {
    return await fn();
  } catch (error) {
    toast(`Ошибка: ${error.message}`);
    throw error;
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function debounce(fn, ms = 250) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), ms);
  };
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

// ---- Store -----------------------------------------------------------------

function createStore(initial) {
  const state = { ...initial };
  const subs = new Map();
  return {
    get(key) {
      return state[key];
    },
    set(key, value) {
      state[key] = value;
      (subs.get(key) || []).forEach((fn) => {
        try {
          fn(value);
        } catch (e) {
          console.error("store subscriber failed:", e);
        }
      });
    },
    subscribe(key, fn) {
      if (!subs.has(key)) subs.set(key, new Set());
      subs.get(key).add(fn);
      return () => subs.get(key).delete(fn);
    },
  };
}

const store = createStore({
  auth: null,
  status: null,
  sources: [],
  defaults: null,
  telegramStatus: null,
  telegramChannels: [],
  bots: [],
  prompts: [],
  models: [],
  pipelines: [],
  runs: [],
  news: [],
});

// ---- Router & lazy loading -------------------------------------------------

const pageLoaders = {};
const pageLoaded = new Set();
const DEFAULT_PAGE = "dashboard";

function _resolveTarget() {
  const hash = (window.location.hash || `#${DEFAULT_PAGE}`).replace("#", "");
  const [tab] = hash.split("/");
  const target = tab || DEFAULT_PAGE;
  // Guard against an unknown hash (e.g. someone pasted #foo) — fall back
  // to the default page instead of leaving the user on a blank screen.
  const known = qsa("[data-page]").some((el) => el.dataset.page === target);
  return known ? target : DEFAULT_PAGE;
}

async function navigate() {
  const target = _resolveTarget();
  qsa("[data-page]").forEach((el) => {
    el.hidden = el.dataset.page !== target;
  });
  qsa("[data-tab]").forEach((el) => {
    el.classList.toggle("active", el.dataset.tab === target);
  });

  if (!pageLoaded.has(target) && typeof pageLoaders[target] === "function") {
    pageLoaded.add(target);
    try {
      await pageLoaders[target]();
    } catch (err) {
      console.error(`page ${target} loader failed:`, err);
      toast(`Не удалось загрузить ${target}: ${err.message}`);
    }
  }
}

window.addEventListener("hashchange", () => {
  navigate();
});

function wireTabClicks() {
  // Don't trust hashchange alone — Safari/iOS occasionally swallow it and
  // some setups override window.location.hash. Bind explicit clicks on
  // every tab anchor: prevent default, set hash, call navigate().
  qsa("[data-tab]").forEach((el) => {
    el.addEventListener("click", (event) => {
      event.preventDefault();
      const target = el.dataset.tab;
      if (!target) return;
      if (window.location.hash !== `#${target}`) {
        history.pushState(null, "", `#${target}`);
      }
      navigate();
    });
  });
}

function reloadPage(tab) {
  pageLoaded.delete(tab);
  if (location.hash.replace("#", "").split("/")[0] === tab) {
    navigate();
  }
}

// ---- Auth ------------------------------------------------------------------

function setShellVisibility(isAppVisible) {
  $("app-shell").hidden = !isAppVisible;
  $("auth-shell").style.display = isAppVisible ? "none" : "grid";
}

function renderAuth(statePayload) {
  store.set("auth", statePayload);
  const configured = !!statePayload.configured;
  const authenticated = !!statePayload.authenticated;

  $("setup-card").hidden = configured;
  $("login-card").hidden = !configured || authenticated;
  setShellVisibility(configured && authenticated);

  if (configured && authenticated) {
    $("admin-badge").textContent = statePayload.username || "admin";
    if (!location.hash) {
      location.hash = `#${DEFAULT_PAGE}`;
    } else {
      navigate();
    }
  }
}

async function loadAuthState() {
  const auth = await api("/api/auth/status");
  renderAuth(auth);
}

async function setupAdmin() {
  const username = $("setup-username").value.trim();
  const password = $("setup-password").value;
  if (!username || !password) throw new Error("Заполните логин и пароль");
  await api("/api/setup", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  toast("Администратор создан");
  await loadAuthState();
}

async function login() {
  const username = $("login-username").value.trim();
  const password = $("login-password").value;
  if (!username || !password) throw new Error("Введите логин и пароль");
  await api("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  $("login-password").value = "";
  await loadAuthState();
}

async function logout() {
  await api("/api/auth/logout", { method: "POST", body: "{}" });
  pageLoaded.clear();
  await loadAuthState();
}

// ---- Dashboard -------------------------------------------------------------

function renderMetrics(status) {
  const stats = status?.stats || {};
  const config = status?.config || {};
  const items = [
    ["Каналов", stats.channels_count ?? "—"],
    ["Новостей", stats.news_count ?? "—"],
    ["Тегов", stats.tags_count ?? "—"],
    ["Последняя", fmtDate(stats.latest_date)],
    ["LM Studio", config.lm_studio_model || "—"],
    ["Авто-парсинг", config.auto_parse_enabled ? "вкл" : "выкл"],
  ];
  $("metrics").innerHTML = items
    .map(([label, value]) => `<div class="metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`)
    .join("");
}

async function loadDashboard() {
  const status = await api("/api/status");
  store.set("status", status);
  renderMetrics(status);

  const news = await api("/api/news?days=1&limit=10");
  $("dashboard-news").innerHTML = (news.news || []).length
    ? (news.news || [])
        .map((row) => `<div class="item"><div><div class="item-title">${escapeHtml((row.text || "").slice(0, 120))}…</div><div class="item-meta">${escapeHtml(fmtDate(row.date))} · ${escapeHtml(row.title || row.username || "—")}</div></div></div>`)
        .join("")
    : `<div class="notice">Новостей за сутки нет.</div>`;

  // Runs panel — placeholder until pipeline runs ship
  $("dashboard-runs").innerHTML = `<div class="notice">Пайплайны и запуски — на вкладке «Пайплайны».</div>`;
}

pageLoaders.dashboard = loadDashboard;

// ---- Sources ---------------------------------------------------------------

const sourcesView = {
  filter: "",
  group: "all",
  sortKey: "title",
  sortDir: 1,
  selected: new Set(),
};

function sourceTitle(source) {
  return source.title || source.username || `#${source.channel_id}`;
}

function applySourceFilters(rows) {
  const text = sourcesView.filter.trim().toLowerCase();
  let filtered = rows;
  if (sourcesView.group !== "all") {
    filtered = filtered.filter((r) => r.source_type === sourcesView.group);
  }
  if (text) {
    filtered = filtered.filter((r) =>
      (sourceTitle(r) + " " + (r.username || "") + " " + (r.source_type || ""))
        .toLowerCase()
        .includes(text),
    );
  }
  const dir = sourcesView.sortDir;
  filtered.sort((a, b) => {
    const k = sourcesView.sortKey;
    const av = k === "total" ? (a.stats?.total || 0)
            : k === "week" ? (a.stats?.week_count || 0)
            : k === "latest" ? (a.stats?.latest_date || "")
            : (a[k] || sourceTitle(a)).toString().toLowerCase();
    const bv = k === "total" ? (b.stats?.total || 0)
            : k === "week" ? (b.stats?.week_count || 0)
            : k === "latest" ? (b.stats?.latest_date || "")
            : (b[k] || sourceTitle(b)).toString().toLowerCase();
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
  return filtered;
}

function renderSourcesGroups(rows) {
  const groups = new Map();
  groups.set("all", rows.length);
  rows.forEach((r) => {
    const k = r.source_type || "other";
    groups.set(k, (groups.get(k) || 0) + 1);
  });
  const labels = { all: "Все", rss: "RSS", telethon: "Telegram (user)", telegram_bot: "Bot API", web: "Web" };
  $("sources-groups").innerHTML = Array.from(groups.entries())
    .map(([key, count]) => `
      <div class="item group-item ${key === sourcesView.group ? "active" : ""}" data-source-group="${escapeHtml(key)}">
        <span>${escapeHtml(labels[key] || key)}</span>
        <span class="tag">${count}</span>
      </div>
    `)
    .join("");
}

function renderSourcesTable(rows) {
  const filtered = applySourceFilters(rows);
  $("sources-count").textContent = `Показано: ${filtered.length} / ${rows.length}`;
  if (!filtered.length) {
    $("sources-tbody").innerHTML = `<tr><td colspan="7"><div class="notice">Ничего не найдено.</div></td></tr>`;
    return;
  }
  $("sources-tbody").innerHTML = filtered
    .map((r) => {
      const stats = r.stats || {};
      const checked = sourcesView.selected.has(r.channel_id) ? "checked" : "";
      return `
        <tr>
          <td><input type="checkbox" data-source-check="${r.channel_id}" ${checked} /></td>
          <td>
            <div class="item-title">${escapeHtml(sourceTitle(r))}</div>
            <div class="item-meta">${escapeHtml(r.username || "")}</div>
          </td>
          <td><span class="tag">${escapeHtml(r.source_type || "—")}</span></td>
          <td class="num">${stats.total ?? 0}</td>
          <td class="num">${stats.week_count ?? 0}</td>
          <td>${escapeHtml(fmtDate(stats.latest_date))}</td>
          <td class="row-actions">
            <button type="button" data-source-parse="${r.channel_id}">Парсить</button>
            <button type="button" data-source-remove="${r.channel_id}" class="danger">Удалить</button>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderSources() {
  const rows = store.get("sources") || [];
  renderSourcesGroups(rows);
  renderSourcesTable(rows);
}

async function loadSources() {
  const data = await api("/api/sources");
  store.set("sources", data.sources || []);
  renderSources();
}

async function loadDefaults() {
  if (store.get("defaults")) return;
  const data = await api("/api/default-sources");
  store.set("defaults", data);
  const categories = data.categories || {};
  const rows = [];
  Object.entries(categories).forEach(([categoryId, category]) => {
    rows.push(`<div class="item subhead"><b>${escapeHtml(category.name || categoryId)}</b><span class="tag">${(category.sources || []).length}</span></div>`);
    (category.sources || []).forEach((source) => {
      rows.push(`
        <div class="item">
          <span>
            <div class="item-title">${escapeHtml(source.title)}</div>
            <div class="item-meta">${escapeHtml(source.source_config?.rss_url || source.username)}</div>
          </span>
          <button type="button" data-default-source="${escapeHtml(categoryId)}::${escapeHtml(source.username)}">+ Добавить</button>
        </div>
      `);
    });
  });
  $("default-sources").innerHTML = rows.join("");
}

async function addDefaultSource(categoryId, username) {
  const category = store.get("defaults")?.categories?.[categoryId];
  const source = (category?.sources || []).find((item) => item.username === username);
  if (!source) throw new Error("Источник не найден");
  await api("/api/sources/default", {
    method: "POST",
    body: JSON.stringify(source),
  });
  toast(`Добавлен: ${source.title}`);
  await loadSources();
}

async function addManualSource() {
  const value = $("manual-source").value.trim();
  if (!value) throw new Error("Укажите источник");
  await api("/api/sources/manual", {
    method: "POST",
    body: JSON.stringify({
      value,
      title: $("manual-title").value.trim() || undefined,
      source_type: $("manual-type").value,
    }),
  });
  $("manual-source").value = "";
  $("manual-title").value = "";
  toast("Источник добавлен");
  await loadSources();
}

async function parseSource(channelId) {
  const data = await api(`/api/sources/${channelId}/parse?limit=200&days=7`, {
    method: "POST",
    body: "{}",
  });
  toast(`Parsed ${data.stats.parsed}, skipped ${data.stats.skipped}, errors ${data.stats.errors}`);
  await loadSources();
}

async function removeSource(channelId) {
  if (!window.confirm("Удалить источник?")) return;
  await api(`/api/sources/${channelId}`, { method: "DELETE" });
  sourcesView.selected.delete(Number(channelId));
  toast("Источник удалён");
  await loadSources();
}

async function bulkParseSources() {
  const ids = Array.from(sourcesView.selected);
  if (!ids.length) throw new Error("Выберите источники");
  let parsed = 0;
  for (const id of ids) {
    try {
      const data = await api(`/api/sources/${id}/parse?limit=200&days=7`, { method: "POST", body: "{}" });
      parsed += data.stats?.parsed || 0;
    } catch (e) {
      console.error(e);
    }
  }
  toast(`Парсинг завершён, новых: ${parsed}`);
  await loadSources();
}

async function bulkDeleteSources() {
  const ids = Array.from(sourcesView.selected);
  if (!ids.length) throw new Error("Выберите источники");
  if (!window.confirm(`Удалить ${ids.length} источников?`)) return;
  for (const id of ids) {
    try {
      await api(`/api/sources/${id}`, { method: "DELETE" });
    } catch (e) {
      console.error(e);
    }
  }
  sourcesView.selected.clear();
  toast(`Удалено: ${ids.length}`);
  await loadSources();
}

async function parseAll() {
  const data = await api("/api/sources/parse-all?limit=100&days=3", { method: "POST", body: "{}" });
  toast(`Parsed ${data.totals.parsed}, skipped ${data.totals.skipped}, errors ${data.totals.errors}`);
  await loadSources();
}

pageLoaders.sources = async () => {
  await loadSources();
  await loadDefaults();
};

// ---- Telegram account ------------------------------------------------------

async function refreshTelegramStatus() {
  const data = await api("/api/telegram/status");
  store.set("telegramStatus", data);
  if (!data.configured) {
    $("tg-status").textContent = "Telethon API ID/hash пока не настроены — заполни на вкладке «Настройки».";
    return;
  }
  const user = data.user ? `${data.user.first_name || ""} ${data.user.username ? `@${data.user.username}` : ""}`.trim() : "";
  $("tg-status").textContent = `configured: ${data.configured} · connected: ${data.connected} · authorized: ${data.authorized}${user ? ` · user: ${user}` : ""}`;
}

async function sendTelegramCode() {
  const phone = $("tg-phone").value.trim();
  if (!phone) throw new Error("Укажите телефон");
  await api("/api/telegram/send-code", { method: "POST", body: JSON.stringify({ phone }) });
  toast("Код отправлен");
  $("tg-code").focus();
}

async function signInTelegram() {
  const payload = {
    phone: $("tg-phone").value.trim(),
    code: $("tg-code").value.trim(),
    password: $("tg-password").value,
  };
  const data = await api("/api/telegram/sign-in", { method: "POST", body: JSON.stringify(payload) });
  toast(data.password_required ? "Нужен 2FA password" : `authorized: ${data.authorized}`);
  await refreshTelegramStatus();
}

const tgChannelsView = { filter: "" };

function renderTelegramChannels() {
  const channels = store.get("telegramChannels") || [];
  const text = tgChannelsView.filter.toLowerCase().trim();
  const filtered = text
    ? channels.filter((c) => (c.title + " " + (c.username || "")).toLowerCase().includes(text))
    : channels;

  if (!channels.length) {
    $("tg-channels").innerHTML = `<div class="notice">Нажми «Подгрузить», чтобы получить список диалогов.</div>`;
    return;
  }
  if (!filtered.length) {
    $("tg-channels").innerHTML = `<div class="notice">Ничего не найдено.</div>`;
    return;
  }
  $("tg-channels").innerHTML = filtered
    .map((channel, displayIdx) => {
      const idx = channels.indexOf(channel);
      return `
        <label class="item">
          <input type="checkbox" data-tg-channel="${idx}" />
          <span>
            <span class="item-title">${escapeHtml(channel.title)}</span>
            <span class="item-meta">${escapeHtml(channel.username ? `@${channel.username}` : channel.id)}</span>
          </span>
          <span class="tag">${channel.broadcast ? "channel" : "group"}</span>
        </label>
      `;
    })
    .join("");
}

async function loadTelegramChannels() {
  const data = await api("/api/telegram/channels");
  store.set("telegramChannels", data.channels || []);
  renderTelegramChannels();
  toast(`Каналов найдено: ${(data.channels || []).length}`);
}

async function addSelectedTelegramChannels() {
  const checked = qsa("[data-tg-channel]:checked");
  const channels = store.get("telegramChannels");
  const picked = checked.map((node) => channels[Number(node.dataset.tgChannel)]);
  if (!picked.length) throw new Error("Выберите каналы");
  await api("/api/telegram/channels", { method: "POST", body: JSON.stringify({ channels: picked }) });
  toast(`Добавлено: ${picked.length}`);
  pageLoaded.delete("sources");
  await refreshTelegramStatus();
}

pageLoaders.account = async () => {
  await refreshTelegramStatus();
  renderTelegramChannels();
};

// ---- Bots ------------------------------------------------------------------

function renderBots() {
  const bots = store.get("bots") || [];
  const postSelect = $("post-bot");
  postSelect.innerHTML = bots.length
    ? bots.map((b) => `<option value="${b.id}">${escapeHtml(b.label)} (${escapeHtml(b.kind)}${b.enabled ? "" : ", off"})</option>`).join("")
    : `<option value="">— нет ботов —</option>`;

  if (!bots.length) {
    $("bots-list").innerHTML = `<div class="notice">Ботов пока нет.</div>`;
    return;
  }
  $("bots-list").innerHTML = bots
    .map((bot) => `
      <article class="card">
        <header class="card-head">
          <div>
            <div class="item-title">${escapeHtml(bot.label)}</div>
            <div class="item-meta">${escapeHtml(bot.kind)} · ${bot.enabled ? "включён" : "выключен"}</div>
          </div>
          <span class="tag ${bot.enabled ? "loaded" : ""}">${bot.kind}</span>
        </header>
        <div class="card-body">
          <div class="item-meta">chat: ${escapeHtml(bot.default_chat_id || "—")}</div>
          <div class="item-meta">token: ${escapeHtml(bot.token_masked || "—")}</div>
        </div>
        <footer class="card-actions">
          <button type="button" data-bot-toggle="${bot.id}">${bot.enabled ? "Выкл" : "Вкл"}</button>
          <button type="button" data-bot-edit-token="${bot.id}">Токен</button>
          <button type="button" data-bot-edit-chat="${bot.id}">Чат</button>
          <button type="button" data-bot-edit-label="${bot.id}">Имя</button>
          <button type="button" data-bot-remove="${bot.id}" class="danger">Удалить</button>
        </footer>
      </article>
    `)
    .join("");
}

async function loadBots() {
  const data = await api("/api/posting/bots");
  store.set("bots", data.bots || []);
  renderBots();
}

async function addBot() {
  const label = $("new-bot-label").value.trim();
  if (!label) throw new Error("Укажите название");
  const payload = {
    label,
    kind: $("new-bot-kind").value,
    token: $("new-bot-token").value.trim() || undefined,
    default_chat_id: $("new-bot-chat").value.trim() || undefined,
  };
  await api("/api/posting/bots", { method: "POST", body: JSON.stringify(payload) });
  $("new-bot-label").value = "";
  $("new-bot-token").value = "";
  $("new-bot-chat").value = "";
  toast("Бот добавлен");
  await loadBots();
}

async function toggleBot(id) {
  const bot = (store.get("bots") || []).find((b) => String(b.id) === String(id));
  if (!bot) return;
  await api(`/api/posting/bots/${id}`, { method: "PATCH", body: JSON.stringify({ enabled: !bot.enabled }) });
  await loadBots();
}

async function patchBotField(id, field) {
  const bot = (store.get("bots") || []).find((b) => String(b.id) === String(id));
  if (!bot) return;
  const labels = { token: "Новый токен:", default_chat_id: "Default chat:", label: "Название:" };
  const initial = field === "token" ? "" : bot[field] || "";
  const value = window.prompt(labels[field], initial);
  if (value === null) return;
  await api(`/api/posting/bots/${id}`, { method: "PATCH", body: JSON.stringify({ [field]: value }) });
  toast("Сохранено");
  await loadBots();
}

async function removeBot(id) {
  if (!window.confirm("Удалить бота?")) return;
  await api(`/api/posting/bots/${id}`, { method: "DELETE" });
  toast("Удалён");
  await loadBots();
}

pageLoaders.bots = loadBots;

// ---- Prompts ---------------------------------------------------------------

let promptsViewTask = "repost";

function renderPrompts() {
  const all = store.get("prompts") || [];
  const filtered = all.filter((p) => p.task === promptsViewTask);
  qsa("[data-prompt-task]").forEach((el) => el.classList.toggle("active", el.dataset.promptTask === promptsViewTask));
  if (!filtered.length) {
    $("prompts-list").innerHTML = `<div class="notice">Промптов для задачи «${escapeHtml(promptsViewTask)}» нет.</div>`;
    return;
  }
  $("prompts-list").innerHTML = filtered
    .map((p) => `
      <div class="item prompt-item">
        <div>
          <div class="item-title">
            ${escapeHtml(p.name)}
            ${p.is_active ? '<span class="tag loaded">active</span>' : ""}
          </div>
          <div class="item-meta">${escapeHtml((p.system_prompt || "").slice(0, 200))}…</div>
        </div>
        <div class="item-actions">
          ${p.is_active ? "" : `<button type="button" data-prompt-activate="${p.id}">Активировать</button>`}
          <button type="button" data-prompt-edit="${p.id}">Редактировать</button>
          <button type="button" data-prompt-remove="${p.id}" class="danger">×</button>
        </div>
      </div>
    `)
    .join("");
}

async function loadPrompts() {
  const data = await api("/api/prompts");
  store.set("prompts", data.prompts || []);
  renderPrompts();
}

async function savePrompt() {
  const payload = {
    task: $("new-prompt-task").value,
    name: $("new-prompt-name").value.trim() || "default",
    system_prompt: $("new-prompt-system").value,
    user_template: $("new-prompt-user").value,
    is_active: $("new-prompt-active").checked,
  };
  if (!payload.system_prompt.trim() || !payload.user_template.trim()) {
    throw new Error("Заполни system и user-шаблон");
  }
  await api("/api/prompts", { method: "POST", body: JSON.stringify(payload) });
  toast("Промпт сохранён");
  promptsViewTask = payload.task;
  await loadPrompts();
}

function editPromptInline(id) {
  const p = (store.get("prompts") || []).find((x) => String(x.id) === String(id));
  if (!p) return;
  $("new-prompt-task").value = p.task;
  $("new-prompt-name").value = p.name;
  $("new-prompt-system").value = p.system_prompt;
  $("new-prompt-user").value = p.user_template;
  $("new-prompt-active").checked = !!p.is_active;
  toast(`Редактируешь: ${p.task}/${p.name}`);
  $("new-prompt-system").scrollIntoView({ behavior: "smooth" });
}

function clearPromptForm() {
  $("new-prompt-name").value = "";
  $("new-prompt-system").value = "";
  $("new-prompt-user").value = "";
  $("new-prompt-sample").value = "";
  $("new-prompt-active").checked = false;
  $("prompt-test-output").hidden = true;
}

async function testPromptDraft() {
  const payload = {
    system_prompt: $("new-prompt-system").value,
    user_template: $("new-prompt-user").value,
    sample_news: $("new-prompt-sample").value.trim() || undefined,
  };
  if (!payload.system_prompt.trim() || !payload.user_template.trim()) {
    throw new Error("Заполни system и user-шаблон");
  }
  const out = $("prompt-test-output");
  out.textContent = "⏳ Запрашиваю LLM…";
  out.hidden = false;
  const data = await api("/api/prompts/test", { method: "POST", body: JSON.stringify(payload) });
  out.textContent = `--- Ответ LLM ---\n${data.text}\n\n--- Использованные данные ---\n${data.sample_used}`;
}

async function activatePrompt(id) {
  await api(`/api/prompts/${id}/activate`, { method: "POST", body: "{}" });
  toast("Активирован");
  await loadPrompts();
}

async function removePrompt(id) {
  if (!window.confirm("Удалить промпт?")) return;
  await api(`/api/prompts/${id}`, { method: "DELETE" });
  toast("Удалён");
  await loadPrompts();
}

pageLoaders.prompts = loadPrompts;

// ---- Pipelines -------------------------------------------------------------

const STEP_TYPES = ["parse_sources", "filter", "dedup", "summary", "compose_post", "publish", "wait"];
let editorState = { pipelineId: null, steps: [] };

function statusTagClass(status) {
  if (status === "success") return "loaded";
  if (status === "failed") return "danger";
  return "";
}

function renderPipelines() {
  const items = store.get("pipelines") || [];
  if (!items.length) {
    $("pipelines-list").innerHTML = `<div class="notice">Пайплайнов пока нет — нажми «Создать пайплайн».</div>`;
    return;
  }
  $("pipelines-list").innerHTML = items
    .map((p) => {
      const recent = (p.recent_runs || [])
        .map((r) => `<span class="tag ${statusTagClass(r.status)}">${escapeHtml(r.status)}</span>`)
        .join(" ");
      return `
        <article class="card">
          <header class="card-head">
            <div>
              <div class="item-title">${escapeHtml(p.name)}</div>
              <div class="item-meta">${escapeHtml(p.group_name)} · ${p.steps.length} шагов · ${p.enabled ? "enabled" : "disabled"}${p.schedule_cron ? ` · cron ${escapeHtml(p.schedule_cron)}` : ""}</div>
            </div>
            <div class="card-actions">
              <button type="button" data-pipeline-run="${p.id}">▶ Запустить</button>
              <button type="button" data-pipeline-edit="${p.id}">Изменить</button>
              <button type="button" data-pipeline-remove="${p.id}" class="danger">×</button>
            </div>
          </header>
          <div class="card-body">
            <div class="item-meta">Шаги: ${p.steps.map((s) => escapeHtml(s.type)).join(" → ") || "—"}</div>
            <div>${recent || `<span class="item-meta">Без запусков</span>`}</div>
          </div>
        </article>
      `;
    })
    .join("");
}

async function loadPipelines() {
  const data = await api("/api/pipelines");
  store.set("pipelines", data.pipelines || []);
  renderPipelines();
}

async function createPipelineFromTemplate() {
  const data = await api("/api/pipeline-templates");
  const options = (data.templates || []).map((t, i) => `${i + 1}. ${t.id} — ${t.name} (${t.step_count} шагов)`).join("\n");
  const choice = window.prompt(`Выбери шаблон по номеру или id:\n\n${options}\n\nНомер или id:`);
  if (!choice) return;
  const trimmed = choice.trim();
  let templateId = trimmed;
  const asNumber = Number(trimmed);
  if (!Number.isNaN(asNumber) && (data.templates || [])[asNumber - 1]) {
    templateId = data.templates[asNumber - 1].id;
  }
  const name = window.prompt("Название нового пайплайна:", "");
  const created = await api("/api/pipelines/from-template", {
    method: "POST",
    body: JSON.stringify({ template: templateId, name: name || undefined }),
  });
  toast(`Создан: ${created.name}`);
  await loadPipelines();
  openPipelineEditor(created);
}

function renderStepEditor() {
  const container = $("pipeline-steps");
  if (!editorState.steps.length) {
    container.innerHTML = `<div class="notice">Нет шагов. Добавь хотя бы один — например, «parse_sources».</div>`;
    return;
  }
  container.innerHTML = editorState.steps
    .map((step, idx) => `
      <div class="item step-item">
        <div>
          <div class="item-title">#${idx + 1} · ${escapeHtml(step.type)}</div>
          <textarea data-step-params="${idx}" rows="3">${escapeHtml(JSON.stringify(step.params || {}, null, 2))}</textarea>
        </div>
        <div class="item-actions">
          <button type="button" data-step-up="${idx}" ${idx === 0 ? "disabled" : ""}>↑</button>
          <button type="button" data-step-down="${idx}" ${idx === editorState.steps.length - 1 ? "disabled" : ""}>↓</button>
          <button type="button" data-step-remove="${idx}" class="danger">×</button>
        </div>
      </div>
    `)
    .join("");
}

function openPipelineEditor(pipeline) {
  editorState = pipeline
    ? {
        pipelineId: pipeline.id,
        steps: (pipeline.steps || []).map((s) => ({ type: s.type, params: s.params || {} })),
      }
    : { pipelineId: null, steps: [] };

  $("pipeline-editor-title").textContent = pipeline ? `Редактирование: ${pipeline.name}` : "Новый пайплайн";
  $("pipeline-name").value = pipeline?.name || "";
  $("pipeline-group").value = pipeline?.group_name || "default";
  $("pipeline-enabled").checked = pipeline ? !!pipeline.enabled : true;
  $("pipeline-cron").value = pipeline?.schedule_cron || "";
  renderStepEditor();
  $("pipeline-editor").hidden = false;
  $("pipeline-editor").scrollIntoView({ behavior: "smooth" });
}

function closePipelineEditor() {
  $("pipeline-editor").hidden = true;
}

function addPipelineStep() {
  const type = window.prompt(`Тип шага (${STEP_TYPES.join(", ")}):`, "parse_sources");
  if (!type) return;
  if (!STEP_TYPES.includes(type)) {
    toast(`Неизвестный тип шага: ${type}`);
    return;
  }
  const defaults = {
    parse_sources: { days: 1, limit: 200, source_group: "all" },
    filter: { keywords_include: [], keywords_exclude: [], min_text_length: 0 },
    dedup: {},
    summary: { period_label: "сутки" },
    compose_post: { prompt_name: "default", include_image: false, instruction: "" },
    publish: { bot_id: 0, chat_id: "", parse_mode: "", include_image: false },
    wait: { seconds: 30 },
  };
  editorState.steps.push({ type, params: defaults[type] || {} });
  renderStepEditor();
}

function readStepsFromEditor() {
  const steps = editorState.steps.map((step, idx) => {
    const textarea = qs(`[data-step-params="${idx}"]`);
    let params = step.params || {};
    if (textarea) {
      try {
        params = JSON.parse(textarea.value || "{}");
      } catch (e) {
        throw new Error(`Шаг #${idx + 1} (${step.type}): некорректный JSON параметров`);
      }
    }
    return { type: step.type, params };
  });
  return steps;
}

async function savePipeline() {
  const name = $("pipeline-name").value.trim();
  if (!name) throw new Error("Укажите название пайплайна");
  const steps = readStepsFromEditor();
  if (!steps.length) throw new Error("Добавьте хотя бы один шаг");
  const payload = {
    name,
    group_name: $("pipeline-group").value.trim() || "default",
    enabled: $("pipeline-enabled").checked,
    schedule_cron: $("pipeline-cron").value.trim() || null,
    steps,
  };
  const method = editorState.pipelineId ? "PUT" : "POST";
  const url = editorState.pipelineId ? `/api/pipelines/${editorState.pipelineId}` : "/api/pipelines";
  const result = await api(url, { method, body: JSON.stringify(payload) });
  editorState.pipelineId = result.id;
  toast("Пайплайн сохранён");
  await loadPipelines();
}

async function runPipelineNow(pipelineId) {
  const id = pipelineId ?? editorState.pipelineId;
  if (!id) throw new Error("Сначала сохраните пайплайн");
  const data = await api(`/api/pipelines/${id}/run`, { method: "POST", body: "{}" });
  toast(`Run #${data.run_id}: ${data.status}${data.error ? " · " + data.error : ""}`);
  await loadPipelines();
  pageLoaded.delete("runs");
}

async function editPipeline(pipelineId) {
  const pipeline = (store.get("pipelines") || []).find((p) => String(p.id) === String(pipelineId));
  if (!pipeline) {
    const fresh = await api(`/api/pipelines/${pipelineId}`);
    openPipelineEditor(fresh);
  } else {
    openPipelineEditor(pipeline);
  }
}

async function removePipeline(pipelineId) {
  if (!window.confirm("Удалить пайплайн?")) return;
  await api(`/api/pipelines/${pipelineId}`, { method: "DELETE" });
  toast("Удалён");
  if (String(editorState.pipelineId) === String(pipelineId)) closePipelineEditor();
  await loadPipelines();
}

pageLoaders.pipelines = loadPipelines;

// ---- Runs -----------------------------------------------------------------

function renderRunsList() {
  const runs = store.get("runs") || [];
  if (!runs.length) {
    $("runs-list").innerHTML = `<div class="notice">Запусков пока нет.</div>`;
    return;
  }
  $("runs-list").innerHTML = runs
    .map((r) => {
      const duration = r.finished_at && r.started_at
        ? Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 1000)
        : null;
      return `
        <div class="item">
          <div>
            <div class="item-title">
              #${r.id} · ${escapeHtml(r.pipeline_name || "")}
              <span class="tag ${statusTagClass(r.status)}">${escapeHtml(r.status)}</span>
            </div>
            <div class="item-meta">${escapeHtml(fmtDate(r.started_at))}${duration !== null ? ` · ${duration}с` : ""} · ${escapeHtml(r.trigger || "manual")}${r.error ? ` · ${escapeHtml(r.error)}` : ""}</div>
          </div>
          <div class="item-actions">
            <button type="button" data-run-open="${r.id}">Детали</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function populateRunsFilter() {
  const select = $("runs-filter");
  const current = select.value;
  const pipelines = store.get("pipelines") || [];
  select.innerHTML = `<option value="">Все пайплайны</option>` + pipelines.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  if (current) select.value = current;
}

async function loadRuns() {
  if (!(store.get("pipelines") || []).length) {
    try {
      const data = await api("/api/pipelines");
      store.set("pipelines", data.pipelines || []);
    } catch {
      /* ignore */
    }
  }
  populateRunsFilter();
  const filter = $("runs-filter").value;
  const data = await api(`/api/runs${filter ? `?pipeline_id=${filter}&limit=100` : "?limit=100"}`);
  store.set("runs", data.runs || []);
  renderRunsList();
}

async function openRunDetail(runId) {
  const detail = await api(`/api/runs/${runId}`);
  $("run-detail-title").textContent = `Запуск #${detail.id} · ${detail.pipeline_name || ""}`;
  const stepsHtml = (detail.steps || [])
    .map((s) => {
      const dur = s.finished_at && s.started_at ? Math.round((new Date(s.finished_at) - new Date(s.started_at)) / 1000) : "?";
      return `
        <details class="step-detail">
          <summary>
            #${s.position + 1} · ${escapeHtml(s.type)} ·
            <span class="tag ${statusTagClass(s.status)}">${escapeHtml(s.status)}</span>
            · ${dur}с
            ${s.error ? `· <span class="danger">${escapeHtml(s.error)}</span>` : ""}
          </summary>
          <pre class="summary">input: ${escapeHtml(JSON.stringify(s.input || {}, null, 2))}
output: ${escapeHtml(JSON.stringify(s.output || {}, null, 2))}</pre>
        </details>
      `;
    })
    .join("");
  $("run-detail-body").innerHTML = `
    <div class="item-meta">Старт: ${escapeHtml(fmtDate(detail.started_at))} · Финиш: ${escapeHtml(fmtDate(detail.finished_at))}</div>
    <div class="item-meta">Триггер: ${escapeHtml(detail.trigger || "manual")}</div>
    ${detail.error ? `<div class="notice danger">${escapeHtml(detail.error)}</div>` : ""}
    <pre class="summary">${escapeHtml(JSON.stringify(detail.output || {}, null, 2))}</pre>
    ${stepsHtml || `<div class="notice">Без шагов.</div>`}
  `;
  $("run-detail").hidden = false;
  $("run-detail").scrollIntoView({ behavior: "smooth" });
}

pageLoaders.runs = loadRuns;

// ---- News page -------------------------------------------------------------

function renderNews(rows, mediaMap = {}) {
  $("news-list").innerHTML = rows.length
    ? rows
        .map((row) => {
          const media = mediaMap[row.id] || [];
          const thumb = media.find((m) => m.kind === "image" && m.url);
          const thumbHtml = thumb
            ? `<img class="news-thumb" loading="lazy" src="${escapeHtml(thumb.url)}" alt="" />`
            : "";
          const badge = media.length ? `<span class="tag">🖼 ${media.length}</span>` : "";
          return `
            <article class="news-card">
              <div class="news-meta">${escapeHtml(fmtDate(row.date))} · ${escapeHtml(row.title || row.username || row.channel_id)} ${badge}</div>
              <div class="news-body">
                ${thumbHtml}
                <div class="news-text">${escapeHtml(row.text)}</div>
              </div>
            </article>
          `;
        })
        .join("")
    : `<div class="notice">Новостей нет.</div>`;
}

async function loadNews() {
  const days = Number($("news-days").value || 1);
  const data = await api(`/api/news?days=${days}&limit=200`);
  const rows = data.news || [];
  store.set("news", rows);

  // Pull media for the visible window in parallel; ignore failures so the
  // page still renders if some news has no media.
  const mediaMap = {};
  await Promise.allSettled(
    rows.slice(0, 30).map(async (row) => {
      try {
        const r = await api(`/api/news/${row.id}/media`);
        if (r.media && r.media.length) mediaMap[row.id] = r.media;
      } catch {
        /* ignore */
      }
    }),
  );
  renderNews(rows, mediaMap);
}

async function summarizeNews() {
  const days = Number($("news-days").value || 1);
  const data = await api("/api/news/summary", { method: "POST", body: JSON.stringify({ days }) });
  $("summary-box").textContent = `Новостей: ${data.input_count}, после дедупа: ${data.unique_count}\n\n${data.summary}`;
}

async function previewPost() {
  const payload = {
    days: Number($("news-days").value || 1),
    instruction: $("post-instruction").value.trim() || undefined,
    prompt_name: $("post-style").value.trim() || undefined,
  };
  const data = await api("/api/posting/preview", { method: "POST", body: JSON.stringify(payload) });
  $("post-text").value = data.text || "";
  $("post-status").textContent = `Новостей: ${data.input_count}, после дедупа: ${data.unique_count}.`;
}

async function sendPost() {
  const botId = Number($("post-bot").value);
  if (!botId) throw new Error("Выбери бота");
  const text = $("post-text").value.trim();
  if (!text) throw new Error("Текст поста пуст");
  const payload = {
    bot_id: botId,
    text,
    chat_id: $("post-chat").value.trim() || undefined,
    parse_mode: $("post-parse-mode").value || undefined,
    disable_web_page_preview: true,
  };
  const data = await api("/api/posting/send", { method: "POST", body: JSON.stringify(payload) });
  $("post-status").textContent = `Отправлено в ${data.chat_id} (бот #${data.bot_id}).`;
  toast("Опубликовано");
}

pageLoaders.news = async () => {
  await loadBots();
  await loadNews();
};

// ---- Settings --------------------------------------------------------------

function modelLabel(m) {
  return m.display_name || m.key || m.id || "unknown";
}
function modelKey(m) {
  return m.key || m.id || m.display_name;
}

function populateModelSelect() {
  const select = $("lm-model");
  const llms = (store.get("models") || []).filter((m) => (m.type || "llm") === "llm");
  if (!llms.length) {
    select.innerHTML = `<option value="">— нет моделей —</option>`;
    return;
  }
  const current = select.value;
  select.innerHTML = llms
    .map((m) => {
      const key = modelKey(m);
      const loaded = Array.isArray(m.loaded_instances) && m.loaded_instances.length > 0;
      const meta = [m.params_string, m.quantization?.name].filter(Boolean).join(" ");
      const suffix = [loaded ? "loaded" : "", meta].filter(Boolean).join(" · ");
      return `<option value="${escapeHtml(key)}">${escapeHtml(modelLabel(m))}${suffix ? ` — ${escapeHtml(suffix)}` : ""}</option>`;
    })
    .join("");
  if (current && llms.some((m) => modelKey(m) === current)) {
    select.value = current;
  }
}

function renderModelsList() {
  const models = store.get("models") || [];
  if (!models.length) {
    $("models-list").innerHTML = `<div class="notice">Сервер вернул пустой список.</div>`;
    return;
  }
  $("models-list").innerHTML = models
    .filter((m) => (m.type || "llm") === "llm")
    .map((m) => {
      const key = modelKey(m);
      const loaded = Array.isArray(m.loaded_instances) && m.loaded_instances.length > 0;
      const meta = [m.publisher, m.params_string, m.quantization?.name].filter(Boolean).join(" · ");
      return `
        <div class="item">
          <span>
            <div class="item-title">${escapeHtml(modelLabel(m))}</div>
            <div class="item-meta">${escapeHtml(key)}${meta ? ` · ${escapeHtml(meta)}` : ""}</div>
          </span>
          <div class="item-actions">
            <span class="tag ${loaded ? "loaded" : ""}">${loaded ? "loaded" : "idle"}</span>
            <button type="button" data-model-select="${escapeHtml(key)}">Выбрать</button>
            <button type="button" data-model-load="${escapeHtml(key)}">Load</button>
          </div>
        </div>
      `;
    })
    .join("");
}

async function loadModels() {
  const data = await api("/api/lm-studio/models");
  store.set("models", data.models || []);
  populateModelSelect();
  renderModelsList();
  $("lm-status").textContent = `Моделей: ${(data.models || []).length}`;
}

async function selectModel(model) {
  await api("/api/lm-studio/select", { method: "POST", body: JSON.stringify({ model }) });
  $("lm-model").value = model;
  toast(`Выбрана: ${model}`);
}

async function loadModel(model) {
  const contextLength = Number($("lm-load-context").value || 0) || undefined;
  await api("/api/lm-studio/load", {
    method: "POST",
    body: JSON.stringify({ model, context_length: contextLength, flash_attention: $("lm-flash-attention").checked }),
  });
  $("lm-model").value = model;
  toast(`Загружается: ${model}`);
  await loadModels();
}

async function testLm() {
  const data = await api("/api/lm-studio/test", { method: "POST", body: "{}" });
  $("lm-status").textContent = `OK · моделей ${data.models_count}, загружено ${data.loaded_count}, активная: ${data.selected_model || "—"}`;
}

async function loadStatus() {
  const status = await api("/api/status");
  store.set("status", status);
  const config = status.config || {};
  $("lm-base-url").value = config.lm_studio_base_url || "";
  const select = $("lm-model");
  const desired = config.lm_studio_model || "";
  if (desired && !Array.from(select.options).some((o) => o.value === desired)) {
    const opt = document.createElement("option");
    opt.value = desired;
    opt.textContent = desired;
    select.appendChild(opt);
  }
  select.value = desired;
  $("lm-api-mode").value = config.lm_studio_api_mode || "native";
  $("web-parser-engine").value = config.web_parser_engine || "playwright";
  $("web-parser-headless").checked = !!config.web_parser_headless;
  $("web-parser-timeout").value = config.web_parser_timeout || 30;
  $("parser-priority").value = (config.parser_priority || []).join(", ");
  $("log-level").value = config.log_level || "INFO";
}

async function loadBotSettings() {
  const data = await api("/api/bot-settings");
  $("bot-token").placeholder = data.telegram_bot_token_masked || "пусто";
  $("bot-telethon-api-id").placeholder = data.telethon_api_id_configured ? "(уже задан)" : "12345678";
  $("bot-telethon-api-hash").placeholder = data.telethon_api_hash_configured ? "(уже задан)" : "";
  $("bot-telethon-phone").value = data.telethon_phone || "";
  $("bot-auto-parse").checked = !!data.auto_parse_enabled;
  $("bot-interval").value = data.check_interval_seconds || "";
  $("bot-parse-limit").value = data.auto_parse_limit || "";
  $("bot-parse-days").value = data.auto_parse_days || "";
}

async function saveSettings() {
  const parser_priority = $("parser-priority").value.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify({
      lm_studio_base_url: $("lm-base-url").value.trim(),
      lm_studio_model: $("lm-model").value,
      lm_studio_api_mode: $("lm-api-mode").value,
      lm_studio_api_token: $("lm-api-token").value.trim() || undefined,
      web_parser_engine: $("web-parser-engine").value,
      web_parser_headless: $("web-parser-headless").checked,
      web_parser_timeout: Number($("web-parser-timeout").value) || 30,
      parser_priority,
      log_level: $("log-level").value,
    }),
  });
  $("lm-api-token").value = "";
  toast("Настройки сохранены");
  await loadStatus();
}

async function saveBotSettings() {
  const payload = {};
  const set = (key, value) => { if (value !== "" && value !== undefined && value !== null) payload[key] = value; };
  set("telegram_bot_token", $("bot-token").value.trim());
  set("telethon_api_id", $("bot-telethon-api-id").value.trim());
  set("telethon_api_hash", $("bot-telethon-api-hash").value.trim());
  set("telethon_phone", $("bot-telethon-phone").value.trim());
  payload.auto_parse_enabled = $("bot-auto-parse").checked;
  set("check_interval_seconds", Number($("bot-interval").value) || undefined);
  set("auto_parse_limit", Number($("bot-parse-limit").value) || undefined);
  set("auto_parse_days", Number($("bot-parse-days").value) || undefined);
  await api("/api/bot-settings", { method: "POST", body: JSON.stringify(payload) });
  toast("Настройки бота сохранены");
  await loadBotSettings();
}

async function exportEnv() {
  const data = await api("/api/env-export");
  const box = $("env-export-box");
  box.textContent = `# ${data.path}\n\n${data.content}`;
  box.hidden = !box.hidden;
}

async function syncEnv() {
  const data = await api("/api/env-sync", { method: "POST", body: "{}" });
  toast(`env синхронизирован: ${data.path}`);
}

pageLoaders.settings = async () => {
  await loadStatus();
  await loadBotSettings();
  await loadModels().catch(() => {});
};

// ---- Wiring ----------------------------------------------------------------

function wireEvents() {
  $("setup-btn").addEventListener("click", (e) => withBusy(e.target, setupAdmin).catch(() => {}));
  $("login-btn").addEventListener("click", (e) => withBusy(e.target, login).catch(() => {}));
  $("logout-btn").addEventListener("click", (e) => withBusy(e.target, logout).catch(() => {}));

  // Dashboard
  $("dashboard-refresh-btn").addEventListener("click", () => reloadPage("dashboard"));

  // Sources
  $("sources-refresh-btn").addEventListener("click", (e) => withBusy(e.target, loadSources).catch(() => {}));
  $("sources-search").addEventListener("input", debounce((e) => { sourcesView.filter = e.target.value; renderSources(); }, 200));
  $("sources-add-toggle-btn").addEventListener("click", () => { $("sources-add-panel").hidden = !$("sources-add-panel").hidden; });
  $("sources-catalog-toggle-btn").addEventListener("click", () => { $("sources-catalog-panel").hidden = !$("sources-catalog-panel").hidden; });
  $("manual-add-btn").addEventListener("click", (e) => withBusy(e.target, addManualSource).catch(() => {}));
  $("sources-check-all").addEventListener("change", (e) => {
    const checked = e.target.checked;
    qsa("[data-source-check]").forEach((cb) => { cb.checked = checked; });
    if (checked) {
      (store.get("sources") || []).forEach((s) => sourcesView.selected.add(s.channel_id));
    } else {
      sourcesView.selected.clear();
    }
  });
  $("sources-bulk-parse-btn").addEventListener("click", (e) => withBusy(e.target, bulkParseSources).catch(() => {}));
  $("sources-bulk-delete-btn").addEventListener("click", (e) => withBusy(e.target, bulkDeleteSources).catch(() => {}));
  $("sources-tbody").addEventListener("change", (e) => {
    const target = e.target;
    if (target.matches("[data-source-check]")) {
      const id = Number(target.dataset.sourceCheck);
      if (target.checked) sourcesView.selected.add(id);
      else sourcesView.selected.delete(id);
    }
  });
  qsa("th[data-sort]", $("sources-tbody")?.parentElement).forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sourcesView.sortKey === key) sourcesView.sortDir = -sourcesView.sortDir;
      else { sourcesView.sortKey = key; sourcesView.sortDir = 1; }
      renderSources();
    });
  });

  // Account
  $("tg-status-btn").addEventListener("click", (e) => withBusy(e.target, refreshTelegramStatus).catch(() => {}));
  $("tg-code-btn").addEventListener("click", (e) => withBusy(e.target, sendTelegramCode).catch(() => {}));
  $("tg-login-btn").addEventListener("click", (e) => withBusy(e.target, signInTelegram).catch(() => {}));
  $("tg-channels-btn").addEventListener("click", (e) => withBusy(e.target, loadTelegramChannels).catch(() => {}));
  $("tg-add-selected-btn").addEventListener("click", (e) => withBusy(e.target, addSelectedTelegramChannels).catch(() => {}));
  $("tg-channels-search").addEventListener("input", debounce((e) => { tgChannelsView.filter = e.target.value; renderTelegramChannels(); }, 200));

  // Bots
  $("bots-refresh-btn").addEventListener("click", (e) => withBusy(e.target, loadBots).catch(() => {}));
  $("new-bot-add-btn").addEventListener("click", (e) => withBusy(e.target, addBot).catch(() => {}));

  // Prompts
  $("prompts-refresh-btn").addEventListener("click", (e) => withBusy(e.target, loadPrompts).catch(() => {}));
  $("new-prompt-save-btn").addEventListener("click", (e) => withBusy(e.target, savePrompt).catch(() => {}));
  $("new-prompt-test-btn").addEventListener("click", (e) => withBusy(e.target, testPromptDraft).catch(() => {}));
  $("new-prompt-clear-btn").addEventListener("click", clearPromptForm);
  $("prompts-tasks").addEventListener("click", (e) => {
    const task = e.target?.dataset?.promptTask;
    if (!task) return;
    promptsViewTask = task;
    $("new-prompt-task").value = task;
    renderPrompts();
  });

  // Pipelines
  $("pipelines-refresh-btn").addEventListener("click", () => reloadPage("pipelines"));
  $("pipeline-new-btn").addEventListener("click", () => openPipelineEditor(null));
  $("pipeline-template-btn").addEventListener("click", (e) => withBusy(e.target, createPipelineFromTemplate).catch(() => {}));
  $("pipeline-editor-close-btn").addEventListener("click", closePipelineEditor);
  $("pipeline-add-step-btn").addEventListener("click", addPipelineStep);
  $("pipeline-save-btn").addEventListener("click", (e) => withBusy(e.target, savePipeline).catch(() => {}));
  $("pipeline-run-btn").addEventListener("click", (e) => withBusy(e.target, () => runPipelineNow()).catch(() => {}));
  $("pipeline-steps").addEventListener("click", (event) => {
    const d = event.target?.dataset || {};
    if (d.stepRemove !== undefined) {
      editorState.steps.splice(Number(d.stepRemove), 1);
      renderStepEditor();
    } else if (d.stepUp !== undefined) {
      const i = Number(d.stepUp);
      if (i > 0) {
        [editorState.steps[i - 1], editorState.steps[i]] = [editorState.steps[i], editorState.steps[i - 1]];
        // sync textareas before re-render
        editorState.steps = readStepsFromEditor();
        renderStepEditor();
      }
    } else if (d.stepDown !== undefined) {
      const i = Number(d.stepDown);
      if (i < editorState.steps.length - 1) {
        [editorState.steps[i], editorState.steps[i + 1]] = [editorState.steps[i + 1], editorState.steps[i]];
        editorState.steps = readStepsFromEditor();
        renderStepEditor();
      }
    }
  });

  // Runs
  $("runs-refresh-btn").addEventListener("click", () => reloadPage("runs"));
  $("runs-filter").addEventListener("change", () => loadRuns().catch((err) => toast(err.message)));
  $("run-detail-close-btn").addEventListener("click", () => { $("run-detail").hidden = true; });

  // News
  $("news-load-btn").addEventListener("click", (e) => withBusy(e.target, loadNews).catch(() => {}));
  $("summary-btn").addEventListener("click", (e) => withBusy(e.target, summarizeNews).catch(() => {}));
  $("post-preview-btn").addEventListener("click", (e) => withBusy(e.target, previewPost).catch(() => {}));
  $("post-send-btn").addEventListener("click", (e) => withBusy(e.target, sendPost).catch(() => {}));
  $("parse-all-btn").addEventListener("click", (e) => withBusy(e.target, parseAll).catch(() => {}));

  // Settings
  $("settings-refresh-btn").addEventListener("click", () => reloadPage("settings"));
  $("settings-save-btn").addEventListener("click", (e) => withBusy(e.target, saveSettings).catch(() => {}));
  $("bot-settings-save-btn").addEventListener("click", (e) => withBusy(e.target, saveBotSettings).catch(() => {}));
  $("bot-env-export-btn").addEventListener("click", (e) => withBusy(e.target, exportEnv).catch(() => {}));
  $("env-sync-btn").addEventListener("click", (e) => withBusy(e.target, syncEnv).catch(() => {}));
  $("models-load-btn").addEventListener("click", (e) => withBusy(e.target, loadModels).catch(() => {}));
  $("selected-model-load-btn").addEventListener("click", (e) => withBusy(e.target, async () => {
    const model = $("lm-model").value;
    if (!model) throw new Error("Выберите модель");
    await loadModel(model);
  }).catch(() => {}));
  $("lm-model").addEventListener("change", (e) => {
    const model = e.target.value;
    if (model) selectModel(model).catch((err) => toast(err.message));
  });
  $("lm-test-btn").addEventListener("click", (e) => withBusy(e.target, testLm).catch(() => {}));

  // Delegated clicks for dynamic content
  document.body.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const d = target.dataset;
    if (d.sourceParse) parseSource(d.sourceParse).catch((err) => toast(err.message));
    else if (d.sourceRemove) removeSource(d.sourceRemove).catch((err) => toast(err.message));
    else if (d.sourceGroup) { sourcesView.group = d.sourceGroup; renderSources(); }
    else if (d.defaultSource) {
      const [c, u] = d.defaultSource.split("::");
      addDefaultSource(c, u).catch((err) => toast(err.message));
    } else if (d.botToggle) toggleBot(d.botToggle).catch((err) => toast(err.message));
    else if (d.botEditToken) patchBotField(d.botEditToken, "token").catch((err) => toast(err.message));
    else if (d.botEditChat) patchBotField(d.botEditChat, "default_chat_id").catch((err) => toast(err.message));
    else if (d.botEditLabel) patchBotField(d.botEditLabel, "label").catch((err) => toast(err.message));
    else if (d.botRemove) removeBot(d.botRemove).catch((err) => toast(err.message));
    else if (d.promptActivate) activatePrompt(d.promptActivate).catch((err) => toast(err.message));
    else if (d.promptEdit) editPromptInline(d.promptEdit);
    else if (d.promptRemove) removePrompt(d.promptRemove).catch((err) => toast(err.message));
    else if (d.modelSelect) selectModel(d.modelSelect).catch((err) => toast(err.message));
    else if (d.modelLoad) loadModel(d.modelLoad).catch((err) => toast(err.message));
    else if (d.pipelineRun) runPipelineNow(d.pipelineRun).catch((err) => toast(err.message));
    else if (d.pipelineEdit) editPipeline(d.pipelineEdit).catch((err) => toast(err.message));
    else if (d.pipelineRemove) removePipeline(d.pipelineRemove).catch((err) => toast(err.message));
    else if (d.runOpen) openRunDetail(d.runOpen).catch((err) => toast(err.message));
  });
}

// ---- Bootstrap -------------------------------------------------------------

(async () => {
  wireEvents();
  wireTabClicks();
  await loadAuthState();
  // Ensure something is shown even if the auth-state path didn't navigate
  // (no hash + already authenticated, for example).
  if (!$("app-shell").hidden) {
    navigate();
  }
})();
