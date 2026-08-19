/* Одна страница на ванильном JS. Никаких библиотек и обращений в интернет. */

const $ = (id) => document.getElementById(id);
const state = { doc: null, result: null };

/* ---------- интерфейсные мелочи ---------- */

let busyTimer = null;
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
  const message = text || 'Работаем…';
  const startedAt = Date.now();
  const tick = () => {
    const seconds = Math.round((Date.now() - startedAt) / 1000);
    const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    $('overlay-text').textContent = `${message} (${clock})`;
  };
  tick();
  clearInterval(busyTimer);
  busyTimer = setInterval(tick, 1000);
  $('overlay').hidden = false;
}

const idle = () => {
  clearInterval(busyTimer);
  $('overlay').hidden = true;
};

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
  const data = await Api.status();
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
  const data = await Api.documents();
  const select = $('manual-doc');
  select.innerHTML = '<option value="">— документ из папки —</option>' +
    data.documents.map((doc) => `<option value="${escapeHtml(doc.path)}">${escapeHtml(doc.title)} (${escapeHtml(doc.path)})</option>`).join('');
}

async function loadResults() {
  const data = await Api.results();
  const box = $('results-list');
  if (!data.results.length) {
    box.innerHTML = '<p class="muted">Пока пусто. Обновлённые документы появятся здесь.</p>';
    return;
  }
  box.innerHTML = data.results.map((item) => {
    const scope = item.mode === 'section' && item.section
      ? `раздел «${escapeHtml(item.section.split(' > ').pop())}»`
      : 'весь документ';
    const description = item.change_description
      ? escapeHtml(item.change_description.length > 90
          ? item.change_description.slice(0, 90) + '…'
          : item.change_description)
      : '';
    const edited = item.edited_at ? ' · правлено вручную' : '';
    return `
    <div class="result-row">
      <div class="result-row__main">
        <a href="/api/download?file=${encodeURIComponent(item.file)}">${escapeHtml(item.doc_path || item.file)}</a>
        ${description ? `<div class="result-row__desc">${description}</div>` : ''}
      </div>
      <span class="result-row__meta">${escapeHtml(item.saved_at)} · ${scope}${edited}</span>
    </div>`;
  }).join('');
}

async function loadGuide() {
  const data = await Api.styleGuide();
  $('guide-text').value = data.content || '';
  $('guide-info').textContent = data.exists
    ? `Гайд подключён: ${data.path}`
    : `Файл гайда пока не найден: ${data.path}`;
}


/* ---------- правила оформления и обученный формат ---------- */

function renderStyleSources(data) {
  $('rules-list').innerHTML = data.guides.map((guide) => `
    <div class="file-list__row">
      <span>${escapeHtml(guide.file)}${guide.exists ? '' : ' — файл не найден'}</span>
      <button class="file-list__drop" data-rule="${escapeHtml(guide.file)}">убрать</button>
    </div>`).join('') || '<p class="muted">Дополнительных файлов правил нет.</p>';

  $('rules-list').querySelectorAll('[data-rule]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        renderStyleSources(await Api.removeRules(button.dataset.rule));
        toast('Файл правил убран из списка');
      } catch (error) { showError(error); }
    });
  });

  const derived = data.derived || {};
  const status = $('format-status');
  if (derived.exists) {
    const docs = (derived.profile && derived.profile.documents) || 0;
    status.className = 'format-status format-status--ok';
    status.textContent = `Формат изучен по образцам (${docs} док., ${derived.learned_at}). `
      + (data.use_derived_guide ? 'Применяется при каждой правке.' : 'Сейчас выключен.');
    $('format-details').hidden = false;
    $('format-text').textContent = derived.text || '';
  } else {
    status.className = 'format-status format-status--none';
    status.textContent = 'Формат ещё не изучен: добавьте образцы и нажмите «Изучить формат».';
    $('format-details').hidden = true;
  }
  $('use-derived').checked = Boolean(data.use_derived_guide);
}

async function loadSamples() {
  const data = await Api.samples();
  $('samples-list').innerHTML = data.samples.map((item) => `
    <div class="file-list__row">
      <span>${escapeHtml(item.file)}</span>
      <button class="file-list__drop" data-sample="${escapeHtml(item.file)}">удалить</button>
    </div>`).join('') || '<p class="muted">Образцов пока нет.</p>';

  $('samples-list').querySelectorAll('[data-sample]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await Api.removeSample(button.dataset.sample);
        await loadSamples();
      } catch (error) { showError(error); }
    });
  });
}

