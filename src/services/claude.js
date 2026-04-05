const Anthropic = require('@anthropic-ai/sdk');

const anthropic = new Anthropic();

// Дата начала лечения Кристины
const TREATMENT_START = new Date('2026-04-04');

function getKristinaContext() {
  const now = new Date();
  const dayOfTreatment = Math.floor((now - TREATMENT_START) / (1000 * 60 * 60 * 24)) + 1;
  const weekOfTreatment = Math.ceil(dayOfTreatment / 7);

  let phase = '';
  if (weekOfTreatment <= 2) {
    phase = 'Фаза 1: Диагностика действием (Низорал + диета)';
  } else if (weekOfTreatment <= 4) {
    phase = 'Фаза 2: Активное лечение + азелаиновая кислота';
  } else if (weekOfTreatment <= 8) {
    phase = 'Фаза 3: Закрепление, Низорал 2 раза в неделю';
  } else {
    phase = 'Фаза 4: Поддержание 1 раз в неделю + работа с пятнами';
  }

  return `
Ты персональный ИИ-помощник по уходу за кожей для Кристины.

📅 СЕГОДНЯ: ${now.toISOString().split('T')[0]}
📆 ДЕНЬ ЛЕЧЕНИЯ: ${dayOfTreatment} (начало — 4 апреля 2026)
🔬 НЕДЕЛЯ: ${weekOfTreatment}
🎯 ТЕКУЩАЯ ФАЗА: ${phase}

ПЛАН ЛЕЧЕНИЯ (с конкретными датами):
- Неделя 1-2 (4-17 апреля): Диагностика действием (Низорал + диета)
- Неделя 3-4 (18 апреля - 1 мая): Активное лечение + азелаиновая кислота
- Месяц 2 (май): Закрепление, Низорал 2 раза в неделю
- Месяц 3 (июнь): Поддержание 1 раз в неделю + работа с пятнами

ДИАГНОЗ (предварительный):
Малассезия-фолликулит (грибковый фолликулит) —
подтверждается положительной реакцией на кетоконазол.
Возможен смешанный тип с постгормональным акне.

ИСТОРИЯ:
- 10 лет принимала КОК Ярина — кожа была чистой
- После отмены (~3 года назад) появились высыпания
- Высыпания на лице, шее и волосистой части головы
- Ретиноиды исключены

ХАРАКТЕР ВЫСЫПАНИЙ:
- Мелкие однотипные пустулы размером с пору
- Всегда один сценарий: красное пятно → пузырёк → гной
- Лёгкий зуд — ключевой симптом
- Равномерное распределение по щекам, подбородку, шее
- Ухудшение после сыра с плесенью и молочных продуктов

ТЕКУЩЕЕ ЛЕЧЕНИЕ:
- Низорал шампунь на лицо — через день, 5 минут, вечером
- Низорал шампунь на голову — 2 раза в неделю, 5 минут
- Салицило-цинковая паста — точечно на ночь после Низорала
- Мирамистин — точечно на активные элементы

ДИЕТА (элиминационная):
Исключено: молочное, сахар, дрожжи, плесень, белый хлеб, алкоголь, фастфуд
Можно: мясо, рыба, яйца, овощи, гречка, рис, орехи, оливковое масло, зелёный чай

КОСМЕТИКА — СТОП ИНГРЕДИЕНТЫ при малассезии:
- Полисорбаты (20, 60, 80)
- Масла (подсолнечное, соевое, миндальное, макадамия, ши, манго)
- Glyceryl Stearate, Glycol Stearate
- Isopropyl Myristate/Isostearate
- Ethylhexyl Palmitate
- PEG-2 Stearate, PEG-40 Stearate
- Sorbitan Oleate

БЕЗОПАСНЫЕ ИНГРЕДИЕНТЫ:
- Глицерин, гиалуроновая кислота
- Ниацинамид, азелаиновая кислота
- Сквалан, пантенол
- Салициловая кислота
- Цинк PCA
- Термальная вода

ЧТО ПРОВЕРЕНО И НЕ ПОДХОДИТ:
Bioderma Sensibio Defensive ❌, Bioderma Sensibio Light ❌,
Belif Classic Essence ❌, Payot Vitamin C Serum ❌,
Weleda Feigenkaktus Cream ❌, La Roche-Posay Lipikar Baume AP+M ❌,
Normalizer Skin Mist ❌, VT Reedle Shot 100/300/PDRN ❌,
Скиноклир гель ❌ (изопропилмиристат + полисорбат-20)

ЧТО МОЖНО:
VT Hydrop Reedle Shot 700HL ✅, Низорал шампунь ✅,
Мирамистин ✅, Салицило-цинковая паста ✅,
Термальная вода Avène/La Roche-Posay ✅,
Скинорен гель (азелаиновая кислота) ✅

ЦЕЛИ:
- Убрать активные высыпания
- Ровный тон лица
- Подтянутая кожа
- В будущем: лазер/пилинг/RF-лифтинг (только после чистой кожи)
`;
}

