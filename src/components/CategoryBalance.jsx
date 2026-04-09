import React from 'react';
import { CATEGORIES, FORMATS } from '../data/initialData';

export default function CategoryBalance({ ideas }) {
  const active = ideas.filter((i) => !i.archived);

  // Category distribution
  const catCounts = {};
  Object.keys(CATEGORIES).forEach((k) => { catCounts[k] = 0; });
  active.forEach((i) => { catCounts[i.category] = (catCounts[i.category] || 0) + 1; });
  const totalCat = active.length || 1;

  // Format distribution
  const fmtCounts = {};
  Object.keys(FORMATS).forEach((k) => { fmtCounts[k] = 0; });
  active.forEach((i) => { fmtCounts[i.format] = (fmtCounts[i.format] || 0) + 1; });

  return (
    <div className="glass-card p-4">
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-primary)' }}>
        Баланс контента
      </h3>

      {/* Categories */}
      <div className="mb-4">
        <p className="text-[11px] mb-2 font-medium" style={{ color: 'var(--text-secondary)' }}>
          Категории
        </p>
        <div className="flex flex-col gap-2">
          {Object.entries(CATEGORIES).map(([key, cat]) => {
            const count = catCounts[key] || 0;
            const pct = Math.round((count / totalCat) * 100);
            return (
              <div key={key} className="flex items-center gap-2">
                <span className="text-[11px] w-16 shrink-0" style={{ color: cat.color }}>
                  {cat.emoji} {cat.label}
                </span>
                <div className="progress-bar flex-1">
                  <div className="progress-fill" style={{
                    width: `${pct}%`,
                    background: cat.color,
                  }} />
                </div>
                <span className="text-[11px] w-8 text-right" style={{ color: 'var(--text-muted)' }}>
                  {count}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Formats */}
      <div>
        <p className="text-[11px] mb-2 font-medium" style={{ color: 'var(--text-secondary)' }}>
          Форматы
        </p>
        <div className="flex gap-3">
          {Object.entries(FORMATS).map(([key, fmt]) => {
            const count = fmtCounts[key] || 0;
            return (
              <div key={key} className="flex-1 text-center p-2 rounded-lg"
                style={{ background: `${fmt.color}10` }}>
                <div className="text-base font-bold" style={{ color: fmt.color }}>
                  {count}
                </div>
                <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                  {fmt.label}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
