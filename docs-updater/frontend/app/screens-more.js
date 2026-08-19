/* Остальные экраны: новая статья, сохранённые результаты, карта документов,
   публикации и журнал. */
(function () {

const { H, html, C, TAG, STATUS, Card, CardHead, Body, Row, Stack, PageTitle,
        Note, Muted, Block, useAsync, useElapsed, readValue, popupToBody, plural, fileName, useState } = window.UI;

/* --- новая статья по шаблону ------------------------------------------------ */

function ScreenArticle({ app }) {
  const rules = useAsync(() => Api.docsConfig(), [app.product]);
  const [title, setTitle] = useState('');
  const [requirements, setRequirements] = useState('');
  const [typeId, setTypeId] = useState('');
  const [profile, setProfile] = useState('');
  const [useExamples, setUseExamples] = useState(true);
  const [draft, setDraft] = useState({ state: 'idle' });
  const elapsed = useElapsed(draft.state === 'loading');
  const data = rules.data || {};

  const types = [{ label: 'определить по структуре', value: '' }]
    .concat((data.types || []).map((type) => ({ label: type.name, value: type.type_id })));
  const profiles = (data.profiles || []).map((item) => ({ label: item, value: item }));
  const plan = (data.types || []).find((type) => type.type_id === typeId);

  const create = () => {
    setDraft({ state: 'loading' });
    Api.newArticle({ title, requirements, type_id: typeId || null, profile: profile || null,
                     use_examples: useExamples })
      .then((answer) => { setDraft({ state: 'ready', data: answer }); app.setResult({
        doc_path: answer.result_file, result_file: answer.result_file, result_path: answer.result_path,
        updated: answer.text, original: '', mode: 'новая статья', checks: answer.checks,
        diff: { blocks: [], stats: {} } }); })
      .catch((error) => setDraft({ state: 'error', error }));
  };

  const marks = draft.state === 'ready' ? (draft.data.text.match(/\[уточнить\]/g) || []).length : 0;

  return html`
    <${Stack} gap=${16}>
      <${PageTitle} title="Новая статья по шаблону"
        subtitle="Разделы возьмём из шаблона. Факты — только из требований: чего нет, отметим как [уточнить]." />

      <${Card}>
        <${CardHead} title="О чём статья" subtitle="От типа зависит, какие разделы будут в статье" />
        <${Body}>
          <${H.Field} label="Название статьи"
            control=${html`<${H.Textbox} value=${title} onChange=${(value) => setTitle(readValue(value))}
              placeholder="Настройка защиты от файловых угроз" />`} />
          <${Row}>
            <div style=${{ minWidth: '260px' }}>
              <${H.Field} label="Тип статьи"
                control=${html`<${H.Select} value=${typeId} options=${types} getPopupContainer=${popupToBody}
                  onChange=${(value) => setTypeId(readValue(value))} />`} />
            </div>
            <div style=${{ minWidth: '220px' }}>
              <${H.Field} label="Поколение шаблона"
                control=${html`<${H.Select} value=${profile} options=${profiles} getPopupContainer=${popupToBody}
                  onChange=${(value) => setProfile(readValue(value))} />`} />
            </div>
          <//>
          ${plan ? html`
            <${Note}>Соберём разделы: ${(plan.required_sections || []).join(' · ') || 'по общему шаблону продукта'}<//>` : null}
          <${H.Field} label="Что должно быть в статье"
            description="Сервис ничего не выдумывает: чего нет здесь, не будет и в статье"
            control=${html`<${H.Textbox.Textarea} value=${requirements} rows=${8} autoSize=${false}
              onChange=${(value) => setRequirements(readValue(value))}
              placeholder="Что делает функция, для кого она, какие ограничения и значения по умолчанию…" />`} />
          <${Row}>
            <${H.Button} mode="primary" size="small" text="Собрать черновик"
              loading=${draft.state === 'loading'} disabled=${!title.trim() || !requirements.trim()}
              onClick=${create} />
            <${H.Checkbox} checked=${useExamples} onChange=${() => setUseExamples(!useExamples)}>
              писать в стиле похожей статьи
            <//>
            ${draft.state === 'loading' ? html`<${Muted}>идёт ${elapsed}<//>` : null}
          <//>
        <//>
      <//>

      ${draft.state === 'error' ? html`<${Block} state="error" error=${draft.error} onRetry=${create} />` : null}

      ${draft.state === 'ready' ? html`
        <${Card}>
          <${CardHead} title="Черновик готов"
            subtitle=${`Тип: ${draft.data.type_id || 'определён по структуре'} · профиль: ${draft.data.profile || '—'} · файл: ${draft.data.result_file}`}
            right=${html`<${H.Button} mode="secondary" size="small" text="Открыть результат"
              onClick=${() => app.go('result')} />`} />
          <${Body}>
            <${Row} gap=${12}>
              <${H.Status} mode=${marks ? STATUS.warn : STATUS.ok}
                label=${marks ? `${marks} ${plural(marks, 'место надо уточнить', 'места надо уточнить', 'мест надо уточнить')}`
                              : 'данных хватило на все разделы'} />
              <${Muted}>Разделы: ${(draft.data.sections || []).join(' · ')}<//>
            <//>
            <div style=${{ maxHeight: '420px', overflow: 'auto', border: '1px solid ' + C.border,
                           borderRadius: '8px', padding: '14px 16px', fontSize: '13px',
                           lineHeight: '20px', whiteSpace: 'pre-wrap' }}>
              ${draft.data.text}
            </div>
          <//>
        <//>` : null}
    <//>`;
}

/* --- сохранённые результаты ------------------------------------------------- */

function ScreenResults({ app }) {
  const results = useAsync(() => Api.results(), [app.product]);
  const items = ((results.data || {}).results) || [];
  return html`
    <${Stack} gap=${16}>
      <${PageTitle} title="Сохранённые результаты"
        subtitle="Каждая правка сохраняется отдельным файлом. Ничего не потеряется." />
      <${Card}>
        <${Body}>
          <${Block} state=${results.state === 'ready' && items.length === 0 ? 'empty'
              : results.state === 'ready' ? 'ready' : results.state}
            error=${results.error} onRetry=${results.reload}
            empty=${{ title: 'Правок пока нет', description: 'Они появятся, когда вы поправите первый документ.' }}>
            <${H.Table} pagination=${false} dataSource=${items.map((item, index) => ({ ...item, key: index }))}
              columns=${[
                { title: 'Файл с правкой', dataIndex: 'file',
                  render: (value) => html`<span style=${{ fontSize: '13px' }}>${value}</span>` },
                { title: 'Документ', dataIndex: 'doc_path' },
                { title: 'Что меняли', dataIndex: 'change_description',
                  render: (value) => html`<${Muted}>${(value || '').slice(0, 120)}<//>` },
                { title: 'Режим', dataIndex: 'mode', width: 120 },
                { title: 'Сохранён', dataIndex: 'saved_at', width: 140 },
                { title: '', dataIndex: 'file', width: 120,
                  render: (value) => html`<${H.Button} mode="tertiary" size="small" text="Скачать"
                    onClick=${() => window.open(Api.downloadUrl(value), '_blank')} />` },
              ]} />
          <//>
        <//>
      <//>
    <//>`;
}

