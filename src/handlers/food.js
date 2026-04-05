import { analyzeFood, downloadPhoto } from '../services/claude.js';
import { addFoodEntry } from '../db/database.js';

export async function handleFoodPhoto(ctx) {
  const photos = ctx.message.photo;
  const photoId = photos[photos.length - 1].file_id;

  try {
    const base64 = ctx._cachedBase64 || await downloadPhoto(ctx, photoId);
    const analysis = await analyzeFood(base64);

    addFoodEntry(ctx.from.id, photoId, analysis);
    await ctx.reply(analysis, { parse_mode: 'Markdown' });
  } catch (err) {
    console.error('Food analysis error:', err);
    await ctx.reply('❌ Не удалось проанализировать еду. Попробуй ещё раз.');
  }
}
