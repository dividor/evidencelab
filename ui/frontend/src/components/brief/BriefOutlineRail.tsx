import React from 'react';
import { UseBriefReturn } from './useBrief';

interface BriefOutlineRailProps {
  brief: UseBriefReturn;
  onExport: () => void;
}

const dotClass = (status: string): string =>
  `brief-rail-dot brief-rail-dot-${status}`;

export const BriefOutlineRail: React.FC<BriefOutlineRailProps> = ({ brief, onExport }) => {
  const { sections, numbers, stage } = brief;
  const isOutline = stage === 'outline';

  return (
    <aside className="brief-rail">
      <div className="brief-rail-actions">
        <button className="brief-link-btn" onClick={brief.reset}>
          <span className="brief-icon">＋</span> New brief
        </button>
        <button className="brief-link-btn" onClick={() => brief.setHistoryOpen(true)}>
          <span className="brief-icon">⟲</span> Saved briefs
          {brief.history.length > 0 && (
            <span className="brief-count-badge">{brief.history.length}</span>
          )}
        </button>
      </div>
      <div className="brief-rail-head">
        <span className="brief-rail-title">Outline</span>
        <span className="brief-rail-count">{sections.length} sections</span>
      </div>

      <div className="brief-rail-list">
        {sections.map((s, i) => (
          <div
            key={s.id}
            className={`brief-rail-item${s.level === 2 ? ' brief-rail-item-sub' : ''}`}
          >
            <span className={dotClass(s.status)} />
            <span className="brief-rail-item-title">
              {numbers[i]}. {s.title}
            </span>
            {isOutline && (
              <span className="brief-rail-controls">
                <button title="Indent / outdent" onClick={() => brief.indentSection(s.id)}>
                  {s.level === 2 ? '⇤' : '⇥'}
                </button>
                <button title="Move up" onClick={() => brief.moveSection(s.id, -1)}>
                  ↑
                </button>
                <button title="Move down" onClick={() => brief.moveSection(s.id, 1)}>
                  ↓
                </button>
                <button title="Remove" onClick={() => brief.removeSection(s.id)}>
                  ×
                </button>
              </span>
            )}
          </div>
        ))}
      </div>

      {isOutline && (
        <div className="brief-rail-add">
          <input
            value={brief.newHeading}
            onChange={(e) => brief.setNewHeading(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') brief.addSection();
            }}
            placeholder="Add a section…"
          />
          <button onClick={brief.addSection}>+</button>
        </div>
      )}

      <div className="brief-rail-foot">
        {stage === 'outline' && (
          <button
            className="brief-btn brief-btn-primary brief-btn-block"
            onClick={brief.startResearch}
            disabled={!sections.length}
          >
            Start deep research →
          </button>
        )}
        {stage === 'research' && (
          <div className="brief-rail-progress">
            <div className="brief-rail-progress-row">
              <span>Researching…</span>
              <span>
                {brief.doneCount}/{sections.length}
              </span>
            </div>
            <div className="brief-progress-track">
              <div
                className="brief-progress-fill"
                style={{ width: `${brief.totalProgress}%` }}
              />
            </div>
          </div>
        )}
        {stage === 'done' && (
          <button className="brief-btn brief-btn-secondary brief-btn-block" onClick={onExport}>
            ⤓ Export brief
          </button>
        )}
      </div>
    </aside>
  );
};
