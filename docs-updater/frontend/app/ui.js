/* Общие части интерфейса: палитра раскладки, каркасы карточек и четыре обязательных
   состояния блока с данными (загрузка / пусто / ошибка / недоступно).

   Внешний вид самих элементов задаёт HEXA. Здесь только «клей»: сетка, отступы и
   цвета фона страницы, взятые из макета. */

const H = window.KasperskyHexaUi || {};
const html = window.htm ? window.htm.bind(React.createElement) : null;
const { useState, useEffect, useCallback, useRef, useMemo } = React;

/* Цвета раскладки из макета. Дизайн-система не отдаёт их CSS-переменными,
   поэтому они собраны в одном месте: менять — только здесь. */
const C = {
  page: '#F1F2F4', surface: '#FFFFFF', border: '#E0E4E8', line: '#F2F3F4', sunken: '#F8F9FA',
  text: '#21272F', textSec: '#68707B', textMuted: '#98A0AA',
  accent: '#4269E7', accentBg: '#E9F0FF', accentBorder: '#C7D8FB',
  okBg: '#DFF8F3', okBorder: '#B9E3DA',
  warnBg: '#FEF8EB', warnBorder: '#D0900E', warnText: '#7A5405',
  badBg: '#FFECEA', badBorder: '#F3C4C0',
};

/* Смысл → цвет. HEXA красит теги названием цвета, а не смыслом, и неизвестное
   значение молча даёт белый тег, поэтому таблица одна на весь интерфейс. */
const TAG = { info: 'marina', ok: 'grey', warn: 'orange', bad: 'red', muted: 'grey' };
const STATUS = { ok: 'positive', warn: 'medium', bad: 'critical', info: 'medium' };
const severityTone = (severity) => (severity === 'error' ? 'bad' : 'warn');


/* Тени, фокус и выделение берём из токенов дизайн-системы, а не подбираем на глаз.
   Форма тени и её цвет лежат в теме отдельно — здесь они собираются в одно значение. */
function elevation(level) {
  const theme = H.LIGHT_THEME || {};
  const shape = ((theme.effects || {}).elevation || {})[level];
  const color = ((theme.colors || {}).elevation || {})[level];
  if (!shape || !color) return 'none';
  return Object.keys(shape).map((key) => `${shape[key]} ${color[key]}`).join(', ');
}

const ELEVATION = { small: elevation('small'), medium: elevation('medium'), large: elevation('large') };

/* Тень панели. Берём ту, что была у бокового меню, и переиспользуем везде:
   панели одного уровня не должны отличаться друг от друга. */
const PANEL_SHADOW = '0 4px 12px rgba(33,39,47,0.10), 0 2px 4px rgba(33,39,47,0.06)';

/* Кольцо фокуса и цвета выделенного пункта — тоже из темы. */
const FOCUS_RING = (() => {
  const theme = H.LIGHT_THEME || {};
  const shape = ((theme.effects || {}).focus || {})['1'];
  const color = ((theme.colors || {}).focus || {}).stroke;
  return shape && color ? `${shape} ${color}` : 'none';
})();

const SELECTED = (() => {
  const menu = ((H.LIGHT_THEME || {}).colors || {}).menu || {};
  const selected = menu.selected || {};
  return {
    bg: ((selected.bg || {}).enabled) || '#EEF2FC',
    border: ((selected.border || {}).enabled) || '#94B4FD',
  };
})();

/* --- каркасы --------------------------------------------------------------- */

const Card = ({ children, style }) => html`
  <div style=${{ background: C.surface, border: '1px solid ' + C.border, borderRadius: '12px',
                 boxShadow: PANEL_SHADOW, ...(style || {}) }}>${children}</div>`;

const CardHead = ({ title, subtitle, step, right }) => html`
  <div style=${{ display: 'flex', alignItems: 'flex-start', gap: '12px', padding: '14px 18px',
                 borderBottom: '1px solid ' + C.border }}>
    ${step ? html`<div style=${{ width: '28px', height: '28px', borderRadius: '8px', flex: 'none',
        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px',
        fontWeight: 700, background: C.accentBg, color: C.accent }}>${step}</div>` : null}
    <div style=${{ display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 }}>
      <div style=${{ fontSize: '15px', fontWeight: 600 }}>${title}</div>
      ${subtitle ? html`<div style=${{ fontSize: '12px', color: C.textSec }}>${subtitle}</div>` : null}
    </div>
    ${right ? html`<div style=${{ marginLeft: 'auto' }}>${right}</div>` : null}
  </div>`;

const Body = ({ children, style }) => html`
  <div style=${{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: '12px',
                 ...(style || {}) }}>${children}</div>`;

const Row = ({ children, gap, style }) => html`
  <div style=${{ display: 'flex', alignItems: 'center', gap: (gap || 8) + 'px',
                 flexWrap: 'wrap', ...(style || {}) }}>${children}</div>`;

const Stack = ({ children, gap, style }) => html`
  <div style=${{ display: 'flex', flexDirection: 'column', gap: (gap || 12) + 'px',
                 ...(style || {}) }}>${children}</div>`;

const PageTitle = ({ title, subtitle, right }) => html`
  <div style=${{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: '16px' }}>
    <div style=${{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0 }}>
      <${H.Text} type="H4">${title}<//>
      ${subtitle ? html`<div style=${{ fontSize: '13px', color: C.textSec, overflowWrap: 'anywhere' }}>${subtitle}</div>` : null}
    </div>
    ${right || null}
  </div>`;

