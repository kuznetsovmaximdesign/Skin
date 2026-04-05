// Diary handler — логика дневника
// Основная обработка /diary теперь в bot.js

const { getEntries, getEntriesByDate, getSkinHistory } = require('../db/database');

function formatDiary(userId, dateStr) {
  const entries = getEntriesByDate(userId, dateStr);
  if (entries.length === 0) {
    return `📓 За ${dateStr} записей нет.\n\nОтправь фото чтобы добавить запись!`;
  }

  let response = `📓 Дневник за ${dateStr}:\n\n`;
  entries.forEach((entry, i) => {
    const time = new Date(entry.date).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    const typeEmoji = { food: '🍽', skin: '🔍', cosmetic: '🧴' }[entry.type] || '📝';
    response += `${i + 1}. ${typeEmoji} ${time}\n${entry.analysis.substring(0, 100)}...\n\n`;
  });

  const skinEntries = getSkinHistory(userId);
  if (skinEntries.length > 1) {
    response += `\n📊 Записей о коже: ${skinEntries.length}`;
  }

  return response;
}

module.exports = { formatDiary };
