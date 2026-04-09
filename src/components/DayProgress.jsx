import React from 'react';

export default function DayProgress({ ideas }) {
  const todayIdeas = ideas.filter((i) => !i.archived && i.week === 0);
  const totalSteps = todayIdeas.reduce((sum, i) => sum + i.steps.length, 0);
  const doneSteps = todayIdeas.reduce((sum, i) => sum + i.steps.filter((s) => s.done).length, 0);
  const percent = totalSteps > 0 ? Math.round((doneSteps / totalSteps) * 100) : 0;

  return (
    <div className="glass-card p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          Прогресс дня
        </h3>
        <span className="text-sm font-bold" style={{ color: percent === 100 ? 'var(--success)' : 'var(--accent)' }}>
          {percent}%
        </span>
      </div>
      <div className="progress-bar">
        <div
          className="progress-fill"
          style={{
            width: `${percent}%`,
            background: percent === 100
              ? 'var(--success)'
              : `linear-gradient(90deg, var(--accent), var(--accent-light))`,
          }}
        />
      </div>
      <p className="text-[11px] mt-2" style={{ color: 'var(--text-muted)' }}>
        {doneSteps} из {totalSteps} шагов • {todayIdeas.length} тем на эту неделю
      </p>
    </div>
  );
}
