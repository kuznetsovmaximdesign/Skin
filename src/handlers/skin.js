// Skin handler — используется для прямых вызовов анализа кожи
// Основная логика теперь в claude.js (analyzePhotoSingle)

const { addEntry, getSkinHistory } = require('../db/database');

async function handleSkin(ctx, analysisText) {
  const userId = ctx.from.id;
  const photoFileId = ctx.message?.photo?.[ctx.message.photo.length - 1]?.file_id || null;
  addEntry(userId, 'skin', analysisText, photoFileId);
}

module.exports = { handleSkin };
