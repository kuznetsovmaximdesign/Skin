require('./env');
const { Telegraf } = require('telegraf');
const { addEntry, getEntries, getEntriesByDate, getSkinHistory, getProfile, saveProfile } = require('./db/database');
const { analyzePhotoSingle, chat } = require('./services/claude');
const https = require('https');
const http = require('http');

const bot = new Telegraf(process.env.TELEGRAM_BOT_TOKEN);

// ID Кристины (username)
const KRISTINA_USERNAME = 'KrisOsmolovskaya';

// Хранилище истории чатов (в памяти)
const conversationHistory = {};
// Хранилище состояний профиля
const profileStates = {};

function isKristina(ctx) {
  return ctx.from?.username === KRISTINA_USERNAME;
}

function getChatHistory(userId) {
  if (!conversationHistory[userId]) conversationHistory[userId] = [];
  return conversationHistory[userId];
}

function addToHistory(userId, role, content) {
  const history = getChatHistory(userId);
  history.push({ role, content });
  // Храним максимум 20 сообщений (10 пар)
  if (history.length > 20) {
    conversationHistory[userId] = history.slice(-20);
  }
}

// /start
bot.start((ctx) => {
  const name = ctx.from.first_name || 'друг';
  if (isKristina(ctx)) {
    ctx.reply(
      `Привет, Кристина! 👋\n\nЯ твой персональный помощник по уходу за кожей.\n\n` +
        `📸 Отправь мне фото — я сам определю что это:\n` +
        `• 🍽 Еда — проверю по твоей элиминационной диете\n` +
        `• 🔍 Кожа — оценю состояние и динамику лечения\n` +
        `• 🧴 Косметика — проверю INCI на стоп-ингредиенты\n\n` +
        `💬 Или просто напиши вопрос — я отвечу как консультант\n\n` +
        `📓 /diary — дневник по датам`
    );
  } else {
    ctx.reply(
      `Привет, ${name}! 👋\n\nЯ ИИ-помощник по уходу за кожей.\n\n` +
        `📸 Отправь фото (еда/кожа/косметика) — я проанализирую\n` +
        `💬 Задай вопрос текстом\n` +
        `👤 /profile — заполни профиль для персональных рекомендаций\n` +
        `📓 /diary — дневник записей`
    );
  }
});

// /profile — заполнение профиля для не-Кристины
bot.command('profile', (ctx) => {
  if (isKristina(ctx)) {
    return ctx.reply('Кристина, твой профиль уже настроен! 😊');
  }

  const userId = ctx.from.id;
  profileStates[userId] = { step: 'problem' };
  ctx.reply(
    '👤 Давай заполним твой профиль!\n\n' +
      'Шаг 1/5: Какая у тебя проблема с кожей?\n' +
      '(акне, розацеа, малассезия, чувствительная кожа и т.д.)'
  );
});

// /diary
bot.command('diary', (ctx) => {
  const userId = ctx.from.id;
  const args = ctx.message.text.split(' ').slice(1);
  const dateStr = args[0] || new Date().toISOString().split('T')[0];

  const entries = getEntriesByDate(userId, dateStr);
  if (entries.length === 0) {
    return ctx.reply(`📓 За ${dateStr} записей нет.\n\nОтправь фото чтобы добавить запись!`);
  }

  let response = `📓 Дневник за ${dateStr}:\n\n`;
  entries.forEach((entry, i) => {
    const time = new Date(entry.date).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    const typeEmoji = { food: '🍽', skin: '🔍', cosmetic: '🧴' }[entry.type] || '📝';
    response += `${i + 1}. ${typeEmoji} ${time}\n${entry.analysis.substring(0, 100)}...\n\n`;
  });

  // Динамика кожи
  const skinEntries = getSkinHistory(userId);
  if (skinEntries.length > 1) {
    response += `\n📊 Записей о коже: ${skinEntries.length}`;
  }

  ctx.reply(response);
});

