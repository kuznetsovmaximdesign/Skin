import { analyzeSkin, downloadPhoto } from '../services/claude.js';
import { addSkinEntry, getSkinHistory } from '../db/database.js';

export async function handleSkinPhoto(ctx) {
  const photos = ctx.message.photo;
  const photoId = photos[photos.length - 1].file_id;

  try {
    const base64 = ctx._cachedBase64 || await downloadPhoto(ctx, photoId);
    const history = getSkinHistory(ctx.from.id, 5);
    const { text, score } = await analyzeSkin(base64, history);

    addSkinEntry(ctx.from.id, photoId, text, score);
    await ctx.reply(text, { parse_mode: 'Markdown' });

    if (history.length >= 2 && score !== null) {
      const scores = history.map(h => h.score).filter(Boolean);
      const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
      const trend = score > avg ? '📈 Улучшение!' : score < avg ? '📉 Ухудшение' : '➡️ Стабильно';
      await ctx.reply(`${trend} Средняя оценка за последние записи: ${avg.toFixed(1)}/10`);
    }
  } catch (err) {
    console.error('Skin analysis error:', err);
    await ctx.reply('❌ Не удалось проанализировать кожу. Попробуй ещё раз.');
  }
}
