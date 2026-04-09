import React from 'react';
import { FORMATS, CATEGORIES } from '../data/initialData';

export default function ArchiveView({ ideas, onRestore, onDelete }) {
  const archived = ideas.filter((i) => i.archived);

  if (archived.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <span className="text-4xl mb-4">📦</span>
        <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>
          Архив пуст
        </h3>
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          Завершённые темы появятся здесь
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
          📦 Архив
        </h2>
        <span className="text-sm" style={{ color: 'var(--text-muted)' }}>
          {archived.length} тем
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {archived.map((idea) => {
          const format = FORMATS[idea.format] || FORMATS.A;
          const category = CATEGORIES[idea.category] || CATEGORIES.b;

          return (
            <div key={idea.id} className="glass-card p-4 fade-in" style={{ opacity: 0.7 }}>
              <div className="flex items-center gap-2 mb-2">
                <span className="badge" style={{ background: `${format.color}20`, color: format.color }}>
                  {format.short}
                </span>
                <span className="badge" style={{ background: `${category.color}18`, color: category.color }}>
                  {category.emoji} {category.label}
                </span>
              </div>

              <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>
                {idea.title}
              </h4>

              {idea.description && (
                <p className="text-[11px] mb-3 line-clamp-2" style={{ color: 'var(--text-muted)' }}
                  dangerouslySetInnerHTML={{ __html: idea.description }}
                />
              )}

              <div className="flex gap-2">
                <button
                  className="glass-btn text-[11px] py-1 px-3"
                  onClick={() => onRestore(idea.id)}
                >
                  ↩ Восстановить
                </button>
                <button
                  className="glass-btn text-[11px] py-1 px-3"
                  style={{ color: 'var(--danger)' }}
                  onClick={() => onDelete(idea.id)}
                >
                  ✕ Удалить
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
