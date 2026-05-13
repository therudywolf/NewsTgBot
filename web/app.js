const state = {
  telegramChannels: [],
  defaults: null,
};

const $ = (id) => document.getElementById(id);

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
  const response = await fetch(path, {
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
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "⏳ Выполняется...";
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

function renderMetrics(payload) {
  const stats = payload.stats || {};
  const config = payload.config || {};
  const items = [
    ["Источники", stats.channels_count ?? 0],
    ["Новости", stats.news_count ?? 0],
    ["Теги", stats.tags_count ?? 0],
    ["Telegram Bot", config.telegram_bot_configured ? "OK" : "ENV"],
    ["LM Token", config.lm_studio_token_configured ? "OK" : "нет"],
  ];

  $("metrics").innerHTML = items
    .map(([label, value]) => `<div class="metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`)
    .join("");

  $("status-line").textContent = `БД: ${config.database_path || "-"} · ${payload.time || ""}`;
  $("lm-base-url").value = config.lm_studio_base_url || "";
  $("lm-model").value = config.lm_studio_model || "";
  $("lm-api-mode").value = config.lm_studio_api_mode || "native";
}

async function loadStatus() {
  const payload = await api("/api/status");
  renderMetrics(payload);
}

async function loadBotSettings() {
  const data = await api("/api/bot-settings");
  $("bot-token").placeholder = data.telegram_bot_token_masked || "не задан";
  $("bot-token").value = "";
  $("bot-telethon-api-id").value = "";
  $("bot-telethon-api-id").placeholder = data.telethon_api_id_configured ? "задан" : "не задан";
  $("bot-telethon-api-hash").value = "";
  $("bot-telethon-api-hash").placeholder = data.telethon_api_hash_configured ? "задан" : "не задан";
  $("bot-telethon-phone").value = data.telethon_phone || "";
  $("bot-auto-parse").checked = !!data.auto_parse_enabled;
  $("bot-interval").value = data.check_interval_seconds || 3600;
  $("bot-parse-limit").value = data.auto_parse_limit || 200;
  $("bot-parse-days").value = data.auto_parse_days || 7;
  const status = data.telegram_bot_token_configured ? "Token задан" : "Token не задан";
  const telethon = data.telethon_api_id_configured ? "Telethon настроен" : "Telethon не настроен";
  $("bot-settings-status").textContent = `${status} · ${telethon} · Авто-парсинг: ${data.auto_parse_enabled ? "вкл" : "выкл"}`;
}

async function saveBotSettings() {
  const payload = {};
  const token = $("bot-token").value.trim();
  if (token) payload.telegram_bot_token = token;
  const apiId = $("bot-telethon-api-id").value.trim();
  if (apiId) payload.telethon_api_id = apiId;
  const apiHash = $("bot-telethon-api-hash").value.trim();
  if (apiHash) payload.telethon_api_hash = apiHash;
  const phone = $("bot-telethon-phone").value.trim();
  payload.telethon_phone = phone;
  payload.auto_parse_enabled = $("bot-auto-parse").checked;
  payload.check_interval_seconds = Number($("bot-interval").value) || 3600;
  payload.auto_parse_limit = Number($("bot-parse-limit").value) || 200;
  payload.auto_parse_days = Number($("bot-parse-days").value) || 7;

  await api("/api/bot-settings", { method: "POST", body: JSON.stringify(payload) });
  toast("Настройки бота сохранены. Перезапустите контейнер bot для применения токена.");
  await loadBotSettings();
  await loadStatus();
}

async function exportEnv() {
  const data = await api("/api/env-export");
  const box = $("env-export-box");
  box.textContent = data.content;
  box.style.display = box.style.display === "none" ? "block" : "none";
}

async function saveSettings() {
  const payload = {
    lm_studio_base_url: $("lm-base-url").value.trim(),
    lm_studio_model: $("lm-model").value.trim(),
    lm_studio_api_mode: $("lm-api-mode").value,
  };
  const data = await api("/api/settings", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  $("lm-status").textContent = `Сохранено. Модель: ${data.lm_studio_model || "не выбрана"}`;
  toast("Настройки сохранены");
}

function modelLabel(model) {
  return model.display_name || model.key || model.id || "unknown";
}

function modelKey(model) {
  return model.key || model.id || model.display_name;
}

function renderModels(models) {
  if (!models.length) {
    $("models-list").innerHTML = `<div class="notice">Сервер вернул пустой список моделей.</div>`;
    return;
  }

  $("models-list").innerHTML = models
    .filter((model) => (model.type || "llm") === "llm")
    .map((model) => {
      const key = modelKey(model);
      const loaded = Array.isArray(model.loaded_instances) && model.loaded_instances.length > 0;
      const quant = model.quantization?.name || "";
      const meta = [model.publisher, model.params_string, quant, model.max_context_length ? `ctx ${model.max_context_length}` : ""]
        .filter(Boolean)
        .join(" · ");
      return `
        <div class="item">
          <div>
            <div class="item-title">${escapeHtml(modelLabel(model))}</div>
            <div class="item-meta">${escapeHtml(key)}${meta ? ` · ${escapeHtml(meta)}` : ""}</div>
          </div>
          <div class="item-actions">
            <span class="tag ${loaded ? "loaded" : ""}">${loaded ? "loaded" : "not loaded"}</span>
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
  renderModels(data.models || []);
  $("lm-status").textContent = `Моделей: ${(data.models || []).length}`;
}

async function testLm() {
  const data = await api("/api/lm-studio/test", { method: "POST", body: "{}" });
  $("lm-status").textContent = `OK: models ${data.models_count}, loaded ${data.loaded_count}, selected ${data.selected_model || "-"}`;
}

async function selectModel(model) {
  await api("/api/lm-studio/select", {
    method: "POST",
    body: JSON.stringify({ model }),
  });
  $("lm-model").value = model;
  toast(`Выбрана модель ${model}`);
}

async function loadModel(model) {
  const contextLength = Number($("lm-load-context").value || 0) || undefined;
  await api("/api/lm-studio/load", {
    method: "POST",
    body: JSON.stringify({
      model,
      context_length: contextLength,
      flash_attention: $("lm-flash-attention").checked,
    }),
  });
  $("lm-model").value = model;
  toast(`Модель загружается/загружена: ${model}`);
  await loadModels();
}

async function refreshTelegramStatus() {
  const data = await api("/api/telegram/status");
  if (!data.configured) {
    $("tg-status").textContent = "TELETHON_API_ID и TELETHON_API_HASH не заданы в env.";
    return;
  }
  const user = data.user ? `${data.user.first_name || ""} ${data.user.username ? `@${data.user.username}` : ""}`.trim() : "";
  $("tg-status").textContent = `configured: ${data.configured}, connected: ${data.connected}, authorized: ${data.authorized}${user ? `, user: ${user}` : ""}`;
}

async function sendTelegramCode() {
  const phone = $("tg-phone").value.trim();
  if (!phone) throw new Error("Укажите телефон");
  const data = await api("/api/telegram/send-code", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
  $("tg-status").textContent = `Код отправлен на ${data.phone}.`;
  $("tg-code").focus();
}

async function signInTelegram() {
  const payload = {
    phone: $("tg-phone").value.trim(),
    code: $("tg-code").value.trim(),
    password: $("tg-password").value,
  };
  const data = await api("/api/telegram/sign-in", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  $("tg-status").textContent = data.password_required ? "Нужен 2FA password." : `authorized: ${data.authorized}`;
}

function renderTelegramChannels(channels) {
  state.telegramChannels = channels;
  $("tg-channels").innerHTML = channels
    .map((channel, index) => `
      <label class="item">
        <input type="checkbox" data-tg-channel="${index}" />
        <span>
          <span class="item-title">${escapeHtml(channel.title)}</span>
          <span class="item-meta">${escapeHtml(channel.username ? `@${channel.username}` : channel.id)}</span>
        </span>
        <span class="tag">${channel.broadcast ? "channel" : "group"}</span>
      </label>
    `)
    .join("");
}

async function loadTelegramChannels() {
  const data = await api("/api/telegram/channels");
  renderTelegramChannels(data.channels || []);
  toast(`Каналов найдено: ${(data.channels || []).length}`);
}

async function addSelectedTelegramChannels() {
  const checked = [...document.querySelectorAll("[data-tg-channel]:checked")];
  const channels = checked.map((node) => state.telegramChannels[Number(node.dataset.tgChannel)]);
  if (!channels.length) throw new Error("Выберите каналы");
  await api("/api/telegram/channels", {
    method: "POST",
    body: JSON.stringify({ channels }),
  });
  toast(`Добавлено: ${channels.length}`);
  await loadSources();
}

function sourceTitle(source) {
  return source.title || source.username || source.channel_id;
}

function renderSources(sources) {
  if (!sources.length) {
    $("sources-list").innerHTML = `<div class="notice">Источники пока не добавлены.</div>`;
    return;
  }

  $("sources-list").innerHTML = sources
    .map((source) => {
      const stats = source.stats || {};
      return `
        <div class="item">
          <div>
            <div class="item-title">${escapeHtml(sourceTitle(source))}</div>
            <div class="item-meta">${escapeHtml(source.source_type)} · ${escapeHtml(source.username || "")} · news ${stats.total ?? 0}</div>
          </div>
          <div class="item-actions">
            <button type="button" data-source-parse="${source.channel_id}">Парсить</button>
            <button type="button" data-source-remove="${source.channel_id}" class="danger">Удалить</button>
          </div>
        </div>
      `;
    })
    .join("");
}

async function loadSources() {
  const data = await api("/api/sources");
  renderSources(data.sources || []);
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

function renderDefaults(payload) {
  state.defaults = payload;
  const categories = payload.categories || {};
  const rows = [];
  Object.entries(categories).forEach(([categoryId, category]) => {
    rows.push(`<div class="item"><div class="item-title">${escapeHtml(category.name || categoryId)}</div><span></span><span class="tag">${(category.sources || []).length}</span></div>`);
    (category.sources || []).forEach((source) => {
      rows.push(`
        <div class="item">
          <span></span>
          <span>
            <span class="item-title">${escapeHtml(source.title)}</span>
            <span class="item-meta">${escapeHtml(source.source_config?.rss_url || source.username)}</span>
          </span>
          <button type="button" data-default-source="${escapeHtml(categoryId)}::${escapeHtml(source.username)}">Добавить</button>
        </div>
      `);
    });
  });
  $("default-sources").innerHTML = rows.join("");
}

async function loadDefaults() {
  const data = await api("/api/default-sources");
  renderDefaults(data);
}

async function addDefaultSource(categoryId, username) {
  const category = state.defaults?.categories?.[categoryId];
  const source = (category?.sources || []).find((item) => item.username === username);
  if (!source) throw new Error("Источник не найден");
  await api("/api/sources/default", {
    method: "POST",
    body: JSON.stringify(source),
  });
  toast(`Добавлен источник ${source.title}`);
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
  await api(`/api/sources/${channelId}`, { method: "DELETE" });
  toast("Источник удален");
  await loadSources();
}

async function parseAll() {
  const data = await api("/api/sources/parse-all?limit=100&days=3", {
    method: "POST",
    body: "{}",
  });
  toast(`Parsed ${data.totals.parsed}, skipped ${data.totals.skipped}, errors ${data.totals.errors}`);
  await Promise.all([loadSources(), loadNews()]);
}

function renderNews(rows) {
  if (!rows.length) {
    $("news-list").innerHTML = `<div class="notice">Новостей за период нет.</div>`;
    return;
  }

  $("news-list").innerHTML = rows
    .map((item) => `
      <article class="news-card">
        <div class="news-meta">${escapeHtml(item.date)} · ${escapeHtml(item.title || item.username || item.channel_id)}</div>
        <div class="news-text">${escapeHtml(item.text)}</div>
      </article>
    `)
    .join("");
}

async function loadNews() {
  const days = Number($("news-days").value || 1);
  const data = await api(`/api/news?days=${days}&limit=100`);
  renderNews(data.news || []);
}

async function summarizeNews() {
  const days = Number($("news-days").value || 1);
  const data = await api("/api/news/summary", {
    method: "POST",
    body: JSON.stringify({ days }),
  });
  $("summary-box").textContent = `Новостей: ${data.input_count}, после дедупликации: ${data.unique_count}\n\n${data.summary}`;
}

function wireEvents() {
  $("refresh-btn").addEventListener("click", () => runAll());
  $("bot-settings-refresh-btn").addEventListener("click", () => loadBotSettings().catch((err) => toast(err.message)));
  $("bot-settings-save-btn").addEventListener("click", (e) => withBusy(e.target, saveBotSettings).catch((err) => toast(err.message)));
  $("bot-env-export-btn").addEventListener("click", (e) => withBusy(e.target, exportEnv).catch((err) => toast(err.message)));
  $("settings-save-btn").addEventListener("click", (e) => withBusy(e.target, saveSettings).catch((err) => toast(err.message)));
  $("models-load-btn").addEventListener("click", (e) => withBusy(e.target, loadModels).catch((err) => toast(err.message)));
  $("selected-model-load-btn").addEventListener("click", (e) => withBusy(e.target, async () => {
    const model = $("lm-model").value.trim();
    if (!model) throw new Error("Выберите модель");
    await loadModel(model);
  }).catch((err) => toast(err.message)));
  $("lm-test-btn").addEventListener("click", (e) => withBusy(e.target, testLm).catch((err) => toast(err.message)));
  $("tg-status-btn").addEventListener("click", (e) => withBusy(e.target, refreshTelegramStatus).catch((err) => toast(err.message)));
  $("tg-code-btn").addEventListener("click", (e) => withBusy(e.target, sendTelegramCode).catch((err) => toast(err.message)));
  $("tg-login-btn").addEventListener("click", (e) => withBusy(e.target, signInTelegram).catch((err) => toast(err.message)));
  $("tg-channels-btn").addEventListener("click", (e) => withBusy(e.target, loadTelegramChannels).catch((err) => toast(err.message)));
  $("tg-add-selected-btn").addEventListener("click", (e) => withBusy(e.target, addSelectedTelegramChannels).catch((err) => toast(err.message)));
  $("sources-refresh-btn").addEventListener("click", () => loadSources().catch((err) => toast(err.message)));
  $("manual-add-btn").addEventListener("click", (e) => withBusy(e.target, addManualSource).catch((err) => toast(err.message)));
  $("defaults-refresh-btn").addEventListener("click", () => loadDefaults().catch((err) => toast(err.message)));
  $("parse-all-btn").addEventListener("click", (e) => withBusy(e.target, parseAll).catch((err) => toast(err.message)));
  $("news-load-btn").addEventListener("click", () => loadNews().catch((err) => toast(err.message)));
  $("summary-btn").addEventListener("click", (e) => withBusy(e.target, summarizeNews).catch((err) => toast(err.message)));

  document.body.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const modelSelect = target.dataset.modelSelect;
    const modelLoad = target.dataset.modelLoad;
    const sourceParse = target.dataset.sourceParse;
    const sourceRemove = target.dataset.sourceRemove;
    const defaultSource = target.dataset.defaultSource;

    if (modelSelect) selectModel(modelSelect).catch((err) => toast(err.message));
    if (modelLoad) loadModel(modelLoad).catch((err) => toast(err.message));
    if (sourceParse) parseSource(sourceParse).catch((err) => toast(err.message));
    if (sourceRemove) removeSource(sourceRemove).catch((err) => toast(err.message));
    if (defaultSource) {
      const [categoryId, username] = defaultSource.split("::");
      addDefaultSource(categoryId, username).catch((err) => toast(err.message));
    }
  });
}

async function runAll() {
  await Promise.allSettled([
    loadStatus(),
    loadBotSettings(),
    refreshTelegramStatus(),
    loadSources(),
    loadDefaults(),
    loadNews(),
  ]);
}

wireEvents();
runAll().catch((err) => toast(err.message));
