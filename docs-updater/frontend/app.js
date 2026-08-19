/* Одна страница на ванильном JS. Никаких библиотек и обращений в интернет. */

const $ = (id) => document.getElementById(id);
const state = { doc: null, result: null };

/* ---------- сеть (только к своему же бэкенду) ---------- */

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let data = null;
  try { data = await response.json(); } catch (e) { data = null; }
  if (!response.ok) {
    const message = (data && (data.error || data.detail)) || `Ошибка ${response.status}`;
    const error = new Error(typeof message === 'string' ? message : JSON.stringify(message));
    error.hint = data && data.hint;
    throw error;
  }
  return data;
}

const json = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/* ---------- интерфейсные мелочи ---------- */

let toastTimer = null;
function toast(text, bad = false) {
  const node = $('toast');
  node.textContent = text;
  node.className = 'toast' + (bad ? ' toast--bad' : '');
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, bad ? 9000 : 4000);
}

function busy(text) {
  $('overlay-text').textContent = text || 'Работаем…';
  $('overlay').hidden = false;
}
const idle = () => { $('overlay').hidden = true; };

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

function showError(error) {
  const hint = error.hint ? ` → ${error.hint}` : '';
  toast(error.message + hint, true);
  const box = $('warnings');
  box.innerHTML = `<div class="warning warning--error">${escapeHtml(error.message)}${
    error.hint ? ' <br><b>Что делать:</b> ' + escapeHtml(error.hint) : ''
  }</div>`;
}

/* ---------- шаг 1: статус и настройки ---------- */

async function loadStatus() {
  const data = await api('/api/status');
  const cfg = data.config;
  $('docs-dir').value = cfg.docs_dir_raw;
  $('style-guide-path').value = cfg.style_guide_raw;
  $('generation-model').value = cfg.generation_model;
  $('embedding-model').value = cfg.embedding_model;

  const badge = $('ollama-status');
  if (!data.ollama.available) {
    badge.className = 'status status--bad';
    badge.textContent = 'Ollama не отвечает';
    badge.title = (data.ollama.error || '') + ' ' + (data.ollama.hint || '');
  } else {
    const missing = [];
    if (!data.ollama.generation_model_installed) missing.push(cfg.generation_model);
    if (!data.ollama.embedding_model_installed) missing.push(cfg.embedding_model);
    if (missing.length) {
      badge.className = 'status status--bad';
      badge.textContent = 'Нет моделей: ' + missing.join(', ');
      badge.title = missing.map((m) => `ollama pull ${m}`).join('\n');
      const box = $('warnings');
      box.innerHTML = missing.map((m) =>
        `<div class="warning">Модель <b>${escapeHtml(m)}</b> не установлена. Выполните в терминале: <code>ollama pull ${escapeHtml(m)}</code></div>`
      ).join('');
    } else {
      badge.className = 'status status--ok';
      badge.textContent = 'Ollama на связи';
      badge.title = 'Модели установлены';
    }
  }

  const index = data.index;
  $('index-info').textContent = index.exists
    ? `В индексе: ${index.documents_count} док. / ${index.sections_count} секций. Файлов в папке: ${data.markdown_files}`
    : `Индекс не построен. Файлов .md в папке: ${data.markdown_files}`;

  return data;
}

async function loadDocuments() {
  const data = await api('/api/documents');
  const select = $('manual-doc');
  select.innerHTML = '<option value="">— документ из папки —</option>' +
    data.documents.map((doc) => `<option value="${escapeHtml(doc.path)}">${escapeHtml(doc.title)} (${escapeHtml(doc.path)})</option>`).join('');
}

async function loadResults() {
  const data = await api('/api/results');
  const box = $('results-list');
  if (!data.results.length) {
    box.innerHTML = '<p class="muted">Пока пусто. Обновлённые документы появятся здесь.</p>';
    return;
  }
  box.innerHTML = data.results.map((item) => `
    <div class="result-row">
      <a href="/api/download?file=${encodeURIComponent(item.file)}">${escapeHtml(item.file)}</a>
      <span class="result-row__meta">${escapeHtml(item.saved_at)} · ${Math.round(item.size / 1024)} КБ</span>
    </div>`).join('');
}

async function loadGuide() {
  const data = await api('/api/style-guide');
  $('guide-text').value = data.content || '';
  $('guide-info').textContent = data.exists
    ? `Гайд подключён: ${data.path}`
    : `Файл гайда пока не найден: ${data.path}`;
}

