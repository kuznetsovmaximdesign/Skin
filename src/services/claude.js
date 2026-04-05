import Anthropic from '@anthropic-ai/sdk';

const anthropic = new Anthropic();

// =============================================
// ПЕРСОНАЛЬНЫЙ КОНТЕКСТ КРИСТИНЫ
// =============================================
const TREATMENT_START = new Date('2026-04-04');
const KRISTINA_USERNAME = 'KrisOsmolovskaya';

function getTodayStr() {
  return new Date().toISOString().split('T')[0];
}

function getKristinaContext() {
  const now = new Date();
  const today = getTodayStr();
  const dayOfTreatment = Math.floor((now - TREATMENT_START) / (1000 * 60 * 60 * 24)) + 1;
  const weekOfTreatment = Math.ceil(dayOfTreatment / 7);

  let phase;
  if (weekOfTreatment <= 2) {
    phase = 'Неделя 1-2: Диагностика действием (Низорал + диета). Наблюдаем реакцию.';
  } else if (weekOfTreatment <= 4) {
    phase = 'Неделя 3-4: Активное лечение. Пора подключать азелаиновую кислоту (Скинорен гель).';
  } else if (weekOfTreatment <= 8) {
    phase = 'Месяц 2: Закрепление. Низорал 2 раза в неделю, продолжаем азелаиновую кислоту.';
  } else {
    phase = 'Месяц 3+: Поддержание. Низорал 1 раз в неделю, работа с постакне и пятнами.';
  }

  return `
⏰ СЕГОДНЯ: ${today}
📅 ДЕНЬ ЛЕЧЕНИЯ: ${dayOfTreatment} (начало: 4 апреля 2026)
📆 НЕДЕЛЯ ЛЕЧЕНИЯ: ${weekOfTreatment}
🔬 ТЕКУЩАЯ ФАЗА: ${phase}

ВАЖНО: Сегодня ${today}, день лечения ${dayOfTreatment}, неделя ${weekOfTreatment}. Не путай!

ДИАГНОЗ: Малассезия-фолликулит (грибковый) + возможно постгормональное акне.
Подтверждается положительной реакцией на кетоконазол.

ИСТОРИЯ:
- 10 лет КОК Ярина — кожа была чистой
- После отмены (~3 года назад) — высыпания на лице, шее, голове
- Ретиноиды исключены

ХАРАКТЕР: мелкие однотипные пустулы, зуд, красное пятно → пузырёк → гной.
Ухудшение после сыра с плесенью и молочных продуктов.

ТЕКУЩЕЕ ЛЕЧЕНИЕ (начато 4 апреля 2026):
- Низорал шампунь на лицо — через день, 5 мин, вечером
- Низорал шампунь на голову — 2 раза в неделю
- Салицило-цинковая паста — точечно на ночь
- Мирамистин — точечно на активные элементы

ПЛАН:
Нед 1-2 (4-17 апр): Низорал + диета
Нед 3-4 (18 апр - 1 мая): + азелаиновая кислота
Месяц 2 (май): Закрепление
Месяц 3 (июнь+): Поддержание + работа с пятнами

ДИЕТА (элиминационная):
НЕЛЬЗЯ: молочное, сахар, дрожжи, плесень, белый хлеб, алкоголь, фастфуд
МОЖНО: мясо, рыба, яйца, овощи, гречка, рис, орехи, оливковое масло, зелёный чай

СТОП-ИНГРЕДИЕНТЫ КОСМЕТИКИ (кормят Malassezia):
Polysorbate 20/60/80, масла (Sunflower, Soybean, Sweet Almond, Shea Butter, Mango Butter, Coconut Oil, Olive Oil), Glyceryl Stearate, Glycol Stearate, Isopropyl Myristate/Isostearate, Ethylhexyl Palmitate, PEG-2/40 Stearate, Sorbitan Oleate/Stearate, эфиры C11-C24.

БЕЗОПАСНЫЕ: Glycerin, Hyaluronic Acid, Niacinamide, Azelaic Acid, Squalane, Panthenol, Salicylic Acid, Zinc PCA, термальная вода, Allantoin, Centella Asiatica, MCT, Mineral Oil, Capric/Caprylic Triglyceride.

ПРОВЕРЕНО ❌: Bioderma Sensibio Defensive/Light, Belif Classic Essence, Payot Vitamin C, Weleda Feigenkaktus, La Roche-Posay Lipikar Baume AP+M, Normalizer Skin Mist, VT Reedle Shot 100/300/PDRN, Скиноклир гель.
ПРОВЕРЕНО ✅: VT Hydrop Reedle Shot 700HL, Низорал, Мирамистин, Салицило-цинковая паста, Термальная вода Avène/LRP, Скинорен гель.

ПРАВИЛО КОСМЕТИКИ: 1 стоп-ингредиент = ❌ НЕЛЬЗЯ. Без компромиссов.
`;
}

