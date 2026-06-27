import React from 'react';
import { UseBriefReturn } from './useBrief';

const formatWhen = (ts: number): string => {
  try {
    const d = new Date(ts);
    return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} · ${d.toLocaleTimeString(
      undefined,
      { hour: 'numeric', minute: '2-digit' },
    )}`;
  } catch {
    return '';
  }
};

interface BriefHistoryModalProps {
  brief: UseBriefReturn;
}

export const BriefHistoryModal: React.FC<BriefHistoryModalProps> = ({ brief }) => {
  if (!brief.historyOpen) return null;
  const { history } = brief;
  return (
    <div className="brief-modal-overlay" onClick={() => brief.setHistoryOpen(false)}>
      <div className="brief-modal" onClick={(e) => e.stopPropagation()}>
        <div className="brief-modal-head">
          <div>
            <div className="brief-modal-title">Saved briefs</div>
            <div className="brief-modal-sub">
              Briefs auto-save as you research. Open one to continue.
            </div>
          </div>
          <button className="brief-modal-close" onClick={() => brief.setHistoryOpen(false)}>
            ×
          </button>
        </div>
        {history.length === 0 ? (
          <div className="brief-modal-empty">
            No saved briefs yet. Generate and research a brief — it’ll appear here automatically.
          </div>
        ) : (
          <div className="brief-modal-list">
            {history.map((entry) => (
              <button
                key={entry.id}
                className="brief-modal-row"
                onClick={() => brief.loadBrief(entry)}
              >
                <div className="brief-modal-row-title">{entry.title}</div>
                <div className="brief-modal-row-query">{entry.query}</div>
                <div className="brief-modal-row-meta">
                  {entry.sectionCount} sections · {entry.sourceCount} sources · {formatWhen(entry.date)}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
