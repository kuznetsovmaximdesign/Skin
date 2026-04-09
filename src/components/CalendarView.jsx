import React from 'react';
import ContentCard from './ContentCard';
import { FORMATS, CATEGORIES } from '../data/initialData';

export default function CalendarView({
  ideas,
  maxWeek,
  onToggleStep,
  onToggleCollapse,
  onArchive,
  onDelete,
  onUpdateTitle,
  onMoveWeek,
  onDropIdea,
}) {
  const weeks = [];
  for (let w = 0; w <= maxWeek; w++) {
    weeks.push(w);
  }

  const handleDragOver = (e) => {
    e.preventDefault();
    e.currentTarget.classList.add('drag-over');
  };

  const handleDragLeave = (e) => {
    e.currentTarget.classList.remove('drag-over');
  };

  const handleDrop = (e, weekNum) => {
    e.preventDefault();
    e.currentTarget.classList.remove('drag-over');
    const ideaId = e.dataTransfer.getData('text/plain');
    if (ideaId) {
      onDropIdea(ideaId, weekNum);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
        📆 Календарь по неделям
      </h2>

      <div className="flex flex-col gap-6">
        {weeks.map((weekNum) => {
          const weekIdeas = ideas.filter((i) => !i.archived && i.week === weekNum);
          const totalSteps = weekIdeas.reduce((sum, i) => sum + i.steps.length, 0);
          const doneSteps = weekIdeas.reduce((sum, i) => sum + i.steps.filter((s) => s.done).length, 0);
          const percent = totalSteps > 0 ? Math.round((doneSteps / totalSteps) * 100) : 0;

          return (
            <div
              key={weekNum}
              className="glass-card p-4 transition-all"
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, weekNum)}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                    Неделя {weekNum}
                  </h3>
                  <span className="text-[11px] px-2 py-0.5 rounded-md"
                    style={{ background: 'var(--surface)', color: 'var(--text-muted)' }}>
                    {weekIdeas.length} тем
                  </span>
                </div>
                <span className="text-sm font-bold" style={{
                  color: percent === 100 ? 'var(--success)' : 'var(--accent-light)',
                }}>
                  {percent}%
                </span>
              </div>

              <div className="progress-bar mb-4">
                <div className="progress-fill" style={{
                  width: `${percent}%`,
                  background: percent === 100 ? 'var(--success)' : 'var(--accent)',
                }} />
              </div>

              {weekIdeas.length === 0 ? (
                <p className="text-[12px] text-center py-4" style={{ color: 'var(--text-muted)' }}>
                  Перетащите идеи сюда
                </p>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {weekIdeas.map((idea) => (
                    <ContentCard
                      key={idea.id}
                      idea={idea}
                      onToggleStep={onToggleStep}
                      onToggleCollapse={onToggleCollapse}
                      onArchive={onArchive}
                      onDelete={onDelete}
                      onUpdateTitle={onUpdateTitle}
                      onMoveWeek={onMoveWeek}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