// =============================================
// УНИВЕРСАЛЬНЫЕ ФУНКЦИИ
// =============================================

/**
 * Check if user is Kristina
 */
export function isKristina(ctx) {
  return ctx.from?.username === KRISTINA_USERNAME || ctx.from?.id === 588539564;
}

/**
 * Download photo from Telegram and return as base64
 */
export async function downloadPhoto(ctx, photoId) {
  const fileLink = await ctx.telegram.getFileLink(photoId);
  const response = await fetch(fileLink.href);
  const buffer = await response.arrayBuffer();
  return Buffer.from(buffer).toString('base64');
}

/**
 * Single call: classify photo AND analyze it in one request
 * For Kristina — uses full personal context
 * For others — uses their session profile or generic advice
 */
export async function classifyAndAnalyze(base64, ctx, skinHistory = null, mediaType = 'image/jpeg') {
  const kristina = isKristina(ctx);
  const userProfile = ctx.session?.profile;

  let contextBlock;
  if (kristina) {
    contextBlock = `ПОЛЬЗОВАТЕЛЬ: Кристина (@KrisOsmolovskaya) — постоянный клиент.
${getKristinaContext()}`;
  } else if (userProfile) {
    contextBlock = `ПОЛЬЗОВАТЕЛЬ: ${ctx.from.first_name}
⏰ СЕГОДНЯ: ${getTodayStr()}

ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:
${userProfile.diagnosis ? `Диагноз/проблема: ${userProfile.diagnosis}` : 'Диагноз: не указан'}
${userProfile.treatments ? `Текущее лечение: ${userProfile.treatments}` : ''}
${userProfile.allergens ? `Аллергии/непереносимости: ${userProfile.allergens}` : ''}
${userProfile.stopIngredients ? `Стоп-ингредиенты: ${userProfile.stopIngredients}` : ''}
${userProfile.dietRestrictions ? `Диета: ${userProfile.dietRestrictions}` : ''}
${userProfile.notes ? `Заметки: ${userProfile.notes}` : ''}`;
  } else {
    contextBlock = `ПОЛЬЗОВАТЕЛЬ: ${ctx.from.first_name} — новый пользователь, профиль не заполнен.
⏰ СЕГОДНЯ: ${getTodayStr()}
Давай общие рекомендации по акне. В конце ответа ОБЯЗАТЕЛЬНО напиши:
"💡 Чтобы я давал персональные рекомендации, расскажи о своей проблеме с кожей — напиши /profile"`;
  }

  let historyBlock = '';
  if (skinHistory && skinHistory.length > 0) {
    historyBlock = `\nИстория состояния кожи:\n` +
      skinHistory.map(h => `- ${h.date}: ${h.score}/10`).join('\n');
  }

  const system = `Ты — ИИ-дерматолог и косметолог, персональный помощник по уходу за кожей.

${contextBlock}
${historyBlock}

ЗАДАЧА: Определи что на фото (еда / кожа / косметика) и сразу дай полный анализ.

ПЕРВАЯ СТРОКА ответа должна быть РОВНО одно слово-тег: [FOOD], [SKIN] или [COSMETIC].
Если не можешь определить — напиши [UNKNOWN].

После тега — сразу полный анализ:

Если [FOOD]:
🍽 **Что на фото:** (продукты)
✅ **Можно:** (что безопасно и почему)
🔴 **Нельзя:** (что вредит коже и почему)
📊 **Оценка:** X/10
💡 **Совет:** (замены)

Если [SKIN]:
🔍 **Состояние:** (что видно)
📊 **Оценка:** X/10 (10 = чистая кожа)
${skinHistory?.length ? '📈 **Динамика:** (сравнение)\n' : ''}💊 **Рекомендации:** (что делать)

Если [COSMETIC]:
🏷 **Продукт:** (название)
📋 **Состав:** (ингредиенты)
🔴 **Опасные ингредиенты:** (проблемные с пояснением)
✅ **Безопасные:** (хорошие)
📊 **Вердикт: ✅ МОЖНО / ❌ НЕЛЬЗЯ**
💡 **Альтернатива:** (если нельзя)

Если [UNKNOWN]:
Объясни что не удалось определить и попроси прислать другое фото.

Отвечай на русском, дружелюбно и по делу.`;

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 2000,
    system,
    messages: [
      {
        role: 'user',
        content: [
          {
            type: 'image',
            source: { type: 'base64', media_type: mediaType, data: base64 },
          },
          { type: 'text', text: 'Определи что на фото и проанализируй.' },
        ],
      },
    ],
  });

  const fullText = response.content[0].text;

  // Extract type tag from first line
  const tagMatch = fullText.match(/^\[?(FOOD|SKIN|COSMETIC|UNKNOWN)\]?/i);
  const type = tagMatch ? tagMatch[1].toLowerCase() : 'unknown';

  // Remove the tag line from response
  const text = fullText.replace(/^\[?(FOOD|SKIN|COSMETIC|UNKNOWN)\]?\s*/i, '').trim();

  // Extract scores
  let score = null;
  let safetyScore = null;
  let productName = null;

  if (type === 'skin') {
    const m = text.match(/Оценка[^:]*:\s*(\d+)/);
    score = m ? parseInt(m[1]) : null;
  } else if (type === 'cosmetic') {
    const m = text.match(/(?:МОЖНО|НЕЛЬЗЯ)/);
    safetyScore = m ? (m[0] === 'МОЖНО' ? 10 : 0) : null;
    const n = text.match(/Продукт:\s*\*?\*?(.+?)(?:\*?\*?\n|$)/);
    productName = n ? n[1].trim() : null;
  } else if (type === 'food') {
    const m = text.match(/Оценка[^:]*:\s*(\d+)/);
    score = m ? parseInt(m[1]) : null;
  }

  return { type, text, score, safetyScore, productName };
}