async function loadStyleSources() {
  renderStyleSources(await Api.styleSources());
}

$('rules-files').addEventListener('change', async (event) => {
  if (!event.target.files.length) return;
  busy('Добавляем файлы правил…');
  try {
    renderStyleSources(await Api.uploadRules(event.target.files));
    toast('Правила добавлены — они обязательны при каждой правке');
  } catch (error) { showError(error); } finally { idle(); event.target.value = ''; }
});

$('sample-files').addEventListener('change', async (event) => {
  if (!event.target.files.length) return;
  busy('Загружаем образцы…');
  try {
    await Api.uploadSamples(event.target.files);
    await loadSamples();
    toast('Образцы загружены. Нажмите «Изучить формат».');
  } catch (error) { showError(error); } finally { idle(); event.target.value = ''; }
});

$('learn-format').addEventListener('click', async () => {
  busy('Разбираем образцы и запоминаем формат…');
  try {
    const data = await Api.learnFormat($('learn-with-model').checked);
    renderStyleSources(data);
    toast(`Формат изучен по ${data.profile.documents} документам — дальше применяется сам`);
  } catch (error) { showError(error); } finally { idle(); }
});

$('use-derived').addEventListener('change', async (event) => {
  try {
    renderStyleSources(await Api.useDerived(event.target.checked));
  } catch (error) { showError(error); }
});

$('forget-format').addEventListener('click', async () => {
  if (!confirm('Забыть изученный формат? Образцы останутся на месте.')) return;
  try {
    renderStyleSources(await Api.forgetFormat());
    toast('Формат забыт');
  } catch (error) { showError(error); }
});

/* ---------- шаг 3: поиск документа ---------- */

function selectDoc(path, title, heading) {
  state.doc = { path, title: title || path };
  $('chosen-doc').textContent = `Выбран документ: ${state.doc.title} (${path})`;
  $('generate').disabled = false;
  document.querySelectorAll('.candidate').forEach((node) => {
    node.classList.toggle('candidate--active', node.dataset.path === path);
  });
  loadOutline(path, heading);
}

async function loadOutline(path, heading) {
  const select = $('section-select');
  const hint = $('section-hint');
  select.disabled = true;
  hint.textContent = '';
  select.innerHTML = '<option value="">весь документ целиком</option>';
  try {
    const data = await Api.outline(path);
    select.innerHTML = '<option value="">весь документ целиком</option>' +
      data.sections.map((section) => {
        const indent = '— '.repeat(Math.max(0, section.level - 1));
        return `<option value="${section.index}">${escapeHtml(indent + section.title)}</option>`;
      }).join('');
    select.disabled = false;

    // Поиск уже нашёл наиболее похожий раздел — подставляем его, но не навязываем.
    const match = heading && data.sections.find((section) => section.path === heading && section.level > 1);
    if (match) {
      select.value = String(match.index);
      hint.textContent = `раздел подставлен поиском — можно поменять`;
    }
  } catch (error) {
    select.disabled = true;
  }
}

function renderCandidates(candidates) {
  const box = $('candidates');
  if (!candidates.length) {
    box.innerHTML = '<p class="muted">Ничего не нашлось. Постройте индекс или уточните описание.</p>';
    return;
  }
  box.innerHTML = candidates.map((item) => `
    <div class="candidate" data-path="${escapeHtml(item.path)}" data-title="${escapeHtml(item.title)}" data-heading="${escapeHtml(item.heading || '')}">
      <div class="candidate__title">${escapeHtml(item.title)}</div>
      <div class="candidate__score">${item.relevance}%<div class="bar"><span style="width:${item.relevance}%"></span></div></div>
      <div class="candidate__path mono">${escapeHtml(item.path)}${item.heading ? ' · ' + escapeHtml(item.heading) : ''}</div>
      <div class="candidate__snippet">${escapeHtml(item.snippet)}</div>
    </div>`).join('');
  box.querySelectorAll('.candidate').forEach((node) => {
    node.addEventListener('click', () => selectDoc(node.dataset.path, node.dataset.title, node.dataset.heading));
  });
  selectDoc(candidates[0].path, candidates[0].title, candidates[0].heading);
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

function countMarks(text) {
  const unclear = (text.match(/\[уточнить[^\]]*\]/g) || []).length;
  const disputed = (text.match(/\[спорно:[^\]]*\]/g) || []).length;
  const parts = [];
  if (unclear) parts.push(`пометок [уточнить]: ${unclear}`);
  if (disputed) parts.push(`спорных мест: ${disputed}`);
  $('marks-info').textContent = parts.join(' · ');
  return unclear + disputed;
}


