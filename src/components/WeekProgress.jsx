import React from 'react';
import { FORMATS, CATEGORIES } from '../data/initialData';

export default function WeekProgress({ ideas, currentWeek }) {
  const weekIdeas = ideas.filter((i) => !i.archived && i.week === currentWeek);
  const totalSteps = weekIdeas.reduce((sum, i) => sum + i.steps.length, 0);
  const doneSteps = weekIdeas.reduce((sum, i) => sum + i.steps.filter((s) => s.done).length, 0);
  const percent = totalSteps > 0 ? Math.round((doneSteps / totalSteps) * 100) : 0;

  const formatCounts = {};
  weekIdeas.forEach((i) => {
    formatCounts[i.format] = (formatCounts[i.format] || 0) + 1;
  });

  return (
    <div className="glass-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          Неделя {currentWeek}
        </h3>
        <span className="text-sm font-bold" style={{ color: percent === 100 ? 'var(--success)' : 'var(--accent-light)' }}>
          {percent}%
        </span>
      </div>

      <div className="progress-bar mb-3">
        <div
          className="progress-fill"
          style={{
            width: `${percent}%`,
            background: percent === 100
              ? 'var(--success)'
              : `linear-gradient(90deg, var(--accent), var(--pink))`,
          }}
        />
      </div>

      <div className="flex gap-2 flex-wrap">
        {Object.entries(formatCounts).map(([fmt, count]) => (
          <span key={fmt} className="badge" style={{
            background: `${FORMATS[fmt]?.color}18`,
            color: FORMATS[fmt]?.color,
          }}>
            {FORMATS[fmt]?.short} ×{count}
          </span>
        ))}
      </div>

      <p className="text-[11px] mt-2" style={{ color: 'var(--text-muted)' }}>
        {weekIdeas.length} тем • {doneSteps}/{totalSteps} шагов
      </p>
    </div>
  );
}
