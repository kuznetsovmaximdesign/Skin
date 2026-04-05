import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, '..', '..', 'data');
const DB_FILE = path.join(DATA_DIR, 'diary.json');

function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
  if (!fs.existsSync(DB_FILE)) {
    fs.writeFileSync(DB_FILE, JSON.stringify({ food: [], skin: [], cosmetic: [] }, null, 2));
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

export function addFoodEntry(userId, photoId, analysis) {
  const db = readDB();
  db.food.push({
    userId,
    photoId,
    analysis,
    date: new Date().toISOString().split('T')[0],
    createdAt: new Date().toISOString(),
  });
  writeDB(db);
}

export function addSkinEntry(userId, photoId, analysis, score = null) {
  const db = readDB();
  db.skin.push({
    userId,
    photoId,
    analysis,
    score,
    date: new Date().toISOString().split('T')[0],
    createdAt: new Date().toISOString(),
  });
  writeDB(db);
}

export function addCosmeticEntry(userId, photoId, productName, analysis, safetyScore = null) {
  const db = readDB();
  db.cosmetic.push({
    userId,
    photoId,
    productName,
    analysis,
    safetyScore,
    date: new Date().toISOString().split('T')[0],
    createdAt: new Date().toISOString(),
  });
  writeDB(db);
}

export function getSkinHistory(userId, limit = 5) {
  const db = readDB();
  return db.skin
    .filter((e) => e.userId === userId)
    .slice(-limit);
}

export function getEntriesByDate(userId, dateStr) {
  const db = readDB();
  const results = [];
  for (const type of ['food', 'skin', 'cosmetic']) {
    for (const entry of db[type]) {
      if (entry.userId === userId && entry.date === dateStr) {
        results.push({ ...entry, type });
      }
    }
  }
  return results.sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));
}

export function getAllEntries(userId, limit = 20) {
  const db = readDB();
  const results = [];
  for (const type of ['food', 'skin', 'cosmetic']) {
    for (const entry of db[type]) {
      if (entry.userId === userId) {
        results.push({ ...entry, type });
      }
    }
  }
  return results
    .sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt))
    .slice(-limit);
}
