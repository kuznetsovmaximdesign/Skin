/* Основной путь писателя: описал изменение → выбрал документ → получил правку → сравнил.
   Данные приходят из Api (единственное место с адресами), здесь только экран. */
(function () {

const { H, html, C, TAG, STATUS, severityTone, Card, CardHead, Body, Row, Stack, PageTitle,
        Note, Muted, Block, useAsync, useElapsed, readValue, percent, plural, fileName,
        useState, useEffect, useRef } = window.UI;

/* --- шаг 1: что изменилось -------------------------------------------------- */

function CandidateCard({ item, onPick }) {
  return html`
    <div style=${{ border: '1px solid ' + C.border, borderRadius: '8px', padding: '12px 14px',
                   display: 'grid', gridTemplateColumns: '1fr 180px', gap: '16px', alignItems: 'start' }}>
      <${Stack} gap=${6} style=${{ minWidth: 0 }}>
        <div style=${{ fontSize: '14px', fontWeight: 600, lineHeight: '20px' }}>${item.title}</div>
        <div style=${{ fontSize: '12px', color: C.textSec, overflowWrap: 'anywhere' }}>${item.path}</div>
        <${Row}>
          ${item.heading ? html`<span style=${{ fontSize: '12px' }}>Раздел: ${item.heading}</span>` : null}
          <${H.Tag} mode=${item.matched_on === 'summary' ? TAG.info : TAG.muted} size="small" readOnly=${true}>
            ${item.matched_on === 'summary' ? 'совпало по описанию документа' : 'совпало по разделу'}
          <//>
        <//>
        ${item.snippet ? html`
          <div style=${{ fontSize: '13px', lineHeight: '20px', background: C.line,
                         borderLeft: '3px solid #CCD0D4', padding: '8px 10px', borderRadius: '0 8px 8px 0' }}>
            ${item.snippet}</div>` : null}
      <//>
      <${Stack} gap=${8} style=${{ alignItems: 'flex-start' }}>
        <${Muted}>Совпадение<//>
        <div style=${{ fontSize: '20px', fontWeight: 600, lineHeight: 1 }}>${percent(item.relevance)}</div>
        <${H.Button} mode="secondary" size="small" text="Обновить документ"
          onClick=${() => onPick(item)} />
      <//>
    </div>`;
}

function CoverageRow({ item }) {
  const tone = item.action === 'устарело' ? 'bad' : item.action === 'заменить' ? 'warn' : 'ok';
  const bar = { bad: '#D6413B', warn: '#D0900E', ok: '#CCD0D4' }[tone];
  return html`
    <div style=${{ padding: '10px 4px 10px 10px', borderBottom: '1px solid ' + C.line,
                   borderLeft: '3px solid ' + bar, display: 'grid',
                   gridTemplateColumns: '1fr 132px 48px', gap: '10px', alignItems: 'start' }}>
      <${Stack} gap=${3} style=${{ minWidth: 0 }}>
        <div style=${{ fontSize: '13px', fontWeight: 600, lineHeight: '18px' }}>${item.title}</div>
        <div style=${{ fontSize: '11px', color: C.textMuted, overflowWrap: 'anywhere' }}>${item.path}</div>
        <div style=${{ fontSize: '12px', lineHeight: '16px', color: C.textSec }}>${item.reason || item.summary || ''}</div>
      <//>
      <div><${H.Tag} mode=${TAG[tone]} size="small" readOnly=${true}>${item.action}<//></div>
      <div style=${{ fontSize: '13px', fontWeight: 600, textAlign: 'right' }}>${percent(item.relevance)}</div>
    </div>`;
}

const FINDING_TITLES = {
  'broken-link': 'Битые ссылки и якоря',
  'stale-value': 'Устаревшие значения',
  'removed-mention': 'Упоминания удалённого',
  marker: 'Оставшиеся пометки [уточнить] и TODO',
  glossary: 'Термины вне глоссария',
  'structure-mismatch': 'Расхождение структуры между языками',
  'date-mismatch': 'Расхождение дат обновления',
  'version-mismatch': 'Расхождение версий продукта',
  'missing-locale': 'Нет версии на языке',
};

function FindingsPane({ data }) {
  const findings = data.findings || [];
  const errors = findings.filter((item) => item.severity === 'error').length;
  const byKind = data.summary && data.summary.by_kind ? data.summary.by_kind : {};
  const kinds = Object.keys(byKind).sort((a, b) => byKind[b] - byKind[a]);
  return html`
    <${Stack} gap=${12} style=${{ padding: '12px 0 4px' }}>
      <${Row} gap=${12}>
        <${H.Status} mode=${STATUS.bad} label=${`${errors} ${plural(errors, 'ошибка', 'ошибки', 'ошибок')}`} />
        <${H.Status} mode=${STATUS.warn}
          label=${`${findings.length - errors} ${plural(findings.length - errors, 'предупреждение', 'предупреждения', 'предупреждений')}`} />
      <//>
      <${Stack} gap=${8} style=${{ maxWidth: '640px' }}>
        ${kinds.map((kind) => {
          const worst = findings.find((item) => item.kind === kind && item.severity === 'error');
          return html`
            <div key=${kind} style=${{ display: 'grid', gridTemplateColumns: '124px 1fr 32px',
                                       gap: '8px', alignItems: 'center' }}>
              <${H.Status} mode=${worst ? STATUS.bad : STATUS.warn} label=${worst ? 'ошибка' : 'внимание'} />
              <span style=${{ fontSize: '13px', lineHeight: '18px' }}>${FINDING_TITLES[kind] || kind}</span>
              <span style=${{ fontSize: '13px', fontWeight: 600, textAlign: 'right' }}>${byKind[kind]}</span>
            </div>`;
        })}
      <//>
      <div style=${{ paddingTop: '4px', borderTop: '1px solid ' + C.line, fontSize: '12px', color: C.textSec }}>
        Всего находок: ${findings.length}. Ниже — первые ${Math.min(findings.length, 40)}.
      </div>
      <${Stack} gap=${6}>
        ${findings.slice(0, 40).map((item, index) => html`
          <${Row} key=${index} gap=${10} style=${{ alignItems: 'flex-start' }}>
            <${H.Status} mode=${STATUS[severityTone(item.severity)]} label=${item.kind} />
            <span style=${{ fontSize: '13px', flex: 1, minWidth: '200px' }}>${item.message}</span>
            <${Muted}>${item.doc_path}${item.line ? ':' + item.line : ''}<//>
          <//>`)}
      <//>
    <//>`;
}

function ScreenChanged({ app }) {
  const [tab, setTab] = useState('candidates');
  const [analysis, setAnalysis] = useState({ state: 'idle', data: null, error: null });
  const documents = useAsync(() => Api.documents(), [app.product]);
  const elapsed = useElapsed(analysis.state === 'loading');

  const description = app.description;
  const analyze = () => {
    if (!description.trim()) return;
    setAnalysis({ state: 'loading', data: null, error: null });
    Promise.all([
      Api.search(description),
      Api.impact(description).catch((error) => ({ error })),
      Api.drift(description).catch((error) => ({ error })),
    ])
      .then(([found, impact, drift]) => setAnalysis({
        state: 'ready', error: null,
        data: { candidates: found.candidates || [], impact, drift },
      }))
      .catch((error) => setAnalysis({ state: 'error', data: null, error }));
  };

  const pick = (item) => { app.selectDoc({ path: item.path, title: item.title }); app.go('update'); };
  const counter = `${description.length} ${plural(description.length, 'символ', 'символа', 'символов')}`;

  return html`
    <${Stack} gap=${16} style=${{ flex: 1, minHeight: '460px' }}>
      <${PageTitle} title="Что изменилось"
        subtitle="Опишите словами, что изменилось. Сервис найдёт документы, которые надо поправить." />

      <div style=${{ display: 'flex', gap: '20px', alignItems: 'stretch', flex: 1, minHeight: 0 }}>
        <${Card} style=${{ width: '420px', flex: 'none', display: 'flex', flexDirection: 'column' }}>
          <${CardHead} title="Опишите изменение" subtitle="Всё, что попадёт в документ, берётся отсюда" />
          <${Body} style=${{ flex: 1, overflowY: 'auto' }}>
            <${H.SectionMessage} mode="info">
              Модель ничего не придумывает. Чего нет в описании — того не будет в тексте.
            <//>
            <${H.Textbox.Textarea} value=${description} rows=${9} autoSize=${false}
              placeholder="Например: срок жизни токена увеличен с 60 до 120 минут"
              onChange=${(value) => app.setDescription(readValue(value))} />
            <${Row} style=${{ justifyContent: 'space-between' }}>
              <${Muted}>${counter}<//>
              <${Muted}>Ctrl + Enter — начать поиск<//>
            <//>
            <${Row} style=${{ marginTop: 'auto', paddingTop: '8px' }}>
              <${H.Button} mode="primary" size="medium" text="Найти документы"
                loading=${analysis.state === 'loading'} disabled=${!description.trim() || analysis.state === 'loading'}
                onClick=${analyze} />
              <${H.Button} mode="tertiary" size="medium" text="Выбрать документ из списка"
                onClick=${() => app.go('pick')} />
            <//>
            ${app.screenArgs.pick || app.current === 'pick' ? null : null}
          <//>
        <//>

        <${Card} style=${{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <${CardHead} title="Результат анализа" subtitle="Три разных ответа на одно описание" />
          <div style=${{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '8px 18px 18px' }}>
            ${analysis.state === 'idle' ? html`
              <${Block} state="empty" empty=${{ title: 'Здесь появятся найденные документы',
                description: 'Опишите изменение слева и нажмите «Найти документы».' }} />` : null}
            ${analysis.state === 'loading' ? html`
              <${Block} state="loading" loading=${{ title: 'Ищем подходящие документы',
                description: `Сравниваем описание с текстом документов · ${elapsed}` }} />` : null}
            ${analysis.state === 'error' ? html`
              <${Block} state="error" error=${analysis.error} onRetry=${analyze} />` : null}
            ${analysis.state === 'ready' ? html`
              <${H.Tabs} activeKey=${tab} onChange=${setTab}>
                <${H.Tabs.TabPane} tab=${`Что править · ${analysis.data.candidates.length}`} key="candidates">
                  <${Stack} gap=${10} style=${{ padding: '12px 0 4px' }}>
                    ${analysis.data.candidates.length === 0
                      ? html`<${Block} state="empty" empty=${{ title: 'Ничего не нашлось',
                          description: 'Опишите изменение другими словами или выберите документ сами.' }} />`
                      : analysis.data.candidates.map((item) => html`
                          <${CandidateCard} key=${item.path + item.heading} item=${item} onPick=${pick} />`)}
                  <//>
                <//>
                <${H.Tabs.TabPane} tab=${`Что ещё задето · ${(analysis.data.impact.documents || []).length}`} key="coverage">
                  ${analysis.data.impact.error
                    ? html`<${Block} state="error" error=${analysis.data.impact.error} />`
                    : html`<div style=${{ padding: '8px 0 4px' }}>
                        ${(analysis.data.impact.documents || []).map((item) => html`
                          <${CoverageRow} key=${item.path} item=${item} />`)}
                      </div>`}
                <//>
                <${H.Tabs.TabPane} tab=${`Что ещё стоит поправить · ${((analysis.data.drift.summary || {}).total) || 0}`} key="findings">
                  ${analysis.data.drift.error
                    ? html`<${Block} state="error" error=${analysis.data.drift.error} />`
                    : html`<${FindingsPane} data=${analysis.data.drift} />`}
                <//>
              <//>` : null}
          </div>
        <//>
      </div>

      ${app.current === 'pick' ? html`
        <${Card}>
          <${CardHead} title="Выбрать документ из списка" subtitle="Все файлы .md из вашей папки" />
          <${Body}>
            <${Block} state=${documents.state === 'ready' && (documents.data.documents || []).length === 0
                ? 'empty' : documents.state === 'ready' ? 'ready' : documents.state}
              error=${documents.error} onRetry=${documents.reload}
              empty=${{ title: 'В папке нет файлов .md', description: 'Проверьте путь на экране «Настройки и индекс».' }}>
              <div style=${{ maxHeight: '320px', overflowY: 'auto' }}>
                ${((documents.data || {}).documents || []).map((item) => html`
                  <div key=${item.path} role="button" tabIndex=${0}
                    onClick=${() => pick(item)}
                    style=${{ display: 'flex', justifyContent: 'space-between', gap: '10px',
                              padding: '8px 10px', borderBottom: '1px solid ' + C.line, cursor: 'pointer' }}>
                    <span style=${{ fontSize: '13px' }}>${item.title}</span>
                    <${Muted}>${item.path}<//>
                  </div>`)}
              </div>
            <//>
          <//>
        <//>` : null}
    <//>`;
}

/* --- шаг 2: обновление документа -------------------------------------------- */

function PatchCard({ edit, onDecide }) {
  const [reason, setReason] = useState(edit.comment || '');
  const accepted = edit.status === 'accepted';
  const rejected = edit.status === 'rejected';
  return html`
    <div style=${{ border: '1px solid ' + (accepted ? C.okBorder : rejected ? C.border : C.border),
                   borderRadius: '8px', overflow: 'hidden' }}>
      <${Row} gap=${10} style=${{ padding: '10px 14px', background: accepted ? C.okBg : C.sunken,
                                  borderBottom: '1px solid ' + C.border }}>
        <span style=${{ fontSize: '13px', fontWeight: 600 }}>${edit.section}</span>
        <${H.Tag} mode=${edit.assumption ? TAG.warn : TAG.muted} size="small" readOnly=${true}>
          ${edit.assumption ? 'предположение' : 'есть основание'}
        <//>
        <${Muted}>Уверенность: ${edit.confidence}<//>
        <span style=${{ marginLeft: 'auto' }}>
          <${H.Status} mode=${accepted ? STATUS.ok : rejected ? STATUS.bad : STATUS.warn}
            label=${accepted ? 'принята' : rejected ? 'отклонена' : 'решения нет'} />
        </span>
      <//>
      <${Stack} gap=${10} style=${{ padding: '12px 14px' }}>
        <div style=${{ fontSize: '12px', lineHeight: '18px', background: edit.assumption ? C.warnBg : C.line,
                       borderLeft: '3px solid ' + (edit.assumption ? C.warnBorder : '#CCD0D4'),
                       padding: '8px 10px', borderRadius: '0 8px 8px 0' }}>
          ${edit.reason
            ? `Взято из вашего описания: «${edit.reason}»`
            : 'Модель не смогла показать, откуда это взяла — проверьте внимательно'}
        </div>
        <div style=${{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <${Stack} gap=${4}>
            <div style=${{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: C.textMuted }}>Было</div>
            <div style=${{ fontSize: '13px', lineHeight: '20px', padding: '10px 12px',
                           border: '1px solid ' + C.border, borderRadius: '8px', minHeight: '64px' }}>${edit.old}</div>
          <//>
          <${Stack} gap=${4}>
            <div style=${{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: C.textMuted }}>Станет</div>
            <div style=${{ fontSize: '13px', lineHeight: '20px', padding: '10px 12px',
                           border: '1px solid ' + C.okBorder, borderRadius: '8px', background: C.okBg, minHeight: '64px' }}>
              <${H.TextDiff} oldText=${edit.old} newText=${edit.new} textType="BTR3" />
            </div>
          <//>
        </div>
        <${Row}>
          <${H.Button} mode=${accepted ? 'primary' : 'secondary'} size="small" text="Принять"
            onClick=${() => onDecide(edit.id, true, reason)} />
          <${H.Button} mode=${rejected ? 'dangerFilled' : 'secondary'} size="small" text="Отклонить"
            onClick=${() => onDecide(edit.id, false, reason)} />
          <div style=${{ flex: 1, minWidth: '240px' }}>
            <${H.Textbox} value=${reason} placeholder="Почему отклоняете — сервис запомнит"
              onChange=${(value) => setReason(readValue(value))} />
          </div>
        <//>
      <//>
    </div>`;
}

function ScreenUpdate({ app }) {
  const doc = app.doc;
  const [scope, setScope] = useState('document');
  const [section, setSection] = useState(null);
  const [method, setMethod] = useState('whole');
  const [stream, setStream] = useState({ busy: false, text: '', status: '', done: null, error: null });
  const [changeset, setChangeset] = useState({ state: 'idle', data: null, error: null });
  const outline = useAsync(() => (doc ? Api.outline(doc.path) : Promise.resolve({ sections: [] })), [doc && doc.path]);
  const feedback = useAsync(() => (doc ? Api.feedback(doc.path) : Promise.resolve({ notes: [] })), [doc && doc.path]);
  const elapsed = useElapsed(stream.busy || changeset.state === 'loading');

  if (!doc) {
    return html`
      <${Stack} gap=${16}>
        <${PageTitle} title="Обновление документа" />
        <${Card}><${Body}>
          <${Block} state="empty" empty=${{ title: 'Документ не выбран',
            description: 'Вернитесь на шаг «Что изменилось» и выберите документ.',
            action: html`<${H.Button} mode="primary" size="small" text="Выбрать документ"
              onClick=${() => app.go('changed')} /> ` }} />
        <//><//>
      <//>`;
  }

  const body = () => ({
    doc_path: doc.path,
    change_description: app.description,
    section_index: scope === 'section' && section !== null ? section : null,
  });

  const runStream = () => {
    setStream({ busy: true, text: '', status: 'Модель пишет текст', done: null, error: null });
    Api.generateStream(body(), (event) => {
      if (event.type === 'chunk') {
        setStream((old) => ({ ...old, text: old.text + event.text }));
      } else if (event.type === 'checking') {
        setStream((old) => ({ ...old, status: 'Проверяем по вашим правилам' }));
      } else if (event.type === 'done') {
        setStream((old) => ({ ...old, busy: false, status: 'Готово', done: event }));
        app.setResult(event);
      } else if (event.type === 'error') {
        setStream((old) => ({ ...old, busy: false, error: { message: event.error, hint: event.hint } }));
      }
    }).then((streamed) => {
      if (streamed === false) {
        return Api.generate(body()).then((data) => {
          setStream({ busy: false, text: data.updated, status: 'Готово', done: data, error: null });
          app.setResult(data);
        });
      }
      return null;
    }).catch((error) => setStream((old) => ({ ...old, busy: false, error })));
  };

  const runChangeset = () => {
    setChangeset({ state: 'loading', data: null, error: null });
    Api.proposeChangeset({
      doc_path: doc.path,
      change_description: app.description,
      section_indexes: scope === 'section' && section !== null ? [section] : null,
    })
      .then((data) => setChangeset({ state: 'ready', data, error: null }))
      .catch((error) => setChangeset({ state: 'error', data: null, error }));
  };

  const decide = (editId, accepted, comment) => {
    Api.decideEdit(changeset.data.id, editId, accepted, comment)
      .then((data) => setChangeset({ state: 'ready', data, error: null }))
      .catch((error) => setChangeset((old) => ({ ...old, error })));
  };

  const build = () => {
    setChangeset((old) => ({ ...old, building: true }));
    Api.buildChangeset(changeset.data.id)
      .then((data) => { app.setResult(data); app.go('result'); })
      .catch((error) => setChangeset((old) => ({ ...old, building: false, error })));
  };

  const sections = (outline.data || {}).sections || [];
  const summary = changeset.data ? changeset.data.summary || {} : {};
  const notes = (feedback.data || {}).notes || [];

  return html`
    <${Stack} gap=${16}>
      <${PageTitle} title="Обновление документа" subtitle=${`${doc.title || fileName(doc.path)} · ${doc.path}`}
        right=${html`<${H.Button} mode="tertiary" size="small" text="Сменить документ" onClick=${() => app.go('changed')} />`} />

      <${Card}>
        <${CardHead} step="1" title="Что править"
          subtitle="Правка одного раздела безопаснее: остальной текст модель даже не увидит" />
        <${Body}>
          <${Row}>
            <${H.Button} mode=${scope === 'document' ? 'primary' : 'secondary'} size="small"
              text="Весь документ" onClick=${() => setScope('document')} />
            <${H.Button} mode=${scope === 'section' ? 'primary' : 'secondary'} size="small"
              text="Один раздел" onClick=${() => setScope('section')} />
          <//>
          <${Note}>Разделы, которых правка не касается, останутся точно такими же.<//>
          ${scope === 'section' ? html`
            <${Block} state=${outline.state === 'ready' && sections.length === 0 ? 'empty' : outline.state === 'ready' ? 'ready' : outline.state}
              error=${outline.error} onRetry=${outline.reload}
              empty=${{ title: 'В документе нет заголовков', description: 'Правьте документ целиком.' }}>
              <div style=${{ border: '1px solid ' + C.border, borderRadius: '8px', maxHeight: '260px', overflow: 'auto' }}>
                ${sections.map((item) => html`
                  <div key=${item.index} role="button" tabIndex=${0} onClick=${() => setSection(item.index)}
                    style=${{ display: 'flex', justifyContent: 'space-between', gap: '10px', padding: '8px 10px',
                              borderBottom: '1px solid ' + C.line, cursor: 'pointer',
                              background: section === item.index ? C.accentBg : 'transparent' }}>
                    <span style=${{ fontSize: '13px', paddingLeft: (item.level - 1) * 12 + 'px',
                                    fontWeight: section === item.index ? 600 : 400 }}>${item.title}</span>
                    <${Muted}>${item.chars} симв.<//>
                  </div>`)}
              </div>
            <//>` : null}
        <//>
      <//>

      <${Card}>
        <${CardHead} step="2" title="Как править"
          subtitle="Переписать текст целиком или разобрать правки по одной" />
        <${Row} style=${{ padding: '16px 18px' }}>
          <${H.Button} mode=${method === 'whole' ? 'primary' : 'secondary'} size="small"
            text="Переписать целиком" onClick=${() => setMethod('whole')} />
          <${H.Button} mode=${method === 'patch' ? 'primary' : 'secondary'} size="small"
            text="Разобрать по одной" onClick=${() => setMethod('patch')} />
          <div style=${{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
            <${H.Button} mode="primary" size="small"
              text=${method === 'whole' ? 'Переписать текст' : 'Показать правки'}
              loading=${stream.busy || changeset.state === 'loading'}
              disabled=${stream.busy || changeset.state === 'loading' || !app.description.trim()}
              onClick=${method === 'whole' ? runStream : runChangeset} />
            <${H.Button} mode="secondary" size="small" text="Открыть результат"
              disabled=${!app.result} onClick=${() => app.go('result')} />
          </div>
        <//>
        ${!app.description.trim() ? html`<${Body} style=${{ paddingTop: 0 }}>
          <${Note} tone="warn">Сначала опишите изменение на шаге «Что изменилось»: правка делается по нему.<//>
        <//>` : null}
      <//>

      <${Card}>
        <${CardHead} step="3" title="Результат"
          subtitle=${method === 'whole' ? 'Текст появляется сразу, по мере написания'
                                        : 'По каждой правке вы решаете сами'} />
        ${method === 'whole' ? html`
          <${Body}>
            ${stream.error ? html`<${Block} state="error" error=${stream.error} onRetry=${runStream} />` : null}
            ${!stream.busy && !stream.text && !stream.error ? html`
              <${Block} state="empty" empty=${{ image: 'preparing', title: 'Текст ещё не переписан',
                description: 'Нажмите «Переписать текст» — текст будет появляться сразу.' }} />` : null}
            ${stream.busy ? html`
              <${Row} gap=${10} style=${{ padding: '8px 12px', background: C.accentBg,
                                          border: '1px solid ' + C.accentBorder, borderRadius: '8px' }}>
                <${H.Loader} size="small" />
                <span style=${{ fontSize: '13px' }}>${stream.status}</span>
                <span style=${{ fontSize: '13px', fontWeight: 600, marginLeft: 'auto' }}>${elapsed}</span>
              <//>` : null}
            ${stream.done ? html`
              <${Row} gap=${10}>
                <${H.Status} mode=${STATUS.ok} label="Готово" />
                <span style=${{ fontSize: '13px' }}>
                  Проверка: ${((stream.done.checks || {}).summary || {}).errors || 0} нарушений,
                  ${((stream.done.checks || {}).summary || {}).warnings || 0} советов.
                </span>
                <${H.Button} mode="primary" size="small" text="Открыть результат" onClick=${() => app.go('result')} />
              <//>` : null}
            ${stream.text ? html`
              <div style=${{ border: '1px solid ' + C.border, borderRadius: '8px', padding: '16px 18px',
                             fontSize: '14px', lineHeight: '22px', whiteSpace: 'pre-wrap',
                             maxHeight: '420px', overflowY: 'auto' }}>${stream.text}</div>` : null}
          <//>` : html`
          <${Body}>
            ${changeset.state === 'idle' ? html`
              <${Block} state="empty" empty=${{ image: 'preparing', title: 'Правок пока нет',
                description: 'Нажмите «Показать правки» — сервис разберёт документ по разделам.' }} />` : null}
            ${changeset.state === 'loading' ? html`
              <${Block} state="loading" loading=${{ title: 'Читаем документ', description: elapsed }} />` : null}
            ${changeset.state === 'error' ? html`
              <${Block} state="error" error=${changeset.error} onRetry=${runChangeset} />` : null}
            ${changeset.state === 'ready' ? html`
              <${Stack} gap=${12}>
                <${Row} gap=${12} style=${{ padding: '8px 12px', background: C.line, borderRadius: '8px' }}>
                  <span style=${{ fontSize: '13px', fontWeight: 600 }}>
                    Предложено: ${summary.total || 0} · принято: ${summary.accepted || 0} · отклонено: ${summary.rejected || 0}
                    ${summary.assumptions ? ` · предположений: ${summary.assumptions}` : ''}
                  </span>
                  <${Muted}>Остальные разделы останутся без изменений.<//>
                <//>
                ${(changeset.data.edits || []).length === 0 ? html`
                  <${Block} state="empty" empty=${{ title: 'Модель не нашла, что менять',
                    description: 'Опишите изменение подробнее или выберите раздел сами.' }} />` : null}
                ${(changeset.data.edits || []).map((edit) => html`
                  <${PatchCard} key=${edit.id} edit=${edit} onDecide=${decide} />`)}
                ${(summary.accepted || 0) > 0 ? html`
                  <${Row}>
                    <${H.Button} mode="primary" size="small" text="Собрать документ из принятых правок"
                      loading=${!!changeset.building} onClick=${build} />
                    <${Muted}>Получится отдельный файл. Оригинал останется как есть.<//>
                  <//>` : null}
              <//>` : null}
          <//>`}
      <//>

      ${notes.length ? html`
        <div style=${{ background: C.sunken, border: '1px solid ' + C.border, borderRadius: '12px',
                       padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style=${{ fontSize: '13px', fontWeight: 600, color: C.textSec }}>Что вы уже отклоняли в этом документе</div>
          ${notes.slice(0, 5).map((note, index) => html`
            <div key=${index} style=${{ fontSize: '12px', lineHeight: '17px', color: C.textSec }}>${note}</div>`)}
          <div style=${{ fontSize: '11px', color: C.textMuted }}>
            Сервис помнит эти отказы и больше так не предлагает.
          </div>
        </div>` : null}
    <//>`;
}

window.FlowScreens = { ScreenChanged, ScreenUpdate };

}());
