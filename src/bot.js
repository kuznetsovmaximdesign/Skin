// Load .env FIRST — before any other imports that use env vars
import './env.js';

import { Telegraf, session } from 'telegraf';
import { classifyAndAnalyze, downloadPhoto, chat, isKristina } from './services/claude.js';
import { addFoodEntry, addSkinEntry, addCosmeticEntry, getSkinHistory } from './db/database.js';
import { setupDiaryHandler } from './handlers/diary.js';

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
if (!BOT_TOKEN) {
  console.error('❌ TELEGRAM_BOT_TOKEN not set');
  process.exit(1);
}
if (!process.env.ANTHROPIC_API_KEY) {
  console.error('❌ ANTHROPIC_API_KEY not set');
  process.exit(1);
}

const bot = new Telegraf(BOT_TOKEN);

bot.use(session({ defaultSession: () => ({ chatHistory: [], profile: null, profileStep: null }) }));

// /start
bot.start((ctx) => {
  const kristina = isKristina(ctx);
  if (kristina) {
    ctx.reply(
      `Привет, Кристина! 💜\n\n` +
      `Я — твой персональный консультант по коже.\n\n` +
      `📸 Отправь фото — я сам определю:\n` +
      `🍽 Еда → проверю по твоей диете\n` +
      `🔍 Кожа → оценю состояние + динамику\n` +
      `🧴 Косметика → проверю INCI на малассезию\n\n` +
      `💬 Задай любой вопрос — по уходу, питанию, лечению\n` +
      `📓 /diary — дневник\n\n` +
      `Я знаю твой диагноз, план лечения и диету — просто пиши!`,
      { reply_markup: { keyboard: [[{ text: '📓 Дневник' }]], resize_keyboard: true } }
    );
  } else {
    ctx.reply(
      `Привет, ${ctx.from.first_name}! 👋\n\n` +
      `Я — ИИ-помощник по уходу за кожей.\n\n` +
      `📸 Отправь фото — я определю тип и проанализирую:\n` +
      `🍽 Еда → что полезно/вредно для кожи\n` +
      `🔍 Кожа → оценка состояния\n` +
      `🧴 Косметика → INCI-анализ состава\n\n` +
      `💬 Задай любой вопрос текстом\n\n` +
      `📋 /profile — заполни профиль для персональных рекомендаций\n` +
      `📓 /diary — дневник`,
      { reply_markup: { keyboard: [[{ text: '📓 Дневник' }, { text: '📋 Профиль' }]], resize_keyboard: true } }
    );
  }
});

// /profile — onboarding for new users
bot.command('profile', startProfile);
bot.hears('📋 Профиль', startProfile);

function startProfile(ctx) {
  if (isKristina(ctx)) {
    return ctx.reply('Кристина, твой профиль уже загружен! 💜');
  }
  ctx.session.profileStep = 'diagnosis';
  ctx.reply(
    '📋 **Давай заполним твой профиль!**\n\n' +
    'Шаг 1/5: Какая у тебя проблема с кожей?\n' +
    '(например: акне, розацеа, малассезия, просто хочу следить за кожей)\n\n' +
    'Напиши или отправь /skip чтобы пропустить.',
    { parse_mode: 'Markdown' }
  );
}

const PROFILE_STEPS = {
  diagnosis: {
    field: 'diagnosis',
    next: 'treatments',
    prompt: 'Шаг 2/5: Какое лечение сейчас используешь?\n(препараты, процедуры, или /skip)',
  },
  treatments: {
    field: 'treatments',
    next: 'allergens',
    prompt: 'Шаг 3/5: Есть аллергии или непереносимости?\n(продукты, компоненты косметики, или /skip)',
  },
  allergens: {
    field: 'allergens',
    next: 'dietRestrictions',
    prompt: 'Шаг 4/5: Какая диета? Что исключено?\n(например: без молочки, без сахара, или /skip)',
  },
  dietRestrictions: {
    field: 'dietRestrictions',
    next: 'notes',
    prompt: 'Шаг 5/5: Что-то ещё важное?\n(стоп-ингредиенты, особенности кожи, или /skip)',
  },
  notes: {
    field: 'notes',
    next: null,
    prompt: null,
  },
};

function handleProfileStep(ctx, text) {
  const step = PROFILE_STEPS[ctx.session.profileStep];
  if (!step) return false;

  if (!ctx.session.profile) ctx.session.profile = {};

  if (text !== '/skip') {
    ctx.session.profile[step.field] = text;
  }

  if (step.next) {
    ctx.session.profileStep = step.next;
    ctx.reply(step.prompt);
  } else {
    ctx.session.profileStep = null;
    ctx.reply(
      '✅ **Профиль сохранён!**\n\n' +
      'Теперь я буду давать персональные рекомендации.\n' +
      'Отправь фото или задай вопрос!',
      { parse_mode: 'Markdown' }
    );
  }
  return true;
}

