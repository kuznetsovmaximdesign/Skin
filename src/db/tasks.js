import { readFileSync, writeFileSync, existsSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const TASKS_PATH = join(__dirname, '..', '..', 'tasks.json');

function load() {
  if (!existsSync(TASKS_PATH)) return { tasks: [], idCounter: 1 };
  return JSON.parse(readFileSync(TASKS_PATH, 'utf-8'));
}

function save(data) {
  writeFileSync(TASKS_PATH, JSON.stringify(data, null, 2));
}

function todayStr() {
  return new Date().toISOString().split('T')[0];
}

/**
 * Get all tasks, optionally filtered
 * @param {Object} filters - { status, priority, date }
 */
export function getTasks(filters = {}) {
  const data = load();
  let tasks = data.tasks;

  if (filters.status) {
    tasks = tasks.filter(t => t.status === filters.status);
  }
  if (filters.priority) {
    tasks = tasks.filter(t => t.priority === filters.priority);
  }
  if (filters.date) {
    tasks = tasks.filter(t => t.date === filters.date);
  }

  // Sort: priority order (critical > high > normal > low), then by createdAt
  const priorityOrder = { critical: 0, high: 1, normal: 2, low: 3 };
  tasks.sort((a, b) => {
    if (a.status !== b.status) {
      const statusOrder = { in_progress: 0, todo: 1, done: 2 };
      return (statusOrder[a.status] || 9) - (statusOrder[b.status] || 9);
    }
    const pa = priorityOrder[a.priority] ?? 2;
    const pb = priorityOrder[b.priority] ?? 2;
    if (pa !== pb) return pa - pb;
    return (a.createdAt || '').localeCompare(b.createdAt || '');
  });

  return tasks;
}

/**
 * Add a new task
 */
export function addTask({ text, priority = 'normal', deadline = null, category = '' }) {
  const data = load();
  const task = {
    id: data.idCounter++,
    text,
    priority, // critical, high, normal, low
    status: 'todo', // todo, in_progress, done
    category,
    deadline,
    date: todayStr(),
    createdAt: new Date().toISOString(),
    completedAt: null,
  };
  data.tasks.push(task);
  save(data);
  return task;
}

/**
 * Update task fields
 */
export function updateTask(id, updates) {
  const data = load();
  const task = data.tasks.find(t => t.id === id);
  if (!task) return null;

  if (updates.text !== undefined) task.text = updates.text;
  if (updates.priority !== undefined) task.priority = updates.priority;
  if (updates.status !== undefined) {
    task.status = updates.status;
    if (updates.status === 'done') {
      task.completedAt = new Date().toISOString();
    } else {
      task.completedAt = null;
    }
  }
  if (updates.category !== undefined) task.category = updates.category;
  if (updates.deadline !== undefined) task.deadline = updates.deadline;

  save(data);
  return task;
}

/**
 * Delete a task
 */
export function deleteTask(id) {
  const data = load();
  const idx = data.tasks.findIndex(t => t.id === id);
  if (idx === -1) return false;
  data.tasks.splice(idx, 1);
  save(data);
  return true;
}

/**
 * Get today's progress stats
 */
export function getTasksProgress(date) {
  const d = date || todayStr();
  const data = load();
  const dayTasks = data.tasks.filter(t => t.date === d);
  const total = dayTasks.length;
  const done = dayTasks.filter(t => t.status === 'done').length;
  const inProgress = dayTasks.filter(t => t.status === 'in_progress').length;
  const todo = dayTasks.filter(t => t.status === 'todo').length;
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;

  return { total, done, inProgress, todo, percent, date: d };
}

/**
 * Clean completed tasks (archive them)
 */
export function cleanDoneTasks() {
  const data = load();
  const removed = data.tasks.filter(t => t.status === 'done').length;
  data.tasks = data.tasks.filter(t => t.status !== 'done');
  save(data);
  return removed;
}

/**
 * Get all unique dates that have tasks
 */
export function getTaskDates() {
  const data = load();
  const dates = [...new Set(data.tasks.map(t => t.date))].sort().reverse();
  return dates;
}
