const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', '..', 'data');
const DB_FILE = path.join(DATA_DIR, 'diary.json');

function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
  if (!fs.existsSync(DB_FILE)) {
    fs.writeFileSync(DB_FILE, JSON.stringify({ entries: [], profiles: {} }, null, 2));
  }
}

function readDB() {
  ensureDataDir();
  const raw = fs.readFileSync(DB_FILE, 'utf-8');
  return JSON.parse(raw);
}

function writeDB(data) {
  ensureDataDir();
  fs.writeFileSync(DB_FILE, JSON.stringify(data, null, 2));
}

function addEntry(userId, type, analysis, photoFileId = null) {
  const db = readDB();
  const entry = {
    id: Date.now(),
    userId,
    type, // 'food' | 'skin' | 'cosmetic'
    analysis,
    photoFileId,
    date: new Date().toISOString(),
  };
  db.entries.push(entry);
  writeDB(db);
  return entry;
}

function getEntries(userId, type = null, limit = 10) {
  const db = readDB();
  let entries = db.entries.filter((e) => e.userId === userId);
  if (type) entries = entries.filter((e) => e.type === type);
  return entries.slice(-limit);
}

function getEntriesByDate(userId, dateStr) {
  const db = readDB();
  return db.entries.filter((e) => {
    return e.userId === userId && e.date.startsWith(dateStr);
  });
}

function getSkinHistory(userId, limit = 5) {
  return getEntries(userId, 'skin', limit);
}

function getProfile(userId) {
  const db = readDB();
  return db.profiles?.[userId] || null;
}

function saveProfile(userId, profile) {
  const db = readDB();
  if (!db.profiles) db.profiles = {};
  db.profiles[userId] = { ...profile, updatedAt: new Date().toISOString() };
  writeDB(db);
}

module.exports = {
  addEntry,
  getEntries,
  getEntriesByDate,
  getSkinHistory,
  getProfile,
  saveProfile,
};