/* ---------- превью документа с подсветкой изменений ---------- */

/* Служебные символы отмечают новый текст: они переживают разметку Markdown
   и в самом конце превращаются в теги подсветки. */
const MARK_OPEN = String.fromCharCode(1);
const MARK_CLOSE = String.fromCharCode(2);

function markedText(parts, marked) {
  return parts
    .filter((part) => part.type !== (marked === 'added' ? 'removed' : 'added'))
    .map((part) => (part.type === marked ? MARK_OPEN + part.text + MARK_CLOSE : part.text))
    .join('');
}

function inlineMarkdown(text) {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" rel="noreferrer">$1</a>');
}

/* Небольшой конвертер Markdown → HTML: заголовки, списки, код, цитаты, таблицы.
   Никаких библиотек — всё локально и без обращений в сеть. */
function renderMarkdownBlock(raw) {
  const text = escapeHtml(raw);
  const lines = text.split('\n');

  if (lines[0].trimStart().startsWith('```')) {
    const last = lines[lines.length - 1].trimStart().startsWith('```') ? -1 : lines.length;
    return `<pre class="preview__code"><code>${lines.slice(1, last).join('\n')}</code></pre>`;
  }

  if (lines.length > 1 && lines.every((line) => line.trim().startsWith('|'))) {
    const rows = lines
      .filter((line) => !/^\s*\|[\s:|-]+\|\s*$/.test(line))
      .map((line) => line.trim().replace(/^\||\|$/g, '').split('|'));
    const [head, ...body] = rows;
    return `<div class="preview__tablewrap"><table class="preview__table">
      <thead><tr>${head.map((cell) => `<th>${inlineMarkdown(cell.trim())}</th>`).join('')}</tr></thead>
      <tbody>${body.map((row) => `<tr>${row.map((cell) => `<td>${inlineMarkdown(cell.trim())}</td>`).join('')}</tr>`).join('')}</tbody>
    </table></div>`;
  }

  if (lines.every((line) => /^\s*[-*+]\s+/.test(line) || line.trim() === '')) {
    const items = lines.filter((line) => line.trim()).map((line) => line.replace(/^\s*[-*+]\s+/, ''));
    return `<ul class="preview__list">${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join('')}</ul>`;
  }

  if (lines.every((line) => /^\s*\d+[.)]\s+/.test(line) || line.trim() === '')) {
    const items = lines.filter((line) => line.trim()).map((line) => line.replace(/^\s*\d+[.)]\s+/, ''));
    return `<ol class="preview__list">${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join('')}</ol>`;
  }

  if (lines.every((line) => line.trimStart().startsWith('>') || line.trim() === '')) {
    const body = lines.map((line) => line.replace(/^\s*>\s?/, '')).join('<br>');
    return `<blockquote class="preview__quote">${inlineMarkdown(body)}</blockquote>`;
  }

  const rendered = lines.map((line) => {
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (!heading) return inlineMarkdown(line);
    const level = Math.min(6, heading[1].length);
    return `<h${level} class="preview__h preview__h--${level}">${inlineMarkdown(heading[2])}</h${level}>`;
  });
  const onlyHeadings = rendered.every((line) => line.startsWith('<h'));
  return onlyHeadings ? rendered.join('') : `<p class="preview__p">${rendered.join('<br>')}</p>`;
}

function applyMarks(html) {
  return html
    .split(MARK_OPEN).join('<ins class="preview__ins">')
    .split(MARK_CLOSE).join('</ins>');
}

function renderPreview(diff) {
  const showRemoved = $('show-removed').checked;
  const html = diff.blocks.map((block) => {
    if (block.type === 'equal') {
      return renderMarkdownBlock(block.new);
    }
    if (block.type === 'insert') {
      return applyMarks(renderMarkdownBlock(MARK_OPEN + block.new + MARK_CLOSE));
    }
    if (block.type === 'delete') {
      if (!showRemoved) return '';
      return `<div class="preview__removed"><span class="preview__label">удалено</span>
        <del>${escapeHtml(block.old)}</del></div>`;
    }
    const parts = (block.inline && block.inline.new) || [{ type: 'same', text: block.new }];
    return applyMarks(renderMarkdownBlock(markedText(parts, 'added')));
  }).join('');

  $('preview-view').innerHTML = html || '<p class="muted">Документ пуст.</p>';
}

