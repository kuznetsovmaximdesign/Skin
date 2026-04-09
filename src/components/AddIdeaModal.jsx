import React, { useState } from 'react';
import { FORMATS, CATEGORIES } from '../data/initialData';

export default function AddIdeaModal({ onAdd, onClose, currentWeek }) {
  const [title, setTitle] = useState('');
  const [format, setFormat] = useState('A');
  const [category, setCategory] = useState('b');
  const [week, setWeek] = useState(currentWeek || 0);
  const [description, setDescription] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!title.trim()) return;
    onAdd({
      title: title.trim(),
      format,
      category,
      week,
      description: description.trim(),
    });
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="glass p-6 w-full max-w-md mx-4"
        style={{ background: 'var(--bg-secondary)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>
            Новая идея
          </h3>
          <button
            className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-white/10 transition"
            style={{ color: 'var(--text-muted)' }}
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label className="text-[11px] font-medium mb-1 block" style={{ color: 'var(--text-secondary)' }}>
              Название
            </label>
            <input
              className="glass-input"
              placeholder="Введите название темы..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-medium mb-1 block" style={{ color: 'var(--text-secondary)' }}>
                Формат
              </label>
              <div className="flex gap-2">
                {Object.entries(FORMATS).map(([key, fmt]) => (
                  <button
                    type="button"
                    key={key}
                    className="flex-1 py-2 rounded-lg text-[12px] font-semibold transition-all"
                    style={{
                      background: format === key ? `${fmt.color}25` : 'var(--surface)',
                      color: format === key ? fmt.color : 'var(--text-muted)',
                      border: `1px solid ${format === key ? fmt.color + '40' : 'var(--border)'}`,
                    }}
                    onClick={() => setFormat(key)}
                  >
                    {fmt.short}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-[11px] font-medium mb-1 block" style={{ color: 'var(--text-secondary)' }}>
                Категория
              </label>
              <div className="flex gap-2">
                {Object.entries(CATEGORIES).map(([key, cat]) => (
                  <button
                    type="button"
                    key={key}
                    className="flex-1 py-2 rounded-lg text-[12px] transition-all"
                    style={{
                      background: category === key ? `${cat.color}20` : 'var(--surface)',
                      color: category === key ? cat.color : 'var(--text-muted)',
                      border: `1px solid ${category === key ? cat.color + '40' : 'var(--border)'}`,
                    }}
                    onClick={() => setCategory(key)}
                  >
                    {cat.emoji}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div>
            <label className="text-[11px] font-medium mb-1 block" style={{ color: 'var(--text-secondary)' }}>
              Неделя
            </label>
            <input
              type="number"
              className="glass-input w-20"
              min={0}
              value={week}
              onChange={(e) => setWeek(parseInt(e.target.value) || 0)}
            />
          </div>

          <div>
            <label className="text-[11px] font-medium mb-1 block" style={{ color: 'var(--text-secondary)' }}>
              Описание / Хук (необязательно)
            </label>
            <textarea
              className="glass-input min-h-[80px] resize-y"
              placeholder="Описание идеи..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="flex gap-3 mt-1">
            <button type="button" className="glass-btn flex-1" onClick={onClose}>
              Отмена
            </button>
            <button
              type="submit"
              className="glass-btn glass-btn-primary flex-1"
              disabled={!title.trim()}
            >
              Добавить
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
