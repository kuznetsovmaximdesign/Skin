import React, { useState } from 'react';
import { FORMATS, CATEGORIES } from '../data/initialData';

export default function ContentCard({
  idea,
  onToggleStep,
  onToggleCollapse,
  onArchive,
  onDelete,
  onUpdateTitle,
  onMoveWeek,
  onDragStart,
  onDragEnd,
}) {
  const [editing, setEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState(idea.title);

  const format = FORMATS[idea.format] || FORMATS.A;
  const category = CATEGORIES[idea.category] || CATEGORIES.b;
  const totalSteps = idea.steps.length;
  const doneSteps = idea.steps.filter((s) => s.done).length;
  const percent = totalSteps > 0 ? Math.round((doneSteps / totalSteps) * 100) : 0;
  const isComplete = percent === 100;

  const handleTitleSave = () => {
    setEditing(false);
    if (titleDraft.trim() && titleDraft !== idea.title) {
      onUpdateTitle(idea.id, titleDraft.trim());
    }
  };

  return (
    <div
      className={`glass-card p-4 fade-in ${isComplete && !idea.collapsed ? 'collapsed' : ''}`}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', idea.id);
        e.currentTarget.classList.add('dragging');
        onDragStart?.(idea.id);
      }}
      onDragEnd={(e) => {
        e.currentTarget.classList.remove('dragging');
        onDragEnd?.();
      }}
      style={{
        borderLeftWidth: '3px',
        borderLeftColor: category.color,
        opacity: isComplete ? 0.7 : 1,
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="badge" style={{ background: `${format.color}20`, color: format.color }}>
              {format.short}
            </span>
            <span className="badge" style={{ background: `${category.color}18`, color: category.color }}>
              {category.emoji} {category.label}
            </span>
            {isComplete && (
              <span className="badge" style={{ background: 'var(--success-bg)', color: 'var(--success)' }}>
                ✓ Готово
              </span>
            )}
          </div>

          {editing ? (
            <input
              className="glass-input text-sm font-semibold"
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              onBlur={handleTitleSave}
              onKeyDown={(e) => e.key === 'Enter' && handleTitleSave()}
              autoFocus
            />
          ) : (
            <h4
              className="text-sm font-semibold cursor-pointer truncate"
              style={{ color: 'var(--text-primary)' }}
              onDoubleClick={() => setEditing(true)}
            >
              {idea.title}
            </h4>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            className="w-6 h-6 rounded flex items-center justify-center text-[11px] hover:bg-white/10 transition"
            style={{ color: 'var(--text-muted)' }}
            onClick={() => onToggleCollapse(idea.id)}
            title={idea.collapsed ? 'Развернуть' : 'Свернуть'}
          >
            {idea.collapsed ? '▼' : '▲'}
          </button>
          <button
            className="w-6 h-6 rounded flex items-center justify-center text-[11px] hover:bg-white/10 transition"
            style={{ color: 'var(--text-muted)' }}
            onClick={() => onArchive(idea.id)}
            title="В архив"
          >
            📦
          </button>
          <button
            className="w-6 h-6 rounded flex items-center justify-center text-[11px] hover:bg-white/10 transition"
            style={{ color: 'var(--danger)' }}
            onClick={() => onDelete(idea.id)}
            title="Удалить"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="flex items-center gap-2 mb-2">
        <div className="progress-bar flex-1">
          <div
            className="progress-fill"
            style={{
              width: `${percent}%`,
              background: isComplete ? 'var(--success)' : 'var(--accent)',
            }}
          />
        </div>
        <span className="text-[11px] font-medium" style={{
          color: isComplete ? 'var(--success)' : 'var(--text-muted)',
        }}>
          {percent}%
        </span>
      </div>

      {/* Body (collapsible) */}
      {!idea.collapsed && (
        <div className="card-body">
          {/* Description */}
          {idea.description && (
            <div
              className="text-[12px] mb-3 p-2 rounded-lg"
              style={{ background: 'var(--surface)', color: 'var(--text-secondary)' }}
              dangerouslySetInnerHTML={{ __html: idea.description }}
            />
          )}

          {/* Steps */}
          <div className="flex flex-col gap-1.5">
            {idea.steps.map((step, idx) => (
              <label
                key={step.id}
                className="flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer transition-all hover:bg-white/5"
              >
                <input
                  type="checkbox"
                  checked={step.done}
                  onChange={() => onToggleStep(idea.id, step.id)}
                  className="w-4 h-4 rounded accent-purple-500"
                />
                <span className="text-[13px]" style={{
                  color: step.done ? 'var(--text-muted)' : 'var(--text-primary)',
                  textDecoration: step.done ? 'line-through' : 'none',
                }}>
                  {step.text}
                </span>
              </label>
            ))}
          </div>

          {/* Week control */}
          <div className="flex items-center gap-2 mt-3 pt-2 border-t" style={{ borderColor: 'var(--border)' }}>
            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>Неделя:</span>
            <button
              className="w-5 h-5 rounded flex items-center justify-center text-[10px] hover:bg-white/10"
              style={{ color: 'var(--text-secondary)' }}
              onClick={() => onMoveWeek(idea.id, idea.week - 1)}
              disabled={idea.week <= 0}
            >
              ◀
            </button>
            <span className="text-[12px] font-medium" style={{ color: 'var(--accent-light)' }}>
              {idea.week}
            </span>
            <button
              className="w-5 h-5 rounded flex items-center justify-center text-[10px] hover:bg-white/10"
              style={{ color: 'var(--text-secondary)' }}
              onClick={() => onMoveWeek(idea.id, idea.week + 1)}
            >
              ▶
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