function renderChecks(checks) {
  const box = $('checks-notes');
  if (!checks) { box.hidden = true; return; }
  const violations = checks.violations || [];
  const summary = checks.summary || {};
  box.hidden = false;
  if (!violations.length) {
    box.innerHTML = '<div class="review__ok">Автопроверка оформления и формулировок: нарушений нет.</div>';
    return;
  }
  const fixed = checks.fix_iterations
    ? ` Модель уже исправила часть нарушений (заходов: ${checks.fix_iterations}).`
    : '';
  box.innerHTML = `<div class="review__title">Автопроверка: ${summary.errors || 0} ошибок,
      ${summary.warnings || 0} предупреждений.${fixed}</div>
    <ul class="review__list">${violations.slice(0, 30).map((item) => `
      <li${item.severity === 'error' ? ' class="review__err"' : ''}>
        <span class="review__tag">${escapeHtml(item.source)}/${escapeHtml(item.rule)}</span>
        ${item.line ? `строка ${item.line}: ` : ''}${escapeHtml(item.message)}
      </li>`).join('')}</ul>`;
}

function renderWarnings(warnings) {
  $('warnings').innerHTML = (warnings || [])
    .map((text) => `<div class="warning">${escapeHtml(text)}</div>`).join('');
}

/* ---------- обработчики ---------- */

$('save-config').addEventListener('click', async () => {
  busy('Сохраняем настройки…');
  try {
    await Api.saveConfig({
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
    const index = await Api.reindex();
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
    const data = await Api.uploadStyleGuide(file);
    $('guide-text').value = data.content;
    $('guide-info').textContent = `Гайд подключён: ${data.path}`;
    toast('Гайд загружен');
  } catch (error) { showError(error); } finally { idle(); event.target.value = ''; }
});

$('save-guide').addEventListener('click', async () => {
  busy('Сохраняем гайд…');
  try {
    await Api.saveStyleGuide($('guide-text').value);
    await loadGuide();
    toast('Гайд сохранён');
  } catch (error) { showError(error); } finally { idle(); }
});

$('find-doc').addEventListener('click', async () => {
  const query = $('change-text').value.trim();
  if (!query) { toast('Опишите, что изменилось', true); return; }
  busy('Ищем подходящий документ…');
  try {
    const data = await Api.search(query);
    renderCandidates(data.candidates);
  } catch (error) { showError(error); } finally { idle(); }
});

$('manual-doc').addEventListener('change', (event) => {
  if (event.target.value) {
    selectDoc(event.target.value, event.target.selectedOptions[0].textContent);
  }
});

function setResultButtons(enabled) {
  ['save-edits', 'download', 'apply', 'review'].forEach((id) => { $(id).disabled = !enabled; });
}

function showTab(view) {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.classList.toggle('tab--active', tab.dataset.view === view);
  });
  $('result-pane').hidden = view !== 'result';
  $('preview-pane').hidden = view !== 'preview';
  $('diff-view').hidden = view !== 'diff';
}

function finishResult(data) {
  state.result = data;
  renderWarnings((data.warnings || []).concat(data.style_guide_used ? [] : ['Гайд по стилю пуст — правки сделаны без него.']));
  renderDiff(data.diff);
  renderPreview(data.diff);
  renderChecks(data.checks);
  $('result-view').value = data.updated;
  countMarks(data.updated);
  $('result-file').textContent = data.result_path;
  setResultButtons(true);
  showTab('diff');
  if (!data.diff.has_changes) toast('Модель ничего не изменила — уточните описание правки', true);
  else toast('Готово. Оригинал не тронут, результат сохранён отдельным файлом.');
}

