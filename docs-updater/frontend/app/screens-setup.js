/* Настройка сервиса: папка и модели, правила оформления, правила портала. */
(function () {

const { H, html, C, TAG, STATUS, severityTone, Card, CardHead, Body, Row, Stack, PageTitle,
        Note, Muted, Block, useAsync, useElapsed, readValue, plural, fileName, useState } = window.UI;


/* Загрузка файлов делается компонентом дизайн-системы: он же показывает список и прогресс.
   Uploader отдаёт { file, fileList }; настоящий файл лежит в originFileObj. */
function pickFiles(info) {
  const items = (info && info.fileList) || [];
  return items.map((item) => item.originFileObj || item).filter(Boolean);
}

/* --- настройки и индекс ----------------------------------------------------- */

function ScreenSettings({ app }) {
  const status = app.status;
  const config = (status.data || {}).config || {};
  const index = (status.data || {}).index || {};
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState(null);
  const elapsed = useElapsed(!!busy);

  const values = form || {
    docs_dir: config.docs_dir_raw || '',
    style_guide: config.style_guide_raw || '',
    generation_model: config.generation_model || '',
    embedding_model: config.embedding_model || '',
  };
  const set = (key) => (value) => setForm({ ...values, [key]: readValue(value) });

  const run = (name, action) => {
    setBusy(name); setMessage(null);
    action()
      .then((data) => { setBusy(''); setMessage({ ok: true, data }); app.reloadStatus(); })
      .catch((error) => { setBusy(''); setMessage({ ok: false, error }); });
  };

  return html`
    <${Stack} gap=${16}>
      <${PageTitle} title="Настройки и индекс"
        subtitle="Где лежат ваши документы, какие модели использовать и что уже прочитано." />

      <${Block} state=${status.state === 'ready' ? 'ready' : status.state} error=${status.error} onRetry=${app.reloadStatus}>
        <${Stack} gap=${16}>
          <${Card}>
            <${CardHead} title="Откуда брать документы" subtitle="Путь можно указать коротко (data/docs) или полностью (/Users/…/docs)" />
            <${Body}>
              <${H.Field} label="Папка с документами (.md)"
                description=${config.docs_dir_exists ? `Папка найдена: ${config.docs_dir}` : `Папки нет по адресу: ${config.docs_dir}`}
                control=${html`<${H.Textbox} value=${values.docs_dir} onChange=${set('docs_dir')} placeholder="data/docs" />`} />
              <${H.Field} label="Файл с правилами оформления (.md)"
                description=${config.style_guide_exists ? `Файл найден: ${config.style_guide}` : `Файла нет по адресу: ${config.style_guide}`}
                control=${html`<${H.Textbox} value=${values.style_guide} onChange=${set('style_guide')} placeholder="data/styleguide.md" />`} />
              <${Row}>
                <${H.Field} label="Модель генерации"
                  control=${html`<${H.Textbox} value=${values.generation_model} onChange=${set('generation_model')} />`} />
                <${H.Field} label="Модель поиска"
                  control=${html`<${H.Textbox} value=${values.embedding_model} onChange=${set('embedding_model')} />`} />
              <//>
              <${Row}>
                <${H.Button} mode="primary" size="small" text="Сохранить настройки"
                  loading=${busy === 'config'} onClick=${() => run('config', () => Api.saveConfig(values))} />
                <${Muted}>Модели работают по очереди, чтобы не занимать всю память. Держим в памяти: ${config.keep_alive || '5m'}<//>
              <//>
            <//>
          <//>

          <${Card}>
            <${CardHead} title="Индекс" subtitle="Список документов, по которому сервис ищет нужный" />
            <${Body}>
              <${Row} gap=${28}>
                <${Stack} gap=${2}>
                  <${Muted}>Файлов .md в папке<//>
                  <span style=${{ fontSize: '20px', fontWeight: 600 }}>${(status.data || {}).markdown_files || 0}</span>
                <//>
                <${Stack} gap=${2}>
                  <${Muted}>Документов прочитано<//>
                  <span style=${{ fontSize: '20px', fontWeight: 600 }}>${index.documents_count || 0}</span>
                <//>
                <${Stack} gap=${2}>
                  <${Muted}>Разделов найдено<//>
                  <span style=${{ fontSize: '20px', fontWeight: 600 }}>${index.sections_count || 0}</span>
                <//>
              <//>
              ${!index.exists ? html`
                <${Block} state="empty" empty=${{ title: 'Документы ещё не прочитаны',
                  description: 'Без этого поиск по описанию не работает.' }} />` : null}
              ${index.exists && index.documents_count !== (status.data || {}).markdown_files ? html`
                <${Note} tone="warn">
                  В папке файлов больше, чем прочитано. Стоит прочитать заново.
                <//>` : null}
              <${Row}>
                <${H.Button} mode="primary" size="small" text="Прочитать документы"
                  loading=${busy === 'reindex'} onClick=${() => run('reindex', Api.reindex)} />
                <${H.Button} mode="secondary" size="small" text="Составить описания документов"
                  loading=${busy === 'map'} onClick=${() => run('map', Api.buildMap)} />
                ${busy ? html`<${Muted}>идёт ${elapsed}<//>` : null}
              <//>
              ${message && message.ok ? html`
                <${H.SectionMessage} mode="success" title="Готово">
                  ${message.data && message.data.sections_count
                    ? `Прочитано документов: ${message.data.documents_count}, разделов: ${message.data.sections_count}.`
                    : 'Операция завершена.'}
                <//>` : null}
              ${message && !message.ok ? html`<${Block} state="error" error=${message.error} />` : null}
            <//>
          <//>
        <//>
      <//>
    <//>`;
}

/* --- правила оформления ----------------------------------------------------- */

function FileList({ items, onRemove, emptyText }) {
  if (!items.length) return html`<${Muted}>${emptyText}<//>`;
  return html`
    <${Stack} gap=${6}>
      ${items.map((item) => html`
        <${Row} key=${item.file} style=${{ justifyContent: 'space-between', padding: '6px 0',
                                           borderBottom: '1px solid ' + C.line }}>
          <span style=${{ fontSize: '13px' }}>${item.file}</span>
          <${Row} gap=${8}>
            <${Muted}>${item.chars || 0} симв.<//>
            ${onRemove ? html`<${H.Button} mode="tertiary" size="small" text="Убрать"
              onClick=${() => onRemove(item.file)} />` : null}
          <//>
        <//>`)}
    <//>`;
}

function ScreenRules({ app }) {
  const guide = useAsync(() => Api.styleGuide(), [app.product]);
  const sources = useAsync(() => Api.styleSources(), [app.product]);
  const samples = useAsync(() => Api.samples(), [app.product]);
  const [text, setText] = useState(null);
  const [busy, setBusy] = useState('');
  const [learned, setLearned] = useState(null);
  const [importUrl, setImportUrl] = useState('');
  const [imported, setImported] = useState({ state: 'idle' });
  const [useModel, setUseModel] = useState(true);
  const elapsed = useElapsed(!!busy);

  const guideText = text === null ? ((guide.data || {}).content || '') : text;
  const derived = ((sources.data || {}).derived) || {};

  const upload = (files, uploader, after) => {
    if (!files || !files.length) return;
    setBusy('upload');
    uploader(files).then(() => { setBusy(''); after(); }).catch(() => setBusy(''));
  };

  const learn = () => {
    setBusy('learn'); setLearned(null);
    Api.learnFormat(useModel)
      .then((data) => { setBusy(''); setLearned(data); sources.reload(); })
      .catch((error) => { setBusy(''); setLearned({ error }); });
  };

  const doImport = (save) => {
    setImported({ state: 'loading' });
    const action = save ? Api.importUrl(importUrl, 'samples', null) : Api.importPreview(importUrl);
    action
      .then((data) => { setImported({ state: 'ready', data, saved: save }); if (save) samples.reload(); })
      .catch((error) => setImported({ state: 'error', error }));
  };

  return html`
    <${Stack} gap=${16}>
      <${PageTitle} title="Правила оформления"
        subtitle="Правила можно задать тремя способами. Они дополняют друг друга." />

      <${Card}>
        <${CardHead} title="Основные правила оформления" subtitle="Эти правила сервис соблюдает всегда" />
        <${Body}>
          <${Block} state=${guide.state === 'ready' ? 'ready' : guide.state} error=${guide.error} onRetry=${guide.reload}>
            <${Stack} gap=${12}>
              <${H.Textbox.Textarea} value=${guideText} rows=${10} autoSize=${false}
                onChange=${(value) => setText(readValue(value))}
                placeholder="Как писать и оформлять документы…" />
              <${Row}>
                <${H.Button} mode="primary" size="small" text="Сохранить правила" loading=${busy === 'guide'}
                  onClick=${() => { setBusy('guide'); Api.saveStyleGuide(guideText)
                    .then(() => { setBusy(''); guide.reload(); }).catch(() => setBusy('')); }} />
                <${H.Field} label="Загрузить файл с правилами"
                  description="Один файл .md — он заменит текст выше"
                  control=${html`<${H.Uploader} size="small" manual=${true} maxCount=${1}
                    onChange=${(info) => upload(pickFiles(info), (files) => Api.uploadStyleGuide(files[0]),
                      () => { setText(null); guide.reload(); })} />`} />
              <//>
            <//>
          <//>
        <//>
      <//>

      <${Card}>
        <${CardHead} title="Дополнительные файлы с правилами"
          subtitle="Файлов может быть сколько угодно" />
        <${Body}>
          <${Block} state=${sources.state === 'ready' ? 'ready' : sources.state} error=${sources.error} onRetry=${sources.reload}>
            <${Stack} gap=${12}>
              <${FileList} items=${((sources.data || {}).guides) || []}
                emptyText="Дополнительных файлов пока нет."
                onRemove=${(file) => Api.removeRules(file).then(sources.reload)} />
              <${Note}>Файл пропадёт из списка, но останется на диске.<//>
              <${H.Field} label="Добавить файлы с правилами"
                description="Можно выбрать сразу несколько файлов .md"
                control=${html`<${H.Uploader} size="small" manual=${true}
                  onChange=${(info) => upload(pickFiles(info), Api.uploadRules, sources.reload)} />`} />
            <//>
          <//>
        <//>
      <//>

      <${Card}>
        <${CardHead} title="Образцы: сервис сам поймёт формат"
          subtitle="Дайте примеры готовых документов или ссылку на статью справки" />
        <${Body}>
          <${Row}>
            <div style=${{ flex: 1, minWidth: '280px' }}>
              <${H.Textbox} value=${importUrl} placeholder="Ссылка на статью справки"
                onChange=${(value) => setImportUrl(readValue(value))} />
            </div>
            <${H.Button} mode="secondary" size="small" text="Показать текст"
              disabled=${!importUrl.trim()} onClick=${() => doImport(false)} />
            <${H.Button} mode="secondary" size="small" text="Сохранить как образец"
              disabled=${!importUrl.trim()} onClick=${() => doImport(true)} />
          <//>
          ${imported.state === 'loading' ? html`<${Block} state="loading" loading=${{ title: 'Читаем страницу' }} />` : null}
          ${imported.state === 'error' ? html`<${Block} state="error" error=${imported.error} />` : null}
          ${imported.state === 'ready' ? html`
            <${Stack} gap=${8}>
              <${H.SectionMessage} mode="success"
                title=${imported.saved ? `Сохранили как образец: ${imported.data.file}` : `Прочитали: ${imported.data.title || 'без заголовка'}`}>
                ${imported.data.chars} символов${(imported.data.meta || {}).article_id ? ` · идентификатор: ${imported.data.meta.article_id}` : ''}
              <//>
              <div style=${{ maxHeight: '240px', overflow: 'auto', border: '1px solid ' + C.border,
                             borderRadius: '8px', padding: '12px', fontSize: '12px', whiteSpace: 'pre-wrap' }}>
                ${(imported.data.markdown || '').slice(0, 4000)}
              </div>
            <//>` : null}

          <${Block} state=${samples.state === 'ready' ? 'ready' : samples.state} error=${samples.error} onRetry=${samples.reload}>
            <${Stack} gap=${12}>
              <${FileList} items=${((samples.data || {}).samples) || []}
                emptyText="Образцов пока нет."
                onRemove=${(file) => Api.removeSample(file).then(samples.reload)} />
              <${Row}>
                <${H.Field} label="Добавить образцы"
                  description="Готовые документы .md, на которые сервис будет равняться"
                  control=${html`<${H.Uploader} size="small" manual=${true}
                    onChange=${(info) => upload(pickFiles(info), Api.uploadSamples, samples.reload)} />`} />
                <${H.Button} mode="primary" size="small" text="Изучить формат"
                  loading=${busy === 'learn'} onClick=${learn} />
                <${H.Checkbox} checked=${useModel} onChange=${() => setUseModel(!useModel)}>
                  попросить модель дописать правила словами
                <//>
                ${busy === 'learn' ? html`<${Muted}>идёт ${elapsed}<//>` : null}
              <//>
            <//>
          <//>

          ${derived.exists ? html`
            <${H.SectionMessage} mode=${((sources.data || {}).use_derived_guide) ? 'success' : 'info'}
              title=${`Формат изучен по образцам${derived.learned_at ? ': ' + derived.learned_at : ''}`}>
              <${Stack} gap=${8}>
                <div>${((sources.data || {}).use_derived_guide) ? 'Сервис применяет его к каждой правке.' : 'Сейчас не применяется.'}</div>
                <${Row}>
                  <${H.Button} mode="secondary" size="small"
                    text=${((sources.data || {}).use_derived_guide) ? 'Выключить' : 'Включить'}
                    onClick=${() => Api.useDerived(!((sources.data || {}).use_derived_guide)).then(sources.reload)} />
                  <${H.Button} mode="tertiary" size="small" text="Забыть формат"
                    onClick=${() => Api.forgetFormat().then(sources.reload)} />
                <//>
              <//>
            <//>` : null}
          ${learned && learned.error ? html`<${Block} state="error" error=${learned.error} />` : null}
        <//>
      <//>
    <//>`;
}

/* --- правила портала -------------------------------------------------------- */

function ScreenPortal({ app }) {
  const rules = useAsync(() => Api.docsConfig(), [app.product]);
  const [sync, setSync] = useState(null);
  const [locales, setLocales] = useState({ state: 'idle' });
  const data = rules.data || {};

  const checkLocales = () => {
    setLocales({ state: 'loading' });
    Api.crosslocale()
      .then((answer) => setLocales({ state: 'ready', data: answer }))
      .catch((error) => setLocales({ state: 'error', error }));
  };

  return html`
    <${Stack} gap=${16}>
      <${PageTitle} title="Правила портала"
        subtitle="Типы статей, свои правила и словарь терминов лежат в папке docs-config. Поменяли файл — поменялись правила." />

      <${Block} state=${rules.state === 'ready' ? 'ready' : rules.state} error=${rules.error} onRetry=${rules.reload}>
        <${Stack} gap=${16}>
          ${(data.errors || []).length ? html`
            <${H.SectionMessage} mode="error" title="Не все файлы правил удалось прочитать">
              ${(data.errors || []).join('; ')}
            <//>` : null}

          <${Card}>
            <${CardHead} title=${`Типы статей · ${(data.types || []).length}`}
              subtitle="У каждого типа свой набор разделов и свои обязательные поля" />
            <${Body}>
              ${(data.types || []).length === 0
                ? html`<${Block} state="empty" empty=${{ title: 'Типы статей не заданы',
                    description: 'Положите файл article-type-schemas.json в папку docs-config.' }} />`
                : html`<${Row} gap=${8}>
                    ${(data.types || []).map((type) => html`
                      <${H.Tag} key=${type.type_id} mode=${type.lintable ? TAG.info : TAG.muted}
                        size="small" readOnly=${true}>
                        ${type.name}${type.lintable ? '' : ' · без текстовой проверки'}
                      <//>`)}
                  <//>`}
              <${Row} gap=${8}>
                <${Muted}>Поколения шаблона:<//>
                ${(data.profiles || []).map((profile) => html`
                  <${H.Tag} key=${profile} mode=${TAG.muted} size="small" readOnly=${true}>${profile}<//>`)}
              <//>
            <//>
          <//>

          <${Card}>
            <${CardHead} title=${`Свои правила · ${(data.kdoc || []).length}`}
              subtitle="Обязательные правила и советы показаны отдельно" />
            <${Body}>
              ${(data.kdoc || []).map((rule) => html`
                <${Row} key=${rule.id} gap=${10} style=${{ justifyContent: 'space-between',
                    padding: '6px 0', borderBottom: '1px solid ' + C.line }}>
                  <${Row} gap=${8}>
                    <${H.Tag} mode=${rule.enabled === false ? TAG.muted : rule.severity === 'error' ? TAG.bad : TAG.warn}
                      size="small" readOnly=${true}>
                      ${rule.enabled === false ? 'выключено' : rule.severity === 'error' ? 'нарушение' : 'совет'}
                    <//>
                    <span style=${{ fontSize: '13px', fontWeight: 600 }}>${rule.id}</span>
                    <${Muted}>${rule.description || ''}<//>
                  <//>
                  <${Muted}>${[...(rule.types || []), ...(rule.profiles || [])].join(', ') || 'все типы'}<//>
                <//>`)}
              ${(data.kdoc || []).length === 0 ? html`<${Muted}>Своих правил пока нет.<//>` : null}
            <//>
          <//>

          <${Card}>
            <${CardHead} title="Глоссарий" subtitle="Один список терминов: и для проверки, и для перевода" />
            <${Body}>
              <${Row} gap=${28}>
                <${Stack} gap=${2}>
                  <${Muted}>Терминов<//>
                  <span style=${{ fontSize: '20px', fontWeight: 600 }}>${(data.glossary || {}).terms || 0}</span>
                <//>
                <${Stack} gap=${2}>
                  <${Muted}>Замен<//>
                  <span style=${{ fontSize: '20px', fontWeight: 600 }}>${(data.glossary || {}).substitutions || 0}</span>
                <//>
                <${Stack} gap=${2}>
                  <${Muted}>Не переводить<//>
                  <span style=${{ fontSize: '13px' }}>${((data.glossary || {}).do_not_translate || []).join(', ') || '—'}</span>
                <//>
              <//>
              <${Row}>
                <${H.Button} mode="secondary" size="small" text="Обновить словарь для проверки терминов"
                  onClick=${() => Api.syncGlossary().then((answer) => setSync({ ok: true, answer }))
                    .catch((error) => setSync({ ok: false, error }))} />
                <${H.Button} mode="secondary" size="small" text="Сравнить версии на разных языках" onClick=${checkLocales} />
              <//>
              ${sync && sync.ok ? html`
                <${H.SectionMessage} mode="success" title="Словарь обновлён">
                  Записано файлов: ${(sync.answer.written || []).length}. Правильных написаний: ${sync.answer.accepted}.
                <//>` : null}
              ${sync && !sync.ok ? html`<${Block} state="error" error=${sync.error} />` : null}
            <//>
          <//>

          ${locales.state !== 'idle' ? html`
            <${Card}>
              <${CardHead} title="Версии на разных языках"
                subtitle="Состав разделов и даты проверяем отдельно: это разные проблемы" />
              <${Body}>
                <${Block} state=${locales.state === 'ready' ? 'ready' : locales.state} error=${locales.error}
                  onRetry=${checkLocales} loading=${{ title: 'Сравниваем версии' }}>
                  ${((locales.data || {}).findings || []).length === 0
                    ? html`<${H.SectionMessage} mode="success" title="Расхождений нет">
                        Разделы и даты во всех версиях совпадают.<//>`
                    : html`<${Stack} gap=${6}>
                        ${((locales.data || {}).findings || []).map((item, index) => html`
                          <${Row} key=${index} gap=${10} style=${{ alignItems: 'flex-start' }}>
                            <${H.Tag} mode=${item.kind === 'structure-mismatch' ? TAG.bad : TAG.warn}
                              size="small" readOnly=${true}>
                              ${item.kind === 'structure-mismatch' ? 'разделы' : 'даты и номера версий'}
                            <//>
                            <span style=${{ fontSize: '13px', flex: 1, minWidth: '240px' }}>${item.message}</span>
                            <${Muted}>${item.path}<//>
                          <//>`)}
                      <//>`}
                <//>
              <//>
            <//>` : null}
        <//>
      <//>
    <//>`;
}

window.SetupScreens = { ScreenSettings, ScreenRules, ScreenPortal };

}());
