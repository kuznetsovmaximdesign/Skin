export const FORMATS = {
  A: { label: 'Озвучка', color: 'var(--format-a)', short: 'A' },
  B: { label: 'Разбор', color: 'var(--format-b)', short: 'B' },
  C: { label: 'Карусель', color: 'var(--format-c)', short: 'C' },
};

export const CATEGORIES = {
  b: { label: 'Бытовая', color: 'var(--cat-bytovaya)', emoji: '🏠' },
  d: { label: 'Даты', color: 'var(--cat-daty)', emoji: '📅' },
  p: { label: 'Прочее', color: 'var(--cat-prochee)', emoji: '💡' },
};

export const TABS = [
  { id: 'topics', label: 'Темы', icon: '📋' },
  { id: 'archive', label: 'Архив', icon: '📦' },
  { id: 'calendar', label: 'Календарь', icon: '📆' },
];

export const DEFAULT_STEPS = [
  { id: 1, text: 'Написать хук', done: false },
  { id: 2, text: 'Записать озвучку', done: false },
  { id: 3, text: 'Смонтировать', done: false },
  { id: 4, text: 'Опубликовать', done: false },
];

export function createIdea(data = {}) {
  return {
    id: Date.now() + Math.random().toString(36).slice(2, 8),
    title: data.t || data.title || 'Новая идея',
    format: data.f || data.format || 'A',
    category: data.cat || data.category || 'b',
    week: data.w ?? data.week ?? 0,
    description: data.d || data.description || '',
    steps: data.steps || DEFAULT_STEPS.map((s) => ({ ...s, id: Date.now() + Math.random() })),
    archived: false,
    collapsed: false,
    createdAt: new Date().toISOString(),
  };
}

export const SAMPLE_IDEAS = [
  createIdea({
    t: 'Квартира 13 — страшно?',
    f: 'A',
    cat: 'b',
    w: 0,
    d: '<b>Хук:</b> Квартира 13. Все боятся — а зря.',
  }),
  createIdea({
    t: 'Рождённые 22 числа',
    f: 'A',
    cat: 'd',
    w: 0,
    d: '<b>Хук:</b> Самые сложные люди — рождённые 22.',
  }),
  createIdea({
    t: '5 знаков зодиака-манипуляторов',
    f: 'B',
    cat: 'p',
    w: 1,
    d: '<b>Хук:</b> Эти знаки управляют тобой незаметно.',
  }),
  createIdea({
    t: 'Фэн-шуй рабочего стола',
    f: 'C',
    cat: 'b',
    w: 1,
    d: '<b>Хук:</b> Твой стол блокирует деньги.',
  }),
];