/* --- карта документов ------------------------------------------------------- */

function ScreenMap({ app }) {
  const map = useAsync(() => Api.map(), [app.product]);
  const [busy, setBusy] = useState(false);
  const elapsed = useElapsed(busy);
  const data = map.data || {};
  const documents = data.documents || [];

  const build = () => {
    setBusy(true);
    Api.buildMap().then(() => { setBusy(false); map.reload(); }).catch(() => setBusy(false));
  };

  return html`
    <${Stack} gap=${16}>
      <${PageTitle} title="Карта документов"
        subtitle="Короткое описание каждого документа. По ним сервис понимает, что где написано."
        right=${html`<${H.Button} mode="secondary" size="small" text="Дописать описания"
          loading=${busy} onClick=${build} />`} />
      ${busy ? html`<${Note}>Модель пишет описания, это долго: ${elapsed}<//>` : null}
      <${Card}>
        <${Body}>
          <${Block} state=${map.state === 'ready' && documents.length === 0 ? 'empty'
              : map.state === 'ready' ? 'ready' : map.state}
            error=${map.error} onRetry=${map.reload}
            empty=${{ title: 'Описаний пока нет', description: 'Постройте индекс, затем нажмите «Дописать описания».' }}>
            <${Stack} gap=${12}>
              <${Row} gap=${12}>
                <${H.Status} mode=${STATUS.ok} label=${`с описанием: ${data.with_summary || 0}`} />
                <${H.Status} mode=${STATUS.warn} label=${`без описания: ${(data.total || 0) - (data.with_summary || 0)}`} />
              <//>
              <${Stack} gap=${6}>
                ${documents.map((item) => html`
                  <${Stack} key=${item.path} gap=${2} style=${{ padding: '8px 0', borderBottom: '1px solid ' + C.line }}>
                    <${Row} style=${{ justifyContent: 'space-between' }}>
                      <span style=${{ fontSize: '13px', fontWeight: 600 }}>${item.title || fileName(item.path)}</span>
                      <${Muted}>${item.path}<//>
                    <//>
                    ${item.summary
                      ? html`<span style=${{ fontSize: '12px', color: C.textSec }}>${item.summary}</span>`
                      : html`<${H.Tag} mode=${TAG.warn} size="small" readOnly=${true}>описания пока нет<//>`}
                  <//>`)}
              <//>
            <//>
          <//>
        <//>
      <//>
    <//>`;
}

/* --- публикации ------------------------------------------------------------- */

function ScreenPublications({ app }) {
  const publications = useAsync(() => Api.publications(), [app.product]);
  const registry = (publications.data || {}).publications || {};
  const rows = Object.keys(registry).flatMap((docPath) =>
    Object.keys(registry[docPath] || {}).map((target) => ({
      key: docPath + target, docPath, target, ...(registry[docPath][target] || {}),
    })));

  return html`
    <${Stack} gap=${16}>
      <${PageTitle} title="Публикации"
        subtitle="Где какая статья опубликована." />
      <${Card}>
        <${Body}>
          <${Block} state=${publications.state === 'ready' && rows.length === 0 ? 'empty'
              : publications.state === 'ready' ? 'ready' : publications.state}
            error=${publications.error} onRetry=${publications.reload}
            empty=${{ title: 'Пока ничего не опубликовано', description: 'Публикуют с экрана результата и только по подтверждению.' }}>
            <${H.Table} pagination=${false} dataSource=${rows}
              columns=${[
                { title: 'Документ', dataIndex: 'docPath' },
                { title: 'Площадка', dataIndex: 'target', width: 160 },
                { title: 'Идентификатор', dataIndex: 'id', width: 200 },
                { title: 'Когда', dataIndex: 'at', width: 180 },
              ]} />
          <//>
        <//>
      <//>
    <//>`;
}

/* --- журнал ----------------------------------------------------------------- */

function ScreenAudit({ app }) {
  const audit = useAsync(() => Api.audit(200), [app.product]);
  const records = (audit.data || {}).records || [];
  return html`
    <${Stack} gap=${16}>
      <${PageTitle} title="Журнал"
        subtitle="Что делал сервис: запросы к модели, импорт и публикации." />
      <${H.SectionMessage} mode="info" title="В журнале нет текстов документов и требований">
        Записываем только факт: время, действие, роль и модель. Сами тексты сюда не попадают.
      <//>
      <${Card}>
        <${Body}>
          <${Block} state=${audit.state === 'ready' && records.length === 0 ? 'empty'
              : audit.state === 'ready' ? 'ready' : audit.state}
            error=${audit.error} onRetry=${audit.reload}
            empty=${{ title: 'Записей пока нет', description: 'Журнал заполнится, когда сервис первый раз обратится к модели.' }}>
            <${H.Table} pagination=${false}
              dataSource=${records.map((item, index) => ({ ...item, key: index }))}
              columns=${[
                { title: 'Время', dataIndex: 'at', width: 180 },
                { title: 'Действие', dataIndex: 'action', width: 180 },
                { title: 'Роль', dataIndex: 'role', width: 140 },
                { title: 'Модель', dataIndex: 'model' },
                { title: 'Итог', dataIndex: 'outcome', width: 140 },
              ]} />
          <//>
        <//>
      <//>
    <//>`;
}

window.MoreScreens = { ScreenArticle, ScreenResults, ScreenMap, ScreenPublications, ScreenAudit };

}());
