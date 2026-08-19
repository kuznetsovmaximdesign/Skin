/* Каркас приложения: боковая навигация, выбор продукта, шаги основного пути и роутинг.
   Данные о состоянии сервиса (Ollama, индекс) живут здесь и раздаются экранам. */

(function start() {
  if (!window.KasperskyHexaUi || !window.React || !window.htm) {
    document.getElementById('no-ds').classList.add('no-ds--show');
    return;
  }

  const { H, html, C, STATUS, Card, CardHead, Body, Row, Stack, Muted, Block,
          useAsync, useState, useEffect, plural, readValue, popupToBody } = window.UI;
  const { ScreenChanged, ScreenUpdate } = window.FlowScreens;
  const { ScreenResult } = window.ResultScreen;
  const { ScreenSettings, ScreenRules, ScreenPortal } = window.SetupScreens;
  const { ScreenArticle, ScreenResults, ScreenMap, ScreenPublications, ScreenAudit } = window.MoreScreens;

  const FLOW = ['changed', 'pick', 'update', 'result'];
  const NAV = [
    { key: 'settings', label: 'Настройки и документы' },
    { key: 'rules', label: 'Правила оформления' },
    { key: 'portal', label: 'Правила портала' },
    { key: 'changed', label: 'Правка документов', flow: true },
    { key: 'article', label: 'Новая статья' },
    { key: 'results', label: 'Сохранённые правки' },
    { key: 'map', label: 'Описания документов' },
    { key: 'publications', label: 'Публикации' },
    { key: 'audit', label: 'Журнал' },
  ];

  function Stepper({ current, go, hasDoc, hasResult }) {
    const steps = [
      { key: 'changed', mark: '1', label: 'Что изменилось', enabled: true },
      { key: 'update', mark: '2', label: 'Правка документа', enabled: hasDoc },
      { key: 'result', mark: '3', label: 'Что получилось', enabled: hasResult },
    ];
    const activeIndex = steps.findIndex((step) => step.key === (current === 'pick' ? 'changed' : current));
    return html`
      <div style=${{ display: 'flex', alignItems: 'center', background: C.surface,
                     border: '1px solid ' + C.border, borderRadius: '12px', padding: '12px 20px' }}>
        ${steps.map((step, index) => html`
          <${React.Fragment} key=${step.key}>
            ${index > 0 ? html`
              <div style=${{ flex: 1, height: '1px', margin: '0 12px',
                             background: index <= activeIndex ? C.accent : C.border }}></div>` : null}
            <div role="button" tabIndex=${0} onClick=${() => step.enabled && go(step.key)}
              style=${{ display: 'flex', alignItems: 'center', gap: '8px',
                        cursor: step.enabled ? 'pointer' : 'not-allowed', opacity: step.enabled ? 1 : 0.55 }}>
              <div style=${{ width: '24px', height: '24px', borderRadius: '50%', flex: 'none',
                             display: 'flex', alignItems: 'center', justifyContent: 'center',
                             fontSize: '12px', fontWeight: 700,
                             background: index === activeIndex ? C.accent : index < activeIndex ? C.accentBg : C.surface,
                             color: index === activeIndex ? '#FFFFFF' : index < activeIndex ? C.accent : C.textMuted,
                             border: index > activeIndex ? '1px solid ' + C.border : 'none' }}>
                ${index < activeIndex ? '✓' : step.mark}
              </div>
              <span style=${{ fontSize: '13px', fontWeight: index === activeIndex ? 600 : 400,
                              color: index === activeIndex ? C.text : C.textSec }}>${step.label}</span>
            </div>
          <//>`)}
      </div>`;
  }

  function Sidebar({ app }) {
    const [filter, setFilter] = useState('');
    const status = app.status.data || {};
    const index = status.index || {};
    const ollama = status.ollama || {};
    const missing = ollama.available && (!ollama.generation_model_installed || !ollama.embedding_model_installed);
    const products = app.products.data || {};
    const options = (products.products || []).map((item) => ({ label: item.name, value: item.id }));
    const visible = NAV.filter((item) => !filter.trim()
      || item.label.toLowerCase().includes(filter.trim().toLowerCase()));

    return html`
      <div style=${{ width: '268px', flex: 'none', boxSizing: 'border-box', padding: '8px 0 8px 8px',
                     display: 'flex', flexDirection: 'column', position: 'sticky', top: 0,
                     alignSelf: 'flex-start', height: '100vh' }}>
        <div style=${{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column',
                       background: C.surface, border: '1px solid ' + C.border, borderRadius: '16px',
                       boxShadow: '0 4px 12px rgba(33,39,47,0.10), 0 2px 4px rgba(33,39,47,0.06)',
                       overflow: 'hidden' }}>
          <div style=${{ padding: '16px', borderBottom: '1px solid ' + C.border,
                         display: 'flex', flexDirection: 'column', gap: '8px' }}>
            ${options.length > 1 ? html`
              <${React.Fragment}>
                <div style=${{ fontSize: '10px', letterSpacing: '0.06em', textTransform: 'uppercase',
                               color: C.textMuted }}>Продукт</div>
                <${H.Select} options=${options} value=${app.product} showSearch=${false}
                  getPopupContainer=${popupToBody}
                  onChange=${(value) => app.setProduct(value)} />
              <//>` : html`
              <div style=${{ fontSize: '13px', fontWeight: 600 }}>
                ${status.product_name || 'Документация'}
              </div>`}
            <div data-testid="index-status">
              <${H.Status} mode=${index.exists ? STATUS.ok : STATUS.warn}
                label=${index.exists ? 'Документы прочитаны' : 'Документы не прочитаны'} />
            </div>
            <span data-testid="index-info" style=${{ fontSize: '12px', color: C.textSec }}>
              ${index.exists
                ? `${index.documents_count} ${plural(index.documents_count, 'документ', 'документа', 'документов')} · ${index.sections_count} ${plural(index.sections_count, 'раздел', 'раздела', 'разделов')}`
                : `Файлов .md в папке: ${status.markdown_files || 0}`}
            </span>
            <div data-testid="ollama-status">
              <${H.Status} mode=${!ollama.available ? STATUS.bad : missing ? STATUS.warn : STATUS.ok}
                label=${!ollama.available ? 'Ollama не отвечает' : missing ? 'Не хватает моделей' : 'Ollama на связи'} />
            </div>
          </div>

          <div style=${{ padding: '12px 12px 8px' }}>
            <${H.Textbox} placeholder="Найти раздел" value=${filter} allowClear=${true}
              onChange=${(value) => setFilter(readValue(value))} />
          </div>

          <div style=${{ padding: '0 8px 8px', display: 'flex', flexDirection: 'column', gap: '2px',
                         overflowY: 'auto', flex: 1, minHeight: 0 }}>
            ${visible.map((item) => {
              const active = item.flow ? FLOW.includes(app.current) : app.current === item.key;
              return html`
                <div key=${item.key} role="button" tabIndex=${0} data-testid=${'nav-' + item.key}
                  onClick=${() => app.go(item.key)}
                  style=${{ padding: '7px 9px', borderRadius: '8px', fontSize: '13px', lineHeight: '18px',
                            cursor: 'pointer', display: 'flex', alignItems: 'center',
                            justifyContent: 'space-between', gap: '8px',
                            background: active ? C.accentBg : 'transparent',
                            color: active ? C.accent : C.text,
                            fontWeight: active ? 600 : 400,
                            borderLeft: active ? '3px solid ' + C.accent : '3px solid transparent' }}>
                  <span>${item.label}</span>
                </div>`;
            })}
            ${visible.length === 0 ? html`<${Muted}>Ничего не найдено<//>` : null}
          </div>
        </div>
      </div>`;
  }

  /* Сообщения, которые нужно видеть на любом экране: без Ollama или моделей
     ничего не сгенерируется, и это не должно выясняться после нажатия кнопки. */
  function GlobalNotices({ app }) {
    const status = app.status.data || {};
    const ollama = status.ollama || {};
    const config = status.config || {};
    if (app.status.state !== 'ready') return null;

    if (!ollama.available) {
      return html`
        <${H.SectionMessage} mode="error" title=${ollama.error || 'Ollama не отвечает'}>
          <${Stack} gap=${8}>
            <div>${ollama.hint || 'Запустите программу Ollama или команду: ollama serve'}</div>
            <div><${H.Button} mode="secondary" size="small" text="Проверить снова"
              loading=${app.status.state === 'loading'} onClick=${app.reloadStatus} /></div>
          <//>
        <//>`;
    }
    const missing = [];
    if (!ollama.generation_model_installed) missing.push(config.generation_model);
    if (!ollama.embedding_model_installed) missing.push(config.embedding_model);
    if (missing.length) {
      return html`
        <${H.SectionMessage} mode="warning"
          title=${`Не хватает моделей: ${missing.join(', ')}`}>
          Выполните в терминале: ${missing.map((model) => `ollama pull ${model}`).join('  ·  ')}
        <//>`;
    }
    return null;
  }

  function App() {
    const [current, setCurrent] = useState('changed');
    const [product, setProduct] = useState('');
    const [description, setDescription] = useState('');
    const [doc, setDoc] = useState(null);
    const [result, setResult] = useState(null);

    const products = useAsync(() => Api.products(), []);
    const status = useAsync(() => Api.status(), [product]);

    useEffect(() => {
      if (products.state === 'ready' && !product && products.data && products.data.default) {
        setProduct(products.data.default);
      }
    }, [products.state]);

    useEffect(() => {
      const refresh = () => { if (!document.hidden) status.reload(); };
      window.addEventListener('focus', refresh);
      document.addEventListener('visibilitychange', refresh);
      return () => {
        window.removeEventListener('focus', refresh);
        document.removeEventListener('visibilitychange', refresh);
      };
    }, [status.reload]);

    const app = {
      current, product, description, doc, result, products, status,
      screenArgs: {},
      go: (key) => setCurrent(key),
      setProduct: (value) => { Api.setProduct(value); setProduct(value); setDoc(null); setResult(null); },
      setDescription,
      selectDoc: (value) => { setDoc(value); setResult(null); },
      setResult,
      reloadStatus: status.reload,
    };

    const screens = {
      changed: ScreenChanged, pick: ScreenChanged, update: ScreenUpdate, result: ScreenResult,
      settings: ScreenSettings, rules: ScreenRules, portal: ScreenPortal, article: ScreenArticle,
      results: ScreenResults, map: ScreenMap, publications: ScreenPublications, audit: ScreenAudit,
    };
    const Screen = screens[current] || ScreenChanged;

    return html`
      <${H.LocalizationProvider} i18n=${H.previewI18n} locale="ru-ru">
        <${H.ThemeProvider} theme="light">
          <div style=${{ display: 'flex', minWidth: '1280px', minHeight: '100vh', background: C.page }}>
            <${Sidebar} app=${app} />
            <div style=${{ flex: 1, minWidth: 0, height: '100vh', overflowY: 'auto',
                           boxSizing: 'border-box' }}>
              <div style=${{ maxWidth: '1180px', margin: '0 auto', padding: '0 32px 56px',
                             display: 'flex', flexDirection: 'column', gap: '20px' }}>
                ${FLOW.includes(current) ? html`
                  <div style=${{ position: 'sticky', top: 0, zIndex: 5, background: C.page,
                                 padding: '8px 0 12px' }}>
                    <${Stepper} current=${current} go=${app.go} hasDoc=${!!doc} hasResult=${!!result} />
                  </div>` : html`<div style=${{ height: '20px' }}></div>`}
                <${GlobalNotices} app=${app} />
                <${Screen} app=${app} />
              </div>
            </div>
          </div>
        <//>
      <//>`;
  }

  ReactDOM.createRoot(document.getElementById('root')).render(html`<${App} />`);
}());