/* ---------- шаг 3: поиск документа ---------- */

function selectDoc(path, title) {
  state.doc = { path, title: title || path };
  $('chosen-doc').textContent = `Выбран документ: ${state.doc.title} (${path})`;
  $('generate').disabled = false;
  document.querySelectorAll('.candidate').forEach((node) => {
    node.classList.toggle('candidate--active', node.dataset.path === path);
  });
}

function renderCandidates(candidates) {
  const box = $('candidates');
  if (!candidates.length) {
    box.innerHTML = '<p class="muted">Ничего не нашлось. Постройте индекс или уточните описание.</p>';
    return;
  }
  box.innerHTML = candidates.map((item) => `
    <div class="candidate" data-path="${escapeHtml(item.path)}" data-title="${escapeHtml(item.title)}">
      <div class="candidate__title">${escapeHtml(item.title)}</div>
      <div class="candidate__score">${item.relevance}%<div class="bar"><span style="width:${item.relevance}%"></span></div></div>
      <div class="candidate__path mono">${escapeHtml(item.path)}${item.heading ? ' · ' + escapeHtml(item.heading) : ''}</div>
      <div class="candidate__snippet">${escapeHtml(item.snippet)}</div>
    </div>`).join('');
  box.querySelectorAll('.candidate').forEach((node) => {
    node.addEventListener('click', () => selectDoc(node.dataset.path, node.dataset.title));
  });
  selectDoc(candidates[0].path, candidates[0].title);
}

/* ---------- шаг 5: diff ---------- */

function renderInline(parts) {
  return parts.map((part) => {
    const text = escapeHtml(part.text);
    if (part.type === 'added') return `<ins>${text}</ins>`;
    if (part.type === 'removed') return `<del>${text}</del>`;
    return text;
  }).join('');
}

function renderDiff(diff) {
  const stats = diff.stats;
  $('diff-stats').innerHTML =
    `<span>Изменено абзацев: <b>${stats.changed}</b></span>` +
    `<span>Добавлено: <b>${stats.added}</b></span>` +
    `<span>Удалено: <b>${stats.removed}</b></span>` +
    `<span>Без изменений: <b>${stats.unchanged}</b></span>`;

  $('diff-view').innerHTML = diff.blocks.map((block) => {
    if (block.type === 'equal') {
      return `<div class="diff__block diff__equal">
        <div class="diff__cell">${escapeHtml(block.old)}</div>
        <div class="diff__cell">${escapeHtml(block.new)}</div></div>`;
    }
    if (block.type === 'insert') {
      return `<div class="diff__block">
        <div class="diff__cell diff__cell--empty"><div class="diff__label">было</div>—</div>
        <div class="diff__cell diff__cell--add"><div class="diff__label">добавлено</div>${escapeHtml(block.new)}</div></div>`;
    }
    if (block.type === 'delete') {
      return `<div class="diff__block">
        <div class="diff__cell diff__cell--del"><div class="diff__label">удалено</div>${escapeHtml(block.old)}</div>
        <div class="diff__cell diff__cell--empty"><div class="diff__label">стало</div>—</div></div>`;
    }
    const inline = block.inline || { old: [{ type: 'same', text: block.old }], new: [{ type: 'same', text: block.new }] };
    return `<div class="diff__block">
      <div class="diff__cell diff__cell--del"><div class="diff__label">было</div>${renderInline(inline.old)}</div>
      <div class="diff__cell diff__cell--add"><div class="diff__label">стало</div>${renderInline(inline.new)}</div></div>`;
  }).join('');
}

function renderWarnings(warnings) {
  $('warnings').innerHTML = (warnings || [])
    .map((text) => `<div class="warning">${escapeHtml(text)}</div>`).join('');
}

/* ---------- обработчики ---------- */

$('save-config').addEventListener('click', async () => {
  busy('Сохраняем настройки…');
  try {
    await json('/api/config', {
      docs_dir: $('docs-dir').value,
      style_guide: $('style-guide-path').value,
      generation_model: $('generation-model').value,
      embedding_model: $('embedding-model').value,
    });
    await Promise.all([loadStatus(), loadDocuments(), loadGuide()]);
    toast('Настройки сохранены');
  } catch (error) { showError(error); } finally { idle(); }
});