/* Потоковая генерация: текст появляется по мере того, как модель его пишет. */
async function generateStreaming(body) {
  const startedAt = Date.now();
  let text = '';
  let finished = null;

  const showProgress = () => {
    const seconds = Math.round((Date.now() - startedAt) / 1000);
    const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    $('marks-info').textContent = `модель пишет… ${clock}, символов: ${text.length}`;
  };

  const streamed = await Api.generateStream(body, (event) => {
    if (event.type === 'start') {
      $('step-diff').hidden = false;
      $('result-view').value = '';
      $('diff-view').innerHTML = '';
      $('diff-stats').textContent = '';
      renderWarnings(event.warnings || []);
      setResultButtons(false);
      $('review-notes').hidden = true;
      $('checks-notes').hidden = true;
      showTab('result');
      $('step-diff').scrollIntoView({ behavior: 'smooth' });
      idle();
    } else if (event.type === 'chunk') {
      text += event.text;
      $('result-view').value = text;
      $('result-view').scrollTop = $('result-view').scrollHeight;
      showProgress();
    } else if (event.type === 'error') {
      const error = new Error(event.error);
      error.hint = event.hint;
      throw error;
    } else if (event.type === 'done') {
      finished = event;
    }
  });

  if (!streamed) return false; // браузер не умеет потоки — вызывающий сходит обычным запросом
  if (!finished) throw new Error('Поток оборвался, результат не получен. Повторите запрос.');
  finishResult(finished);
  await loadResults();
  return true;
}

$('generate').addEventListener('click', async () => {
  const change = $('change-text').value.trim();
  if (!state.doc) { toast('Сначала выберите документ', true); return; }
  if (!change) { toast('Опишите, что изменилось', true); return; }

  const sectionValue = $('section-select').value;
  const body = { doc_path: state.doc.path, change_description: change };
  if (sectionValue !== '') body.section_index = Number(sectionValue);

  busy(sectionValue === ''
    ? 'Модель обновляет документ целиком. Сейчас начнёт писать…'
    : 'Модель обновляет выбранный раздел. Сейчас начнёт писать…');
  $('generate').disabled = true;
  try {
    const streamed = await generateStreaming(body);
    if (!streamed) {
      const data = await Api.generate(body);
      finishResult(data);
      await loadResults();
    }
  } catch (error) {
    showError(error);
    setResultButtons(true);
  } finally {
    idle();
    $('marks-info').textContent = state.result ? $('marks-info').textContent : '';
    if (state.result) countMarks(state.result.updated);
    $('generate').disabled = false;
  }
});

$('show-removed').addEventListener('change', () => {
  if (state.result) renderPreview(state.result.diff);
});

$('only-changes').addEventListener('change', (event) => {
  $('diff-view').classList.toggle('diff--only-changes', event.target.checked);
});

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => showTab(tab.dataset.view));
});

$('save-edits').addEventListener('click', async () => {
  if (!state.result) return;
  busy('Сохраняем правки и пересчитываем различия…');
  try {
    const data = await Api.saveResult(
      state.result.doc_path, state.result.result_file, $('result-view').value
    );
    state.result = { ...state.result, updated: data.updated, diff: data.diff };
    renderDiff(data.diff);
    renderPreview(data.diff);
    renderWarnings(data.warnings);
    countMarks(data.updated);
    await loadResults();
    toast('Правки сохранены, сравнение пересчитано');
  } catch (error) { showError(error); } finally { idle(); }
});

function renderReview(notes) {
  const box = $('review-notes');
  box.hidden = false;
  if (!notes.length) {
    box.innerHTML = '<div class="review__ok">Модель не нашла нарушений гайда.</div>';
    return;
  }
  box.innerHTML = `<div class="review__title">Замечания по гайду (${notes.length}):</div>
    <ul class="review__list">${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join('')}</ul>`;
}

$('review').addEventListener('click', async () => {
  if (!state.result) return;
  busy('Модель сверяет текст с гайдом…');
  try {
    const data = await Api.review($('result-view').value || state.result.updated);
    renderReview(data.notes);
    toast(data.notes.length ? `Замечаний по гайду: ${data.notes.length}` : 'Нарушений гайда не найдено');
  } catch (error) { showError(error); } finally { idle(); }
});

$('download').addEventListener('click', () => {
  if (!state.result) return;
  window.location.href = Api.downloadUrl(state.result.result_file);
});

$('apply').addEventListener('click', async () => {
  if (!state.result) return;
  const ok = confirm(`Заменить оригинал ${state.result.doc_path} обновлённой версией?\nКопия исходного файла останется рядом (.bak-…).`);
  if (!ok) return;
  busy('Записываем в оригинал…');
  try {
    const data = await Api.apply(state.result.doc_path, state.result.result_file);
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
    await loadStyleSources();
    await loadSamples();
    await loadResults();
  } catch (error) { showError(error); }
})();