/**
 * Chat — personal consultant
 * For Kristina uses full context, for others uses their profile
 */
export async function chat(userMessage, ctx, messageHistory = []) {
  const kristina = isKristina(ctx);
  const userProfile = ctx.session?.profile;

  let contextBlock;
  if (kristina) {
    contextBlock = `ПОЛЬЗОВАТЕЛЬ: Кристина (@KrisOsmolovskaya)
${getKristinaContext()}`;
  } else if (userProfile) {
    contextBlock = `ПОЛЬЗОВАТЕЛЬ: ${ctx.from.first_name}
⏰ СЕГОДНЯ: ${getTodayStr()}
ПРОФИЛЬ:
${userProfile.diagnosis ? `Проблема: ${userProfile.diagnosis}` : 'Не указано'}
${userProfile.treatments ? `Лечение: ${userProfile.treatments}` : ''}
${userProfile.allergens ? `Аллергии: ${userProfile.allergens}` : ''}
${userProfile.stopIngredients ? `Стоп-ингредиенты: ${userProfile.stopIngredients}` : ''}
${userProfile.dietRestrictions ? `Диета: ${userProfile.dietRestrictions}` : ''}
${userProfile.notes ? `Заметки: ${userProfile.notes}` : ''}`;
  } else {
    contextBlock = `ПОЛЬЗОВАТЕЛЬ: ${ctx.from.first_name} — новый пользователь.
⏰ СЕГОДНЯ: ${getTodayStr()}
Профиль не заполнен. Давай общие рекомендации.
Если вопрос требует персонализации — предложи заполнить /profile.`;
  }

  const system = `Ты — персональный консультант по коже, питанию и уходу.

${contextBlock}

Правила:
- Обращайся на "ты", дружелюбно и по делу
- Если вопрос про еду — учитывай диету пользователя
- Если вопрос про косметику — проверяй стоп-ингредиенты
- Если вопрос про кожу — учитывай диагноз и лечение
- Ты НЕ ставишь диагнозы, рекомендуешь дерматолога при серьёзном
- Отвечай на русском, коротко и по существу`;

  const messages = [
    ...messageHistory,
    { role: 'user', content: userMessage },
  ];

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1500,
    system,
    messages,
  });

  return response.content[0].text;
}
