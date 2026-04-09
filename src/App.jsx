import React, { useState, useRef, useCallback } from 'react';
import { useLocalStorage } from './hooks/useLocalStorage';
import { SAMPLE_IDEAS, createIdea, FORMATS, CATEGORIES } from './data/initialData';
import Sidebar from './components/Sidebar';
import ContentCard from './components/ContentCard';
import DayProgress from './components/DayProgress';
import WeekProgress from './components/WeekProgress';
import CalendarView from './components/CalendarView';
import ArchiveView from './components/ArchiveView';
import AddIdeaModal from './components/AddIdeaModal';
import CategoryBalance from './components/CategoryBalance';

export default function App() {
  const [ideas, setIdeas] = useLocalStorage('aurora-ideas', SAMPLE_IDEAS);
  const [activeTab, setActiveTab] = useLocalStorage('aurora-tab', 'topics');
  const [showAddModal, setShowAddModal] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [showAI, setShowAI] = useState(false);
  const [aiResult, setAiResult] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [apiKey, setApiKey] = useLocalStorage('aurora-api-key', '');
  const [inlineInput, setInlineInput] = useState('');
  const [collapsedCards, setCollapsedCards] = useLocalStorage('aurora-collapsed', {});
  const uploadRef = useRef(null);

  // ---- Idea CRUD ----

  const addIdea = useCallback((data) => {
    const idea = createIdea(data);
    setIdeas((prev) => [...prev, idea]);
  }, [setIdeas]);

  const deleteIdea = useCallback((id) => {
    setIdeas((prev) => prev.filter((i) => i.id !== id));
  }, [setIdeas]);

  const archiveIdea = useCallback((id) => {
    setIdeas((prev) =>
      prev.map((i) => (i.id === id ? { ...i, archived: true } : i))
    );
  }, [setIdeas]);

  const restoreIdea = useCallback((id) => {
    setIdeas((prev) =>
      prev.map((i) => (i.id === id ? { ...i, archived: false } : i))
    );
  }, [setIdeas]);

  const toggleStep = useCallback((ideaId, stepId) => {
    setIdeas((prev) =>
      prev.map((idea) => {
        if (idea.id !== ideaId) return idea;
        const newSteps = idea.steps.map((s) =>
          s.id === stepId ? { ...s, done: !s.done } : s
        );
        const allDone = newSteps.every((s) => s.done);
        return { ...idea, steps: newSteps, collapsed: allDone ? true : idea.collapsed };
      })
    );
  }, [setIdeas]);

  const toggleCollapse = useCallback((id) => {
    setIdeas((prev) =>
      prev.map((i) => (i.id === id ? { ...i, collapsed: !i.collapsed } : i))
    );
  }, [setIdeas]);

  const updateTitle = useCallback((id, title) => {
    setIdeas((prev) =>
      prev.map((i) => (i.id === id ? { ...i, title } : i))
    );
  }, [setIdeas]);

  const moveWeek = useCallback((id, newWeek) => {
    if (newWeek < 0) return;
    setIdeas((prev) =>
      prev.map((i) => (i.id === id ? { ...i, week: newWeek } : i))
    );
  }, [setIdeas]);

  const dropIdea = useCallback((ideaId, weekNum) => {
    setIdeas((prev) =>
      prev.map((i) => (i.id === ideaId ? { ...i, week: weekNum } : i))
    );
  }, [setIdeas]);

  // ---- JSON Upload ----

  const handleUploadJSON = useCallback((jsonText) => {
    try {
      const data = JSON.parse(jsonText);
      const arr = Array.isArray(data) ? data : [data];
      const newIdeas = arr.map((item) => createIdea(item));
      setIdeas((prev) => [...prev, ...newIdeas]);
      setShowUpload(false);
    } catch {
      alert('Ошибка парсинга JSON. Проверьте формат.');
    }
  }, [setIdeas]);

  // ---- Inline add ----

  const handleInlineAdd = useCallback((e) => {
    if (e.key === 'Enter' && inlineInput.trim()) {
      addIdea({ title: inlineInput.trim() });
      setInlineInput('');
    }
  }, [inlineInput, addIdea]);

  // ---- AI Analysis ----

  const runAIAnalysis = useCallback(async () => {
    if (!apiKey) {
      setAiResult('Введите API ключ Anthropic для AI-анализа.');
      return;
    }
    setAiLoading(true);
    setAiResult('');

    const activeIdeas = ideas.filter((i) => !i.archived);
    const summary = activeIdeas.map((i) => {
      const fmt = FORMATS[i.format]?.label || i.format;
      const cat = CATEGORIES[i.category]?.label || i.category;
      const pct = i.steps.length > 0
        ? Math.round((i.steps.filter((s) => s.done).length / i.steps.length) * 100)
        : 0;
      return `- "${i.title}" (${fmt}, ${cat}, неделя ${i.week}, прогресс ${pct}%)`;
    }).join('\n');

    const catCounts = {};
    activeIdeas.forEach((i) => {
      const cat = CATEGORIES[i.category]?.label || i.category;
      catCounts[cat] = (catCounts[cat] || 0) + 1;
    });

    const prompt = `Ты — AI-ассистент контент-планирования. Проанализируй текущий контент-план и дай рекомендации.

Текущие темы (${activeIdeas.length} штук):
${summary}

Распределение по категориям: ${Object.entries(catCounts).map(([k, v]) => `${k}: ${v}`).join(', ')}

Дай краткий анализ:
1. Баланс категорий и форматов
2. Что стоит добавить для разнообразия
3. Приоритеты на эту неделю
4. Общая оценка плана

Ответь на русском, кратко и по делу.`;

    try {
      const response = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': apiKey,
          'anthropic-version': '2023-06-01',
          'anthropic-dangerous-direct-browser-access': 'true',
        },
        body: JSON.stringify({
          model: 'claude-sonnet-4-20250514',
          max_tokens: 1024,
          messages: [{ role: 'user', content: prompt }],
        }),
      });

      if (!response.ok) {
        const err = await response.text();
        throw new Error(`API Error ${response.status}: ${err}`);
      }

      const result = await response.json();
      setAiResult(result.content?.[0]?.text || 'Нет ответа от AI');
    } catch (err) {
      setAiResult(`Ошибка: ${err.message}`);
    } finally {
      setAiLoading(false);
    }
  }, [apiKey, ideas]);

  // ---- Computed ----

  const activeIdeas = ideas.filter((i) => !i.archived);
  const archivedCount = ideas.filter((i) => i.archived).length;
  const maxWeek = Math.max(0, ...activeIdeas.map((i) => i.week), 3);
  const currentWeekIdeas = activeIdeas.filter((i) => i.week === 0);

  // ---- Render ----

  return (
    <div className="flex min-h-screen">
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        ideaCount={activeIdeas.length}
        archivedCount={archivedCount}
      />

      <main className="flex-1 p-6 overflow-y-auto" style={{ maxHeight: '100vh' }}>
        {/* Top bar */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
              {activeTab === 'topics' && '📋 Контент-план'}
              {activeTab === 'archive' && '📦 Архив'}
              {activeTab === 'calendar' && '📆 Календарь'}
            </h2>
            <p className="text-[12px] mt-1" style={{ color: 'var(--text-muted)' }}>
              {activeIdeas.length} активных тем • {archivedCount} в архиве
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button className="glass-btn text-[12px]" onClick={() => setShowAI(true)}>
              🤖 AI-анализ
            </button>
            <button className="glass-btn text-[12px]" onClick={() => setShowUpload(true)}>
              📥 Загрузить план
            </button>
            <button className="glass-btn glass-btn-primary text-[12px]" onClick={() => setShowAddModal(true)}>
              + Новая идея
            </button>
          </div>
        </div>

        {/* Tab content */}
        {activeTab === 'topics' && (
          <div className="flex gap-6">
            {/* Main content */}
            <div className="flex-1 min-w-0">
              {/* Inline add */}
              <div className="mb-4">
                <input
                  className="glass-input"
                  placeholder="Быстрое добавление идеи... (Enter)"
                  value={inlineInput}
                  onChange={(e) => setInlineInput(e.target.value)}
                  onKeyDown={handleInlineAdd}
                />
              </div>

              {/* Week groups */}
              {Array.from({ length: maxWeek + 1 }, (_, w) => w).map((weekNum) => {
                const weekIdeas = activeIdeas.filter((i) => i.week === weekNum);
                if (weekIdeas.length === 0) return null;

                return (
                  <div key={weekNum} className="mb-6">
                    <div className="flex items-center gap-2 mb-3">
                      <h3 className="text-sm font-bold" style={{ color: 'var(--text-secondary)' }}>
                        {weekNum === 0 ? 'Эта неделя' : `Неделя ${weekNum}`}
                      </h3>
                      <span className="text-[11px] px-2 py-0.5 rounded-md"
                        style={{ background: 'var(--surface)', color: 'var(--text-muted)' }}>
                        {weekIdeas.length}
                      </span>
                    </div>
                    <div className="flex flex-col gap-3"
                      onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('drag-over'); }}
                      onDragLeave={(e) => e.currentTarget.classList.remove('drag-over')}
                      onDrop={(e) => {
                        e.preventDefault();
                        e.currentTarget.classList.remove('drag-over');
                        const ideaId = e.dataTransfer.getData('text/plain');
                        if (ideaId) dropIdea(ideaId, weekNum);
                      }}
                    >
                      {weekIdeas.map((idea) => (
                        <ContentCard
                          key={idea.id}
                          idea={idea}
                          onToggleStep={toggleStep}
                          onToggleCollapse={toggleCollapse}
                          onArchive={archiveIdea}
                          onDelete={deleteIdea}
                          onUpdateTitle={updateTitle}
                          onMoveWeek={moveWeek}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}

              {activeIdeas.length === 0 && (
                <div className="flex flex-col items-center justify-center py-20">
                  <span className="text-4xl mb-4">✨</span>
                  <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>
                    Начните планировать
                  </h3>
                  <p className="text-sm mb-4" style={{ color: 'var(--text-muted)' }}>
                    Добавьте первую идею или загрузите JSON-план
                  </p>
                  <button className="glass-btn glass-btn-primary" onClick={() => setShowAddModal(true)}>
                    + Добавить идею
                  </button>
                </div>
              )}
            </div>

            {/* Right sidebar */}
            <div className="w-[280px] shrink-0 flex flex-col gap-4">
              <DayProgress ideas={ideas} />
              <WeekProgress ideas={ideas} currentWeek={0} />
              <CategoryBalance ideas={ideas} />
            </div>
          </div>
        )}

        {activeTab === 'archive' && (
          <ArchiveView
            ideas={ideas}
            onRestore={restoreIdea}
            onDelete={deleteIdea}
          />
        )}

        {activeTab === 'calendar' && (
          <CalendarView
            ideas={ideas}
            maxWeek={maxWeek}
            onToggleStep={toggleStep}
            onToggleCollapse={toggleCollapse}
            onArchive={archiveIdea}
            onDelete={deleteIdea}
            onUpdateTitle={updateTitle}
            onMoveWeek={moveWeek}
            onDropIdea={dropIdea}
          />
        )}
      </main>

      {/* Add Idea Modal */}
      {showAddModal && (
        <AddIdeaModal
          onAdd={addIdea}
          onClose={() => setShowAddModal(false)}
          currentWeek={0}
        />
      )}

      {/* Upload JSON Modal */}
      {showUpload && (
        <UploadModal
          onUpload={handleUploadJSON}
          onClose={() => setShowUpload(false)}
        />
      )}

      {/* AI Analysis Modal */}
      {showAI && (
        <AIModal
          apiKey={apiKey}
          onApiKeyChange={setApiKey}
          result={aiResult}
          loading={aiLoading}
          onRun={runAIAnalysis}
          onClose={() => { setShowAI(false); setAiResult(''); }}
        />
      )}
    </div>
  );
}

// ---- Upload Modal ----

function UploadModal({ onUpload, onClose }) {
  const [text, setText] = useState('');
  const fileRef = useRef(null);

  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => setText(ev.target.result);
    reader.readAsText(file);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="glass p-6 w-full max-w-lg mx-4"
        style={{ background: 'var(--bg-secondary)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>
            📥 Загрузить контент-план
          </h3>
          <button className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-white/10"
            style={{ color: 'var(--text-muted)' }} onClick={onClose}>✕</button>
        </div>

        <div className="mb-3">
          <input
            type="file"
            accept=".json"
            ref={fileRef}
            onChange={handleFile}
            className="hidden"
          />
          <button className="glass-btn text-[12px] w-full" onClick={() => fileRef.current?.click()}>
            📁 Выбрать JSON файл
          </button>
        </div>

        <textarea
          className="glass-input min-h-[200px] font-mono text-[12px] resize-y"
          placeholder='Вставьте JSON...\n[\n  { "t": "Название", "f": "A", "cat": "b", "w": 0 }\n]'
          value={text}
          onChange={(e) => setText(e.target.value)}
        />

        <div className="flex gap-3 mt-4">
          <button className="glass-btn flex-1" onClick={onClose}>Отмена</button>
          <button
            className="glass-btn glass-btn-primary flex-1"
            disabled={!text.trim()}
            onClick={() => onUpload(text)}
          >
            Загрузить
          </button>
        </div>
      </div>
    </div>
  );
}

// ---- AI Modal ----

function AIModal({ apiKey, onApiKeyChange, result, loading, onRun, onClose }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="glass p-6 w-full max-w-lg mx-4"
        style={{ background: 'var(--bg-secondary)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>
            🤖 AI-анализ контент-плана
          </h3>
          <button className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-white/10"
            style={{ color: 'var(--text-muted)' }} onClick={onClose}>✕</button>
        </div>

        <div className="mb-4">
          <label className="text-[11px] font-medium mb-1 block" style={{ color: 'var(--text-secondary)' }}>
            Anthropic API Key
          </label>
          <input
            type="password"
            className="glass-input text-[12px]"
            placeholder="sk-ant-..."
            value={apiKey}
            onChange={(e) => onApiKeyChange(e.target.value)}
          />
          <p className="text-[10px] mt-1" style={{ color: 'var(--text-muted)' }}>
            Ключ хранится локально и не отправляется на сторонние серверы
          </p>
        </div>

        <button
          className="glass-btn glass-btn-primary w-full mb-4"
          onClick={onRun}
          disabled={loading}
        >
          {loading ? '⏳ Анализирую...' : '✨ Запустить анализ'}
        </button>

        {result && (
          <div className="p-4 rounded-lg text-[13px] leading-relaxed whitespace-pre-wrap"
            style={{ background: 'var(--surface)', color: 'var(--text-primary)' }}>
            {result}
          </div>
        )}
      </div>
    </div>
  );
}
