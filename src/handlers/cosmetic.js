import { analyzeCosmetic, downloadPhoto } from '../services/claude.js';
import { addCosmeticEntry } from '../db/database.js';

export async function handleCosmeticPhoto(ctx) {
  const photos = ctx.message.photo;
  const photoId = photos[photos.length - 1].file_id;

  try {
    const base64 = ctx._cachedBase64 || await downloadPhoto(ctx, photoId);
    const { text, safetyScore, productName } = await analyzeCosmetic(base64);

    addCosmeticEntry(ctx.from.id, photoId, productName, text, safetyScore);
    await ctx.reply(text, { parse_mode: 'Markdown' });
  } catch (err) {
    console.error('Cosmetic analysis error:', err);
    await ctx.reply('❌ Не удалось проанализировать состав. Попробуй ещё раз.');
  }
}
