import { getEntriesByDate, getSkinHistory } from '../db/database.js';

export function setupDiaryHandler(bot) {
  // /diary command
  bot.command('diary', (ctx) => {
    const today = new Date().toISOString().split('T')[0];
    const yesterday = (() => { const d = new Date(); d.setDate(d.getDate() - 1); return d.toISOString().split('T')[0]; })();

    ctx.reply('📓 **Дневник**\n\nВыбери:', {
      parse_mode: 'Markdown',
      reply_markup: {
        inline_keyboard: [
          [{ text: '📅 Сегодня', callback_data: `diary_${today}` }],
          [{ text: '📅 Вчера', callback_data: `diary_${yesterday}` }],
          [{ text: '📈 Динамика кожи', callback_data: 'diary_history' }],
        ],
      },
    });
  });

  // Diary date callback
  bot.action(/^diary_(\d{4}-\d{2}-\d{2})$/, (ctx) => {
    const dateStr = ctx.match[1];
    const userId = ctx.from.id;
    const entries = getEntriesByDate(userId, dateStr);

    if (entries.length === 0) {
      return ctx.answerCbQuery().then(() =>
        ctx.editMessageText(`📓 За ${dateStr} записей нет.\n\nОтправь фото чтобы добавить!`)
      );
    }

    let text = `📓 **Дневник за ${dateStr}:**\n\n`;
    entries.forEach((entry, i) => {
      const time = new Date(entry.createdAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
      const emoji = { food: '🍽', skin: '🔍', cosmetic: '🧴' }[entry.type] || '📝';
      const summary = entry.analysis.substring(0, 120).replace(/\n/g, ' ');
      text += `${i + 1}. ${emoji} ${time}\n${summary}...\n\n`;
    });

    ctx.answerCbQuery();
    ctx.editMessageText(text, { parse_mode: 'Markdown' });
  });

  // Skin history callback
  bot.action('diary_history', (ctx) => {
    const userId = ctx.from.id;
    const history = getSkinHistory(userId, 10);

    if (history.length === 0) {
      return ctx.answerCbQuery().then(() =>
        ctx.editMessageText('📈 Нет записей о коже.\n\nОтправь фото кожи для начала!')
      );
    }

    let text = '📈 **Динамика кожи:**\n\n';
    history.forEach((entry, i) => {
      const score = entry.score ? `${entry.score}/10` : '—';
      text += `${entry.date} — ${score}\n`;
    });

    if (history.length >= 2) {
      const scores = history.map(h => h.score).filter(Boolean);
      if (scores.length >= 2) {
        const first = scores[0];
        const last = scores[scores.length - 1];
        const diff = last - first;
        const trend = diff > 0 ? '📈 Улучшение' : diff < 0 ? '📉 Ухудшение' : '➡️ Стабильно';
        text += `\n${trend} (${diff > 0 ? '+' : ''}${diff})`;
      }
    }

    text += `\n\nВсего записей: ${history.length}`;

    ctx.answerCbQuery();
    ctx.editMessageText(text, { parse_mode: 'Markdown' });
  });
}
