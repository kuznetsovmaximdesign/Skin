// Cosmetic handler — используется для прямых вызовов INCI-анализа
// Основная логика теперь в claude.js (analyzePhotoSingle)

const { addEntry } = require('../db/database');

async function handleCosmetic(ctx, analysisText) {
  const userId = ctx.from.id;
  const photoFileId = ctx.message?.photo?.[ctx.message.photo.length - 1]?.file_id || null;
  addEntry(userId, 'cosmetic', analysisText, photoFileId);
}

module.exports = { handleCosmetic };