// Обработка фото
bot.on('photo', async (ctx) => {
  const userId = ctx.from.id;

  try {
    await ctx.reply('⏳ Анализирую фото...');

    // Получаем файл
    const photo = ctx.message.photo[ctx.message.photo.length - 1];
    const file = await ctx.telegram.getFile(photo.file_id);
    const fileUrl = `https://api.telegram.org/file/bot${process.env.TELEGRAM_BOT_TOKEN}/${file.file_path}`;

    // Скачиваем как base64
    const base64 = await downloadAsBase64(fileUrl);
    const mediaType = file.file_path.endsWith('.png') ? 'image/png' : 'image/jpeg';

    // Определяем профиль
    const kristina = isKristina(ctx);
    const userProfile = kristina ? null : getProfile(userId);

    // Один вызов — определение типа + анализ
    const { text, type } = await analyzePhotoSingle(base64, mediaType, kristina, userProfile);

    // Сохраняем в дневник
    addEntry(userId, type, text, photo.file_id);

    // Добавляем в историю чата
    addToHistory(userId, 'user', '[Отправлено фото]');
    addToHistory(userId, 'assistant', text);

    await ctx.reply(text);
  } catch (error) {
    console.error('Photo analysis error:', error);
    await ctx.reply('❌ Ошибка при анализе фото. Попробуй ещё раз.');
  }
});

// Обработка текстовых сообщений
bot.on('text', async (ctx) => {
  const userId = ctx.from.id;
  const message = ctx.message.text;

  // Проверяем заполнение профиля
  if (profileStates[userId]) {
    return handleProfileStep(ctx, userId, message);
  }

  try {
    await ctx.reply('💬 Думаю...');

    const kristina = isKristina(ctx);
    const userProfile = kristina ? null : getProfile(userId);
    const history = getChatHistory(userId);

    const response = await chat(message, kristina, history, userProfile);

    addToHistory(userId, 'user', message);
    addToHistory(userId, 'assistant', response);

    await ctx.reply(response);
  } catch (error) {
    console.error('Chat error:', error);
    await ctx.reply('❌ Ошибка. Попробуй ещё раз.');
  }
});

// Пошаговое заполнение профиля
function handleProfileStep(ctx, userId, message) {
  const state = profileStates[userId];

  switch (state.step) {
    case 'problem':
      state.problem = message;
      state.step = 'treatment';
      ctx.reply('Шаг 2/5: Какое текущее лечение? (или "нет")');
      break;
    case 'treatment':
      state.treatment = message;
      state.step = 'allergies';
      ctx.reply('Шаг 3/5: Есть ли аллергии? (или "нет")');
      break;
    case 'allergies':
      state.allergies = message;
      state.step = 'diet';
      ctx.reply('Шаг 4/5: Соблюдаешь ли диету? Какую? (или "нет")');
      break;
    case 'diet':
      state.diet = message;
      state.step = 'notes';
      ctx.reply('Шаг 5/5: Дополнительные заметки? (или "нет")');
      break;
    case 'notes':
      state.notes = message;
      // Сохраняем профиль
      const profile = {
        problem: state.problem,
        treatment: state.treatment,
        allergies: state.allergies,
        diet: state.diet,
        notes: state.notes,
      };
      saveProfile(userId, profile);
      delete profileStates[userId];
      ctx.reply(
        '✅ Профиль сохранён!\n\nТеперь отправляй фото или задавай вопросы — рекомендации будут персональными.'
      );
      break;
  }
}

// Скачивание файла как base64
function downloadAsBase64(url) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https') ? https : http;
    client.get(url, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const buffer = Buffer.concat(chunks);
        resolve(buffer.toString('base64'));
      });
      res.on('error', reject);
    });
  });
}

// Глобальный обработчик ошибок
bot.catch((err, ctx) => {
  console.error('Bot error:', err);
  ctx.reply('⚠️ Произошла ошибка, попробуй ещё раз.').catch(() => {});
});

// Запуск
bot.launch().then(() => {
  console.log('🤖 Acne Skin Bot запущен!');
});

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