$('reindex').addEventListener('click', async () => {
  busy('Считаем эмбеддинги локально. На первой индексации это может занять пару минут…');
  try {
    const index = await json('/api/reindex', {});
    await loadStatus();
    await loadDocuments();
    const reused = index.reused_sections
      ? `, переиспользовано без пересчёта: ${index.reused_sections}`
      : '';
    toast(`Индекс готов: ${index.documents_count} документов, ${index.sections_count} секций${reused}`);
  } catch (error) { showError(error); } finally { idle(); }
});

$('guide-file').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  busy('Загружаем гайд…');
  try {
    const form = new FormData();
    form.append('file', file);
    const data = await api('/api/style-guide/upload', { method: 'POST', body: form });
    $('guide-text').value = data.content;
    $('guide-info').textContent = `Гайд подключён: ${data.path}`;
    toast('Гайд загружен');
  } catch (error) { showError(error); } finally { idle(); event.target.value = ''; }
});

$('save-guide').addEventListener('click', async () => {
  busy('Сохраняем гайд…');
  try {
    await api('/api/style-guide', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: $('guide-text').value }),
    });
    await loadGuide();
    toast('Гайд сохранён');
  } catch (error) { showError(error); } finally { idle(); }
});

$('find-doc').addEventListener('click', async () => {
  const query = $('change-text').value.trim();
  if (!query) { toast('Опишите, что изменилось', true); return; }
  busy('Ищем подходящий документ…');
  try {
    const data = await json('/api/search', { query });
    renderCandidates(data.candidates);
  } catch (error) { showError(error); } finally { idle(); }
});

$('manual-doc').addEventListener('change', (event) => {
  if (event.target.value) {
    selectDoc(event.target.value, event.target.selectedOptions[0].textContent);
  }
});

$('generate').addEventListener('click', async () => {
  const change = $('change-text').value.trim();
  if (!state.doc) { toast('Сначала выберите документ', true); return; }
  if (!change) { toast('Опишите, что изменилось', true); return; }
  busy('Модель обновляет документ. Это самая долгая часть — обычно от 30 секунд.');
  try {
    const data = await json('/api/generate', { doc_path: state.doc.path, change_description: change });
    state.result = data;
    renderWarnings(data.warnings.concat(data.style_guide_used ? [] : ['Гайд по стилю пуст — правки сделаны без него.']));
    renderDiff(data.diff);
    $('result-view').textContent = data.updated;
    $('result-file').textContent = data.result_path;
    $('step-diff').hidden = false;
    $('step-diff').scrollIntoView({ behavior: 'smooth' });
    await loadResults();
    if (!data.diff.has_changes) toast('Модель ничего не изменила — уточните описание правки', true);
    else toast('Готово. Оригинал не тронут, результат сохранён отдельным файлом.');
  } catch (error) { showError(error); } finally { idle(); }
});

$('only-changes').addEventListener('change', (event) => {
  $('diff-view').classList.toggle('diff--only-changes', event.target.checked);
});

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((other) => other.classList.remove('tab--active'));
    tab.classList.add('tab--active');
    const showResult = tab.dataset.view === 'result';
    $('result-view').hidden = !showResult;
    $('diff-view').hidden = showResult;
  });
});

$('download').addEventListener('click', () => {
  if (!state.result) return;
  window.location.href = '/api/download?file=' + encodeURIComponent(state.result.result_file);
});

$('apply').addEventListener('click', async () => {
  if (!state.result) return;
  const ok = confirm(`Заменить оригинал ${state.result.doc_path} обновлённой версией?\nКопия исходного файла останется рядом (.bak-…).`);
  if (!ok) return;
  busy('Записываем в оригинал…');
  try {
    const data = await json('/api/apply', {
      doc_path: state.result.doc_path,
      result_path: state.result.result_file,
    });
    await loadStatus();
    toast(
      `Оригинал обновлён. Резервная копия: ${data.backup}.` +
      (data.index_updated ? ' Индекс обновлён.' : ' Индекс не обновлён — нажмите «Переиндексировать».')
    );
  } catch (error) { showError(error); } finally { idle(); }
});

/* ---------- старт ---------- */

(async function init() {
  try {
    await loadStatus();
    await loadDocuments();
    await loadGuide();
    await loadResults();
  } catch (error) { showError(error); }
})();
