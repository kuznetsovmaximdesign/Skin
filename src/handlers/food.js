// Food handler — используется для прямых вызовов анализа еды
// Основная логика теперь в claude.js (analyzePhotoSingle)

const { addEntry } = require('../db/database');

async function handleFood(ctx, analysisText) {
  const userId = ctx.from.id;
  const photoFileId = ctx.message?.photo?.[ctx.message.photo.length - 1]?.file_id || null;
  addEntry(userId, 'food', analysisText, photoFileId);
}

module.exports = { handleFood };
