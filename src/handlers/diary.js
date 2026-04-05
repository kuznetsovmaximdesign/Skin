import { getFoodDiary, getSkinDiary, getDiarySummary, getSkinHistory } from '../db/database.js';

export function setupDiaryHandler(bot) {
  bot.command('diary', (ctx) => {
    const today = new Date().toISOString().split('T')[0];
    ctx.reply(
      '📓 **Дневник кожи и питания**\n\n' +
      'Выбери, что хочешь посмотреть:',
      {
        parse_mode: 'Markdown',
        reply_markup: {
          inline_keyboard: [
            [{ text: `📅 Сегодня (${today})`, callback_data: `diary_${today}` }],
            [{ text: '📅 Вчера', callback_data: `diary_${getYesterday()}` }],
            [{ text: '📈 Динамика кожи (10 записей)', callback_data: 'diary_history' }],
          ],
        },
      }
    );
  });

  bot.action(/^diary_(\d{4}-\d{2}-\d{2})$/, async (ctx) => {
    const date = ctx.match[1];
    await ctx.answerCbQuery();
    await showDayDiary(ctx, date);
  });

  bot.action('diary_history', async (ctx) => {
    await ctx.answerCbQuery();
    await showSkinHistory(ctx);
  });

  // Allow user to send date in format YYYY-MM-DD after /diary
  bot.hears(/^(\d{4}-\d{2}-\d{2})$/, async (ctx) => {
    await showDayDiary(ctx, ctx.match[1]);
  });
}

async function showDayDiary(ctx, date) {
  const userId = ctx.from.id;
  const summary = getDiarySummary(userId, date);
  const foodEntries = getFoodDiary(userId, date);
  const skinEntries = getSkinDiary(userId, date);

  if (summary.food === 0 && summary.skin === 0) {
    await ctx.reply(`📓 На **${date}** записей нет.\n\nОтправь фото еды или кожи, чтобы добавить!`, {
      parse_mode: 'Markdown',
    });
    return;
  }

  let msg = `📓 **Дневник за ${date}**\n\n`;

  if (foodEntries.length > 0) {
    msg += `🍽 **Питание** (${foodEntries.length} записей):\n`;
    foodEntries.forEach((entry, i) => {
      const shortAnalysis = entry.analysis.split('\n')[0];
      msg += `${i + 1}. ${shortAnalysis}\n`;
    });
    msg += '\n';
  }

  if (skinEntries.length > 0) {
    msg += `🔍 **Кожа** (${skinEntries.length} записей):\n`;
    skinEntries.forEach((entry, i) => {
      const time = new Date(entry.createdAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
      msg += `${i + 1}. Оценка: ${entry.score || '—'}/10 (${time})\n`;
    });
    if (summary.skinAvgScore) {
      msg += `\n📊 Средняя оценка за день: ${summary.skinAvgScore.toFixed(1)}/10`;
    }
  }

  await ctx.reply(msg, { parse_mode: 'Markdown' });
}

async function showSkinHistory(ctx) {
  const history = getSkinHistory(ctx.from.id, 10);

  if (history.length === 0) {
    await ctx.reply('📈 Пока нет записей о состоянии кожи. Отправь фото через /skin!');
    return;
  }

  let msg = '📈 **Динамика состояния кожи:**\n\n';

  history.forEach((entry) => {
    const bar = entry.score ? '█'.repeat(entry.score) + '░'.repeat(10 - entry.score) : '—';
    msg += `📅 ${entry.date}: ${bar} ${entry.score || '?'}/10\n`;
  });

  const scores = history.map(h => h.score).filter(Boolean);
  if (scores.length >= 2) {
    const recent = scores.slice(0, Math.ceil(scores.length / 2));
    const older = scores.slice(Math.ceil(scores.length / 2));
    const recentAvg = recent.reduce((a, b) => a + b, 0) / recent.length;
    const olderAvg = older.reduce((a, b) => a + b, 0) / older.length;

    msg += '\n';
    if (recentAvg > olderAvg + 0.5) {
      msg += '✅ **Тенденция: улучшение!** Кожа становится лучше.';
    } else if (recentAvg < olderAvg - 0.5) {
      msg += '⚠️ **Тенденция: ухудшение.** Обрати внимание на питание и уход.';
    } else {
      msg += '➡️ **Тенденция: стабильно.** Состояние кожи не меняется.';
    }
  }

  await ctx.reply(msg, { parse_mode: 'Markdown' });
}

function getYesterday() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().split('T')[0];
}
