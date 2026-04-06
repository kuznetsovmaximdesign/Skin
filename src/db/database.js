import { readFileSync, writeFileSync, existsSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DB_PATH = join(__dirname, '..', '..', 'data.json');

function load() {
  if (!existsSync(DB_PATH)) return { food: [], skin: [], cosmetic: [] };
  return JSON.parse(readFileSync(DB_PATH, 'utf-8'));
}

function save(data) {
  writeFileSync(DB_PATH, JSON.stringify(data, null, 2));
}

function today() {
  return new Date().toISOString().split('T')[0];
}

function now() {
  return new Date().toISOString();
}

export function addFoodEntry(userId, photoId, analysis) {
  const data = load();
  data.food.push({ userId, photoId, analysis, date: today(), createdAt: now() });
  save(data);
}

export function addSkinEntry(userId, photoId, analysis, score) {
  const data = load();
  data.skin.push({ userId, photoId, analysis, score, date: today(), createdAt: now() });
  save(data);
}

export function addCosmeticEntry(userId, photoId, productName, analysis, safetyScore) {
  const data = load();
  data.cosmetic.push({ userId, photoId, productName, analysis, safetyScore, date: today(), createdAt: now() });
  save(data);
}

export function getFoodDiary(userId, date) {
  const data = load();
  return data.food.filter(e => e.userId === userId && e.date === date);
}

export function getSkinDiary(userId, date) {
  const data = load();
  return data.skin.filter(e => e.userId === userId && e.date === date);
}

export function getSkinHistory(userId, limit = 10) {
  const data = load();
  return data.skin
    .filter(e => e.userId === userId)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .slice(0, limit);
}

export function getDiarySummary(userId, date) {
  const data = load();
  const food = data.food.filter(e => e.userId === userId && e.date === date);
  const skin = data.skin.filter(e => e.userId === userId && e.date === date);
  const scores = skin.map(e => e.score).filter(Boolean);
  const skinAvgScore = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
  return { food: food.length, skin: skin.length, skinAvgScore };
}

// =============================================
// ADMIN PANEL FUNCTIONS
// =============================================

export function getAllData() {
  return load();
}

export function getStats() {
  const data = load();
  const uniqueUsers = new Set([
    ...data.food.map(e => e.userId),
    ...data.skin.map(e => e.userId),
    ...data.cosmetic.map(e => e.userId),
  ]);

  const skinScores = data.skin.map(e => e.score).filter(Boolean);
  const avgSkinScore = skinScores.length
    ? (skinScores.reduce((a, b) => a + b, 0) / skinScores.length).toFixed(1)
    : null;

  const dates = [
    ...data.food.map(e => e.date),
    ...data.skin.map(e => e.date),
    ...data.cosmetic.map(e => e.date),
  ].sort();

  return {
    totalFood: data.food.length,
    totalSkin: data.skin.length,
    totalCosmetic: data.cosmetic.length,
    totalEntries: data.food.length + data.skin.length + data.cosmetic.length,
    uniqueUsers: uniqueUsers.size,
    avgSkinScore,
    firstDate: dates[0] || null,
    lastDate: dates[dates.length - 1] || null,
  };
}

export function getEntriesByType(type, limit = 50, offset = 0) {
  const data = load();
  const entries = (data[type] || [])
    .sort((a, b) => (b.createdAt || '').localeCompare(a.createdAt || ''))
    .slice(offset, offset + limit);
  return { entries, total: (data[type] || []).length };
}

export function deleteEntry(type, index) {
  const data = load();
  if (!data[type]) return false;
  const sorted = data[type].sort((a, b) => (b.createdAt || '').localeCompare(a.createdAt || ''));
  if (index < 0 || index >= sorted.length) return false;
  const entry = sorted[index];
  data[type] = data[type].filter(e => e !== entry);
  save(data);
  return true;
}

export function getUsersList() {
  const data = load();
  const users = {};
  for (const type of ['food', 'skin', 'cosmetic']) {
    for (const entry of data[type]) {
      if (!users[entry.userId]) {
        users[entry.userId] = { userId: entry.userId, food: 0, skin: 0, cosmetic: 0, lastActive: null };
      }
      users[entry.userId][type]++;
      if (!users[entry.userId].lastActive || entry.createdAt > users[entry.userId].lastActive) {
        users[entry.userId].lastActive = entry.createdAt;
      }
    }
  }
  return Object.values(users).sort((a, b) => (b.lastActive || '').localeCompare(a.lastActive || ''));
}
