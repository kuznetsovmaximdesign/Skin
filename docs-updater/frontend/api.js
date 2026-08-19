/* Все обращения к бэкенду собраны здесь.
   Вёрстка и интерфейс (app.js) не знают ни одного URL — так фронтенд легко переделать. */

const Api = (() => {
  // Выбранный продукт подставляется во все запросы: контексты изолированы.
  let currentProduct = '';

  function withProduct(path) {
    if (!currentProduct) return path;
    return path + (path.includes('?') ? '&' : '?') + 'product=' + encodeURIComponent(currentProduct);
  }

  async function request(path, options = {}) {
    const response = await fetch(withProduct(path), options);
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

  const post = (path, body) => request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });

  const put = (path, body) => request(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });

  return {
    setProduct: (value) => { currentProduct = value || ''; },
    getProduct: () => currentProduct,

    products: () => fetch('/api/products').then((response) => response.json()),
    status: () => request('/api/status'),
    saveConfig: (patch) => post('/api/config', patch),

    documents: () => request('/api/documents'),
    outline: (path) => request('/api/outline?path=' + encodeURIComponent(path)),

    styleGuide: () => request('/api/style-guide'),
    saveStyleGuide: (content) => put('/api/style-guide', { content }),
    uploadStyleGuide: (file) => {
      const form = new FormData();
      form.append('file', file);
      return request('/api/style-guide/upload', { method: 'POST', body: form });
    },

    styleSources: () => request('/api/style-sources'),
    uploadRules: (files) => {
      const form = new FormData();
      Array.from(files).forEach((file) => form.append('files', file));
      return request('/api/style-guides/upload', { method: 'POST', body: form });
    },
    removeRules: (file) => request('/api/style-guides?file=' + encodeURIComponent(file), { method: 'DELETE' }),

    importPreview: (url) => post('/api/import/preview', { url }),
    importUrl: (url, target, fileName) =>
      post('/api/import/url', { url, target, file_name: fileName || null }),

    samples: () => request('/api/samples'),
    uploadSamples: (files) => {
      const form = new FormData();
      Array.from(files).forEach((file) => form.append('files', file));
      return request('/api/samples/upload', { method: 'POST', body: form });
    },
    removeSample: (file) => request('/api/samples?file=' + encodeURIComponent(file), { method: 'DELETE' }),
    learnFormat: (useModel) => post('/api/format/learn', { use_model: useModel }),
    useDerived: (enabled) => post('/api/format/use', { enabled }),
    forgetFormat: () => request('/api/format', { method: 'DELETE' }),

    reindex: () => post('/api/reindex'),
    buildMap: () => post('/api/map/build'),
    map: () => request('/api/map'),
    drift: (changeDescription, docPath) =>
      post('/api/drift', { change_description: changeDescription || '', doc_path: docPath || '' }),
    impact: (changeDescription) => post('/api/impact', { change_description: changeDescription }),
    search: (query) => post('/api/search', { query }),

    generate: (body) => post('/api/generate', body),

    proposeChangeset: (body) => post('/api/changeset/propose', body),
    decideEdit: (changesetId, editId, accepted, comment) =>
      post(`/api/changeset/${changesetId}/decide`, { edit_id: editId, accepted, comment: comment || '' }),
    buildChangeset: (changesetId) => post(`/api/changeset/${changesetId}/build`),
    feedback: (docPath) => request('/api/feedback?doc_path=' + encodeURIComponent(docPath || '')),

    /* Потоковая генерация: onEvent получает события start / chunk / done.
       Возвращает false, если браузер не умеет читать поток — тогда вызывающий
       код может сходить обычным запросом. */
    generateStream: async (body, onEvent) => {
      const response = await fetch('/api/generate/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        let data = null;
        try { data = await response.json(); } catch (e) { data = null; }
        const error = new Error((data && (data.error || data.detail)) || `Ошибка ${response.status}`);
        error.hint = data && data.hint;
        throw error;
      }
      if (!response.body || !response.body.getReader) return false;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (line.trim()) onEvent(JSON.parse(line));
        }
      }
      if (buffer.trim()) onEvent(JSON.parse(buffer));
      return true;
    },

    review: (content) => post('/api/review', { content }),

    newArticle: (body) => post('/api/article/new', body),
    languageVersions: (docPath) => request('/api/languages?doc_path=' + encodeURIComponent(docPath)),
    cascade: (docPath, content, targets) =>
      post('/api/cascade', { doc_path: docPath, content: content || null, targets: targets || null }),

    publishPreview: (body) => post('/api/publish/preview', body),
    publish: (body) => post('/api/publish', body),
    publications: () => request('/api/publications'),

    docsConfig: () => request('/api/docs-config'),
    syncGlossary: () => post('/api/docs-config/sync-glossary'),
    crosslocale: () => request('/api/crosslocale'),
    saveResult: (docPath, resultFile, content) =>
      post('/api/results/save', { doc_path: docPath, result_file: resultFile, content }),
    results: () => request('/api/results'),
    apply: (docPath, resultFile) => post('/api/apply', { doc_path: docPath, result_path: resultFile }),
    downloadUrl: (file) => '/api/download?file=' + encodeURIComponent(file),
  };
})();
