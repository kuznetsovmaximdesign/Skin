import React from 'react';
import { TABS } from '../data/initialData';

export default function Sidebar({ activeTab, onTabChange, ideaCount, archivedCount }) {
  return (
    <aside className="w-[220px] min-h-screen p-4 flex flex-col gap-2 border-r"
      style={{ borderColor: 'var(--border)', background: 'var(--bg-secondary)' }}>

      <div className="flex items-center gap-3 mb-6 px-2">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: 'var(--accent)', boxShadow: '0 0 16px var(--accent-glow)' }}>
          <span className="text-white text-sm font-bold">A</span>
        </div>
        <div>
          <h1 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Aurora</h1>
          <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Content Tracker</p>
        </div>
      </div>

      <nav className="flex flex-col gap-1">
        {TABS.map((tab) => {
          const isActive = activeTab === tab.id;
          const count = tab.id === 'topics' ? ideaCount : tab.id === 'archive' ? archivedCount : null;
          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-left text-sm font-medium transition-all"
              style={{
                background: isActive ? 'var(--surface-hover)' : 'transparent',
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              }}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
              {count != null && (
                <span className="ml-auto text-[11px] px-1.5 py-0.5 rounded-md"
                  style={{ background: 'var(--surface)', color: 'var(--text-muted)' }}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="mt-auto pt-4 border-t" style={{ borderColor: 'var(--border)' }}>
        <p className="text-[11px] px-2" style={{ color: 'var(--text-muted)' }}>
          Aurora Tracker v1.0
        </p>
      </div>
    </aside>
  );
}