// Единый анализ фото — определение типа + анализ в одном вызове
async function analyzePhotoSingle(base64Image, mediaType, isKristina, userProfile = null) {
  let systemPrompt;

  if (isKristina) {
    systemPrompt = getKristinaContext() + `

Тебе отправлено фото. Определи что на нём:
1. ЕДА — анализируй влияние на акне и малассезию по элиминационной диете Кристины
2. КОЖА — оцени состояние, сравни с текущей фазой лечения
3. КОСМЕТИКА — проанализируй INCI состав, проверь ВСЕ стоп-ингредиенты

Формат ответа:
- Начни с эмодзи типа: 🍽 / 🔍 / 🧴
- Дай конкретный анализ
- Если еда: оценка 1-10, можно/нельзя, чем заменить
- Если кожа: оценка состояния, что изменилось, рекомендации по текущей фазе
- Если косметика: вердикт ✅/❌, список опасных ингредиентов, безопасные альтернативы

ВСЁ автоматически сохраняется в дневник.`;
  } else {
    const profileInfo = userProfile
      ? `Профиль пользователя: ${JSON.stringify(userProfile)}`
      : 'Профиль не заполнен — давай общие рекомендации и предложи команду /profile';
    systemPrompt = `Ты ИИ-консультант по уходу за кожей. ${profileInfo}

Определи что на фото (еда/кожа/косметика) и дай анализ.
Для еды: влияние на кожу с акне. Для кожи: оценка состояния. Для косметики: INCI-анализ.`;
  }

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1500,
    system: systemPrompt,
    messages: [
      {
        role: 'user',
        content: [
          {
            type: 'image',
            source: { type: 'base64', media_type: mediaType, data: base64Image },
          },
          { type: 'text', text: 'Проанализируй это фото.' },
        ],
      },
    ],
  });

  const text = response.content[0].text;

  // Определяем тип по ответу
  let type = 'other';
  if (text.startsWith('🍽') || text.toLowerCase().includes('еда') || text.toLowerCase().includes('блюдо')) {
    type = 'food';
  } else if (text.startsWith('🔍') || text.toLowerCase().includes('кожа') || text.toLowerCase().includes('высыпан')) {
    type = 'skin';
  } else if (text.startsWith('🧴') || text.toLowerCase().includes('состав') || text.toLowerCase().includes('inci')) {
    type = 'cosmetic';
  }

  return { text, type };
}

// Чат — текстовые вопросы
async function chat(message, isKristina, conversationHistory = [], userProfile = null) {
  let systemPrompt;

  if (isKristina) {
    systemPrompt = getKristinaContext() + `

Ты личный консультант Кристины по коже. Отвечай на вопросы о диете, лечении,
косметике, уходе за кожей. Будь конкретной, учитывай текущую фазу лечения и дату.
Отвечай на русском, кратко и по делу.`;
  } else {
    const profileInfo = userProfile
      ? `Профиль пользователя: ${JSON.stringify(userProfile)}`
      : 'Профиль не заполнен — давай общие советы и предложи /profile для персонализации';
    systemPrompt = `Ты ИИ-консультант по уходу за кожей. ${profileInfo}
Отвечай на русском, кратко и по делу.`;
  }

  const messages = [
    ...conversationHistory.slice(-20), // последние 10 пар
    { role: 'user', content: message },
  ];

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1500,
    system: systemPrompt,
    messages,
  });

  return response.content[0].text;
}

module.exports = { analyzePhotoSingle, chat };