// Keyboard buttons
bot.hears('📓 Дневник', (ctx) => {
  const today = new Date().toISOString().split('T')[0];
  const yesterday = (() => { const d = new Date(); d.setDate(d.getDate() - 1); return d.toISOString().split('T')[0]; })();
  return ctx.reply('📓 **Дневник**\n\nВыбери:', {
    parse_mode: 'Markdown',
    reply_markup: {
      inline_keyboard: [
        [{ text: `📅 Сегодня`, callback_data: `diary_${today}` }],
        [{ text: '📅 Вчера', callback_data: `diary_${yesterday}` }],
        [{ text: '📈 Динамика кожи', callback_data: 'diary_history' }],
      ],
    },
  });
});

setupDiaryHandler(bot);

// PHOTO — single API call: classify + analyze
bot.on('photo', async (ctx) => {
  const photos = ctx.message.photo;
  const photoId = photos[photos.length - 1].file_id;

  const statusMsg = await ctx.reply('🔄 Анализирую фото...');

  try {
    const base64 = await downloadPhoto(ctx, photoId);
    const skinHistory = getSkinHistory(ctx.from.id, 5);

    const result = await classifyAndAnalyze(base64, ctx, skinHistory);

    await ctx.telegram.deleteMessage(ctx.chat.id, statusMsg.message_id).catch(() => {});

    // Save to diary
    switch (result.type) {
      case 'food':
        addFoodEntry(ctx.from.id, photoId, result.text);
        break;
      case 'skin':
        addSkinEntry(ctx.from.id, photoId, result.text, result.score);
        break;
      case 'cosmetic':
        addCosmeticEntry(ctx.from.id, photoId, result.productName, result.text, result.safetyScore);
        break;
    }

    await ctx.reply(result.text, { parse_mode: 'Markdown' });

    // Show skin trend
    if (result.type === 'skin' && skinHistory.length >= 2 && result.score) {
      const scores = skinHistory.map(h => h.score).filter(Boolean);
      const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
      const trend = result.score > avg ? '📈 Улучшение!' : result.score < avg ? '📉 Ухудшение' : '➡️ Стабильно';
      await ctx.reply(`${trend} Средняя: ${avg.toFixed(1)}/10`);
    }
  } catch (err) {
    console.error('Photo error:', err);
    await ctx.telegram.deleteMessage(ctx.chat.id, statusMsg.message_id).catch(() => {});
    await ctx.reply('❌ Не удалось обработать фото. Попробуй ещё раз.');
  }
});

// TEXT — chat or profile onboarding
bot.on('text', async (ctx) => {
  const text = ctx.message.text;

  if (text.startsWith('/')) return;
  if (text === '📓 Дневник' || text === '📋 Профиль') return;
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return;

  // Profile onboarding in progress
  if (ctx.session.profileStep) {
    return handleProfileStep(ctx, text);
  }

  await ctx.sendChatAction('typing');

  try {
    if (!ctx.session.chatHistory) ctx.session.chatHistory = [];

    const answer = await chat(text, ctx, ctx.session.chatHistory);

    ctx.session.chatHistory.push({ role: 'user', content: text });
    ctx.session.chatHistory.push({ role: 'assistant', content: answer });
    if (ctx.session.chatHistory.length > 20) {
      ctx.session.chatHistory = ctx.session.chatHistory.slice(-20);
    }

    await ctx.reply(answer, { parse_mode: 'Markdown' });
  } catch (err) {
    console.error('Chat error:', err);
    try {
      const answer = await chat(text, ctx);
      await ctx.reply(answer);
    } catch {
      await ctx.reply('❌ Не удалось ответить. Попробуй переформулировать.');
    }
  }
});

bot.help((ctx) => {
  ctx.reply(
    '📸 **Отправь фото** — бот сам определит тип\n' +
    '💬 **Напиши текстом** — отвечу как консультант\n' +
    '📋 /profile — заполнить профиль\n' +
    '📓 /diary — дневник записей',
    { parse_mode: 'Markdown' }
  );
});

bot.catch((err, ctx) => {
  console.error('Bot error:', err.message);
  ctx.reply('❌ Произошла ошибка. Попробуй ещё раз.').catch(() => {});
});

bot.launch().then(() => {
  console.log('🤖 Acne Skin Bot запущен!');
});

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