const Note = ({ children, tone }) => html`
  <div style=${{ fontSize: '12px', lineHeight: '18px', color: tone === 'warn' ? C.warnText : C.text,
                 background: tone === 'warn' ? C.warnBg : C.line, borderRadius: '8px', padding: '10px 12px' }}>
    ${children}</div>`;

const Muted = ({ children, size }) => html`
  <span style=${{ fontSize: (size || 12) + 'px', color: C.textSec }}>${children}</span>`;


/* Индикатор работы. Показывается только когда сервис действительно занят.
   Сколько осталось, сервис не знает (модель отвечает, когда ответит), поэтому
   полоса бегущая, а не заполняющаяся: она честно говорит «идёт», а не врёт про проценты.
   Это пробел ДС: ProgressBar из HEXA не отрисовывается. */
const Progress = ({ width, onAccent }) => html`
  <div class=${'progress' + (onAccent ? ' progress--on-accent' : '')}
    role="progressbar" aria-label="Идёт работа"
    style=${{ width: width ? width + 'px' : '100%' }}>
    <div class="progress__bar"></div>
  </div>`;

/* --- обязательные состояния ------------------------------------------------ */

/* Ошибка отвечает на три вопроса: что случилось, почему и что делать.
   Подсказку hint бэкенд присылает готовой — например, командой ollama pull. */
const ErrorState = ({ error, onRetry }) => html`
  <${H.SectionMessage} mode="error" title=${(error && error.message) || 'Не получилось'}>
    <${Stack} gap=${8}>
      ${error && error.hint ? html`<div>${error.hint}</div>` : null}
      ${onRetry ? html`<div><${H.Button} mode="secondary" size="small" text="Повторить" onClick=${onRetry} /></div>` : null}
    <//>
  <//>`;

const EmptyState = ({ title, description, action, image }) => html`
  <${Stack} gap=${12} style=${{ alignItems: 'center', padding: '12px 0' }}>
    <${H.Placeholder} image=${image || 'noData'} size="small" title=${title || 'Пусто'} description=${description || ''} />
    ${action || null}
  <//>`;

const LoadingState = ({ title, description }) => html`
  <${Stack} gap=${12} style=${{ alignItems: 'center', padding: '24px 0' }}>
    <${H.Placeholder} image="preparing" size="small" title=${title || 'Считаем…'} description=${description || ''} />
    <${Progress} width=${240} />
  <//>`;

const DisabledState = ({ title, children }) => html`
  <${H.SectionMessage} mode="info" title=${title}>${children}<//>`;

/* Один блок с данными: четыре состояния в одном месте, чтобы ни одно не забыть. */
const Block = ({ state, error, onRetry, empty, loading, disabled, children }) => {
  if (state === 'loading') return html`<${LoadingState} ...${loading || {}} />`;
  if (state === 'error') return html`<${ErrorState} error=${error} onRetry=${onRetry} />`;
  if (state === 'disabled') return html`<${DisabledState} ...${disabled || {}} />`;
  if (state === 'empty') return html`<${EmptyState} ...${empty || {}} />`;
  return children;
};

/* --- загрузка данных ------------------------------------------------------- */

function useAsync(loader, deps, options) {
  const settings = options || {};
  const [value, setValue] = useState({ state: settings.lazy ? 'idle' : 'loading', data: null, error: null });
  const run = useCallback(() => {
    setValue((old) => ({ ...old, state: 'loading' }));
    return Promise.resolve()
      .then(loader)
      .then((data) => { setValue({ state: 'ready', data, error: null }); return data; })
      .catch((error) => { setValue({ state: 'error', data: null, error }); });
  }, deps || []);
  useEffect(() => { if (!settings.lazy) run(); }, [run]);
  return { ...value, reload: run, setData: (data) => setValue({ state: 'ready', data, error: null }) };
}

/* Секунды в «мм:сс» — чтобы ожидание долгой операции было объяснимым. */
function useElapsed(active) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) { setSeconds(0); return undefined; }
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.round((Date.now() - started) / 1000)), 500);
    return () => clearInterval(timer);
  }, [active]);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/* Поля дизайн-системы отдают в onChange то событие, то саму строку — читаем оба случая. */
/* Выпадающий список рисуется в body: иначе его срезает карточка или боковая панель. */
const popupToBody = () => document.body;

const readValue = (input) => {
  if (input === null || input === undefined) return '';
  if (typeof input === 'string' || typeof input === 'number') return String(input);
  if (input.target && input.target.value !== undefined) return input.target.value;
  if (input.value !== undefined) return String(input.value);
  return '';
};

const percent = (value) => `${Math.round(value || 0)}%`;
const plural = (count, one, few, many) => {
  const n = Math.abs(count) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return many;
  if (n1 > 1 && n1 < 5) return few;
  if (n1 === 1) return one;
  return many;
};
const fileName = (path) => String(path || '').split('/').pop();

window.UI = {
  H, html, C, TAG, STATUS, severityTone,
  Card, CardHead, Body, Row, Stack, PageTitle, Note, Muted, Progress,
  Block, ErrorState, EmptyState, LoadingState, DisabledState,
  ELEVATION, PANEL_SHADOW, FOCUS_RING, SELECTED,
  useAsync, useElapsed, percent, plural, fileName, readValue, popupToBody,
  useState, useEffect, useCallback, useRef, useMemo,
};
