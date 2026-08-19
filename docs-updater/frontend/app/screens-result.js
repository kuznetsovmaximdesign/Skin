/* Экран результата: три способа посмотреть одну и ту же правку, автопроверка и действия.
   Единственное разрушающее действие — «Перезаписать оригинал» — отделено и подтверждается. */
(function () {

const { H, html, C, TAG, STATUS, severityTone, Card, CardHead, Body, Row, Stack, PageTitle,
        Note, Muted, Block, useAsync, useElapsed, readValue, plural, fileName,
        useState, useEffect } = window.UI;

const DIFF_LABEL = { insert: 'добавлено', delete: 'удалено', replace: 'изменено', equal: 'без изменений' };
const DIFF_TONE = { insert: 'ok', delete: 'bad', replace: 'warn', equal: 'muted' };

function DiffRow({ block, index }) {
  const tone = DIFF_TONE[block.type];
  return html`
    <div style=${{ display: 'grid', gridTemplateColumns: '104px 1fr 1fr', gap: '12px',
                   alignItems: 'start', paddingBottom: '10px', borderBottom: '1px solid ' + C.line }}>
      <${Stack} gap=${4}>
        ${block.type === 'equal'
          ? html`<${Muted}>без изменений<//>`
          : html`<${H.Status} mode=${STATUS[tone] || STATUS.info} label=${DIFF_LABEL[block.type]} />`}
        <span style=${{ fontSize: '11px', color: C.textMuted }}>абзац ${index + 1}</span>
      <//>
      <div style=${{ fontSize: '13px', lineHeight: '20px', padding: '10px 12px', borderRadius: '8px',
                     border: '1px solid ' + C.border,
                     background: block.type === 'delete' || block.type === 'replace' ? C.badBg : C.surface }}>
        ${block.old || ' '}
      </div>
      <div style=${{ fontSize: '13px', lineHeight: '20px', padding: '10px 12px', borderRadius: '8px',
                     border: '1px solid ' + (block.new ? C.okBorder : C.border),
                     background: block.type === 'insert' || block.type === 'replace' ? C.okBg : C.surface }}>
        ${block.type === 'replace'
          ? html`<${H.TextDiff} oldText=${block.old} newText=${block.new} textType="BTR3" />`
          : (block.new || ' ')}
      </div>
    </div>`;
}

function ChecksBlock({ checks }) {
  if (!checks) return null;
  const violations = checks.violations || [];
  const summary = checks.summary || {};
  return html`
    <${Card}>
      <${CardHead} title="Проверка по правилам"
        subtitle=${checks.fix_iterations
          ? `Модель уже исправила часть, попыток: ${checks.fix_iterations}`
          : 'Проверяем формулировки, оформление и структуру'} />
      <${Body}>
        <${Row} gap=${12}>
          <${H.Status} mode=${STATUS.bad} label=${`${summary.violations || 0} ${plural(summary.violations || 0, 'нарушение', 'нарушения', 'нарушений')}`} />
          <${H.Status} mode=${STATUS.warn} label=${`${summary.recommendations || 0} ${plural(summary.recommendations || 0, 'рекомендация', 'рекомендации', 'рекомендаций')}`} />
          <${Muted}>Показываем всё, что нашли, — ничего не прячем.<//>
        <//>
        ${violations.length === 0
          ? html`<${H.SectionMessage} mode="success" title="Всё по правилам">
              Текст не нарушает подключённые правила.<//>`
          : html`<${Stack} gap=${6}>
              ${violations.map((item, index) => html`
                <${Row} key=${index} gap=${10} style=${{ alignItems: 'flex-start' }}>
                  <${H.Status} mode=${STATUS[severityTone(item.severity)]}
                    label=${item.kind === 'violation' ? 'нарушение' : 'рекомендация'} />
                  <${H.Tag} mode=${TAG.muted} size="small" readOnly=${true}>${item.source}/${item.rule}<//>
                  <span style=${{ fontSize: '13px', flex: 1, minWidth: '240px' }}>
                    ${item.line ? `строка ${item.line}: ` : ''}${item.message}
                  </span>
                <//>`)}
            <//>`}
      <//>
    <//>`;
}

function CascadePanel({ result, onClose }) {
  const [run, setRun] = useState({ state: 'idle', data: null, error: null });
  const versions = useAsync(() => Api.languageVersions(result.doc_path), [result.doc_path]);
  const start = () => {
    setRun({ state: 'loading', data: null, error: null });
    Api.cascade(result.doc_path, result.updated)
      .then((data) => setRun({ state: 'ready', data, error: null }))
      .catch((error) => setRun({ state: 'error', data: null, error }));
  };
  const elapsed = useElapsed(run.state === 'loading');
  const targets = ((versions.data || {}).targets) || [];

  return html`
    <${H.Sidebar} visible=${true} onClose=${onClose} size="small" mask=${true}
      title="Перевести на другие языки"
      subtitle=${`${targets.length} ${plural(targets.length, 'языковая версия', 'языковые версии', 'языковых версий')}`}>
      <${Stack} gap=${12}>
        ${run.state === 'idle' ? html`
          <${Stack} gap=${8}>
            <${Muted}>Языки заданы в настройках. Каждый перевод ложится отдельным файлом.<//>
            ${targets.map((code) => html`<div key=${code} style=${{ fontSize: '13px' }}>${code}</div>`)}
            <${H.Button} mode="primary" size="small" text="Перевести" onClick=${start} />
          <//>` : null}
        ${run.state === 'loading' ? html`
          <${Block} state="loading" loading=${{ title: 'Переводим', description: `Осталось языков: ${targets.length} · ${elapsed}` }} />` : null}
        ${run.state === 'error' ? html`<${Block} state="error" error=${run.error} onRetry=${start} />` : null}
        ${run.state === 'ready' ? html`
          <${Stack} gap=${8}>
            <${Row} gap=${12}>
              <${H.Status} mode=${STATUS.ok} label=${`переведено: ${(run.data.summary || {}).translated || 0}`} />
              <${H.Status} mode=${STATUS.warn} label=${`нужна вычитка: ${(run.data.summary || {}).needs_review || 0}`} />
            <//>
            ${(run.data.results || []).map((item) => html`
              <${Stack} key=${item.language} gap=${2}
                style=${{ padding: '8px 0', borderBottom: '1px solid ' + C.line }}>
                <${Row} style=${{ justifyContent: 'space-between' }}>
                  <span style=${{ fontSize: '13px', fontWeight: 600 }}>${item.language}</span>
                  <${H.Status} mode=${item.needs_review ? STATUS.warn : STATUS.ok}
                    label=${item.needs_review ? 'нужна вычитка человеком' : 'готово'} />
                <//>
                ${item.reason ? html`<${Muted}>${item.reason}<//>` : null}
              <//>`)}
          <//>` : null}
      <//>
    <//>`;
}

function PublishPanel({ result, onClose }) {
  const preview = useAsync(() => Api.publishPreview({ doc_path: result.doc_path, result_file: result.result_file }),
    [result.result_file]);
  const [sent, setSent] = useState(null);
  const [busy, setBusy] = useState(false);
  const data = preview.data || {};
  const outbound = data.outbound || {};
  const blocked = outbound.allowed === false;

  const publish = () => {
    setBusy(true);
    Api.publish({ doc_path: result.doc_path, result_file: result.result_file, confirm: true })
      .then((answer) => { setSent(answer); setBusy(false); })
      .catch((error) => { preview.setData({ ...data, error }); setBusy(false); });
  };

  return html`
    <${H.Sidebar} visible=${true} onClose=${onClose} size="small" mask=${true}
      title="Публикация" subtitle="Без подтверждения ничего не уйдёт">
      <${Block} state=${preview.state === 'ready' ? 'ready' : preview.state} error=${preview.error} onRetry=${preview.reload}>
        <${Stack} gap=${12}>
          ${data.enabled === false ? html`
            <${H.SectionMessage} mode="info" title="Публикация выключена в настройках">
              Включите publish.enabled в config.yaml и укажите адреса площадок.
            <//>` : null}
          ${blocked ? html`
            <${H.SectionMessage} mode="error" title="Публиковать нельзя: проверка не пропустила">
              ${(outbound.reasons || []).join('; ') || 'В тексте есть признаки закрытых требований.'}
            <//>` : null}
          ${(data.targets || []).map((target) => html`
            <${Stack} key=${target.target} gap=${2} style=${{ padding: '8px 0', borderBottom: '1px solid ' + C.line }}>
              <${Row} style=${{ justifyContent: 'space-between' }}>
                <span style=${{ fontSize: '13px', fontWeight: 600 }}>${target.target}</span>
                <${H.Tag} mode=${target.action === 'обновить' ? TAG.info : TAG.ok} size="small" readOnly=${true}>
                  ${target.action}
                <//>
              <//>
              <${Muted}>${target.base_url || 'адрес не задан'}<//>
              <${Row} gap=${8}>
                <${H.Status} mode=${target.token_ready ? STATUS.ok : STATUS.warn}
                  label=${target.token_ready ? 'доступ есть' : 'нет доступа: не задан токен'} />
                ${target.last_published ? html`<${Muted}>публиковали: ${target.last_published}<//>` : null}
              <//>
            <//>`)}
          ${sent ? html`
            <${H.SectionMessage} mode="success" title=${`Опубликовано площадок: ${(sent.summary || {}).published || 0}`}>
              ${(sent.results || []).map((item) => `${item.target}: ${item.ok ? 'готово' : item.error || 'ошибка'}`).join('; ')}
            <//>`
          : html`
            <${H.Button} mode="primary" size="small" text="Опубликовать"
              loading=${busy} disabled=${data.enabled === false || blocked}
              onClick=${publish} />`}
        <//>
      <//>
    <//>`;
}

function ScreenResult({ app }) {
  const result = app.result;
  const [view, setView] = useState('diff');
  const [onlyChanges, setOnlyChanges] = useState(false);
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);
  const [replaceOpen, setReplaceOpen] = useState(false);
  const [applied, setApplied] = useState(null);
  const [panel, setPanel] = useState(null);
  const [review, setReview] = useState({ state: 'idle', data: null, error: null });

  useEffect(() => { setText(result ? result.updated || '' : ''); }, [result && result.result_file]);

  if (!result) {
    return html`
      <${Stack} gap=${16}>
        <${PageTitle} title="Что поменялось" />
        <${Card}><${Body}>
          <${Block} state="empty" empty=${{ title: 'Результата пока нет',
            description: 'Сначала переписать текст на шаге «Обновление документа».',
            action: html`<${H.Button} mode="primary" size="small" text="К правке документа" onClick=${() => app.go('update')} />` }} />
        <//><//>
      <//>`;
  }

  const diff = result.diff || { blocks: [], stats: {} };
  const stats = diff.stats || {};
  const blocks = onlyChanges ? (diff.blocks || []).filter((item) => item.type !== 'equal') : (diff.blocks || []);

  const save = () => {
    setSaving(true);
    Api.saveResult(result.doc_path, result.result_file, text)
      .then((data) => { app.setResult({ ...result, updated: data.updated, diff: data.diff }); setSaving(false); })
      .catch(() => setSaving(false));
  };

  const apply = () => {
    Api.apply(result.doc_path, result.result_file)
      .then((data) => { setApplied(data); setReplaceOpen(false); })
      .catch((error) => { setApplied({ error }); setReplaceOpen(false); });
  };

  const runReview = () => {
    setReview({ state: 'loading', data: null, error: null });
    Api.review(text || result.updated)
      .then((data) => setReview({ state: 'ready', data, error: null }))
      .catch((error) => setReview({ state: 'error', data: null, error }));
  };

  return html`
    <${Stack} gap=${16}>
      <${PageTitle} title="Что поменялось"
        subtitle=${`${result.doc_path} · режим: ${result.mode || 'набор правок'}${result.model ? ' · модель: ' + result.model : ''}`} />

      ${applied && applied.error ? html`<${Block} state="error" error=${applied.error} />` : null}
      ${applied && applied.applied ? html`
        <${H.SectionMessage} mode="success" title="Оригинал перезаписан">
          Копия старого файла: ${applied.backup}. ${applied.index_updated ? 'Список документов обновлён.' : 'Список документов обновите вручную.'}
        <//>`
      : html`
        <${H.SectionMessage} mode="success" title="Оригинал не тронут">
          Правка лежит в отдельном файле: ${result.result_file}. Оригинал изменится только
          после кнопки «Перезаписать оригинал» — она внизу, отдельно от остальных.
        <//>`}

      <${Card}>
        <${Row} gap=${28} style=${{ padding: '14px 18px' }}>
          <${Row} gap=${10}>
            <${H.Status} mode=${STATUS.ok} label="добавлено" />
            <span style=${{ fontSize: '20px', fontWeight: 600 }}>${stats.added || 0}</span>
          <//>
          <${Row} gap=${10}>
            <${H.Status} mode=${STATUS.bad} label="удалено" />
            <span style=${{ fontSize: '20px', fontWeight: 600 }}>${stats.removed || 0}</span>
          <//>
          <${Row} gap=${10}>
            <${H.Status} mode=${STATUS.warn} label="изменено" />
            <span style=${{ fontSize: '20px', fontWeight: 600 }}>${stats.changed || 0}</span>
          <//>
          <div style=${{ marginLeft: 'auto' }}>
            <${Muted}>Всего абзацев: ${(diff.blocks || []).length}<//>
          </div>
        <//>
      <//>

      <${Card}>
        <div style=${{ padding: '14px 18px 0' }}>
          <div style=${{ fontSize: '15px', fontWeight: 600 }}>Что поменялось в тексте</div>
          <${Muted}>Одна и та же правка в трёх видах<//>
        </div>
        <div style=${{ padding: '0 18px' }}>
          <${H.Tabs} activeKey=${view} onChange=${setView}
            tabBarExtraContent=${html`
              <${H.Checkbox} checked=${onlyChanges} onChange=${() => setOnlyChanges(!onlyChanges)}>
                только изменения
              <//>`}>
            <${H.Tabs.TabPane} tab="Было и стало" key="diff">
              <${Stack} gap=${10} style=${{ padding: '12px 0 16px' }}>
                ${blocks.length === 0
                  ? html`<${Block} state="empty" empty=${{ title: 'Ничего не изменилось',
                      description: 'Модель вернула тот же текст.' }} />`
                  : blocks.map((block, index) => html`<${DiffRow} key=${index} block=${block} index=${index} />`)}
                <${Muted}>Показано абзацев: ${blocks.length} из ${(diff.blocks || []).length}.<//>
              <//>
            <//>
            <${H.Tabs.TabPane} tab="Предпросмотр" key="preview">
              <${Stack} gap=${6} style=${{ padding: '16px 0 20px' }}>
                ${(diff.blocks || []).filter((block) => block.new).map((block, index) => html`
                  <div key=${index} style=${{ padding: '6px 8px', borderRadius: '8px', lineHeight: '22px',
                      fontSize: '13px',
                      background: block.type === 'insert' || block.type === 'replace' ? C.okBg : 'transparent' }}>
                    ${block.new}
                  </div>`)}
                <${Muted}>Зелёным — то, что добавилось.<//>
              <//>
            <//>
            <${H.Tabs.TabPane} tab="Готовый текст" key="text">
              <${Stack} gap=${10} style=${{ padding: '14px 0 18px' }}>
                <${H.Textbox.Textarea} value=${text} rows=${15} autoSize=${false}
                  onChange=${(value) => setText(readValue(value))} />
                <${Row}>
                  <${H.Button} mode="primary" size="small" text="Сохранить свои правки"
                    loading=${saving} onClick=${save} />
                  <${Muted}>Меняется файл с правкой, а не оригинал.<//>
                <//>
              <//>
            <//>
          <//>
        </div>
      <//>

      <${ChecksBlock} checks=${result.checks} />

      ${review.state !== 'idle' ? html`
        <${Card}>
          <${CardHead} title="Что заметила модель" />
          <${Body}>
            <${Block} state=${review.state === 'ready' ? 'ready' : review.state} error=${review.error} onRetry=${runReview}
              loading=${{ title: 'Модель читает текст' }}>
              <${Stack} gap=${6}>
                ${((review.data || {}).notes || []).map((note, index) => html`
                  <div key=${index} style=${{ fontSize: '13px', lineHeight: '20px' }}>• ${note}</div>`)}
              <//>
            <//>
          <//>
        <//>` : null}

      <${Card}>
        <${CardHead} title="Что дальше" subtitle="Перезапись оригинала — единственное действие, которое не отменить" />
        <${Row} style=${{ padding: '16px 18px' }} gap=${8}>
          <${H.Button} mode="secondary" size="small" text="Скачать .md"
            onClick=${() => window.open(Api.downloadUrl(result.result_file), '_blank')} />
          <${H.Button} mode="secondary" size="small" text="Спросить модель" onClick=${runReview} />
          <${H.Button} mode="secondary" size="small" text="Перевести на другие языки"
            onClick=${() => setPanel('cascade')} />
          <${H.Button} mode="secondary" size="small" text="Опубликовать…" onClick=${() => setPanel('publish')} />
          <div style=${{ marginLeft: 'auto' }}>
            <${H.Button} mode="dangerFilled" size="small" text="Перезаписать оригинал"
              disabled=${!!(applied && applied.applied)} onClick=${() => setReplaceOpen(true)} />
          </div>
        <//>
      <//>

      <${H.Modal} visible=${replaceOpen} centered=${true} mode="warning" size="small"
        header="Перезаписать оригинал?"
        content=${`Файл ${result.doc_path} будет заменён. Перед заменой сервис сохранит резервную копию (.bak с датой) и пересоберёт индекс.`}
        onClose=${() => setReplaceOpen(false)}
        actions=${{
          FIRST_ACTION: { text: 'Перезаписать оригинал', mode: 'dangerFilled', onClick: apply },
          SECOND_ACTION: { text: 'Не перезаписывать', mode: 'secondary', onClick: () => setReplaceOpen(false) },
        }} />

      ${panel === 'cascade' ? html`<${CascadePanel} result=${result} onClose=${() => setPanel(null)} />` : null}
      ${panel === 'publish' ? html`<${PublishPanel} result=${result} onClose=${() => setPanel(null)} />` : null}
    <//>`;
}

window.ResultScreen = { ScreenResult };

}());
