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
