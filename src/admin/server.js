import './../env.js';
import express from 'express';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import { getStats, getEntriesByType, deleteEntry, getUsersList, getAllData } from '../db/database.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.ADMIN_PORT || 3000;

app.use(express.json());
app.use(express.static(join(__dirname, 'public')));

// API routes
app.get('/api/stats', (req, res) => {
  res.json(getStats());
});

app.get('/api/entries/:type', (req, res) => {
  const { type } = req.params;
  if (!['food', 'skin', 'cosmetic'].includes(type)) {
    return res.status(400).json({ error: 'Invalid type' });
  }
  const limit = parseInt(req.query.limit) || 50;
  const offset = parseInt(req.query.offset) || 0;
  res.json(getEntriesByType(type, limit, offset));
});

app.delete('/api/entries/:type/:index', (req, res) => {
  const { type, index } = req.params;
  if (!['food', 'skin', 'cosmetic'].includes(type)) {
    return res.status(400).json({ error: 'Invalid type' });
  }
  const success = deleteEntry(type, parseInt(index));
  res.json({ success });
});

app.get('/api/users', (req, res) => {
  res.json(getUsersList());
});

app.get('/api/export', (req, res) => {
  const data = getAllData();
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Content-Disposition', 'attachment; filename=skin-bot-data.json');
  res.json(data);
});

// Serve admin panel
app.get('/{*path}', (req, res) => {
  res.sendFile(join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`\n  🌌 Aurora Admin Panel`);
  console.log(`  http://localhost:${PORT}\n`);
});
