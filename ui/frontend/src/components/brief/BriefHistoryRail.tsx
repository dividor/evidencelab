import React from 'react';
import { IconPlus } from './BriefIcons';
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

interface BriefHistoryRailProps {
  brief: UseBriefReturn;
}

/**
 * Left rail in the builder: the user's saved briefs (the same list as the seed
 * page's modal). Each row opens that brief; the × deletes it; the footer button
 * starts a fresh brief on the landing page.
 */
export const BriefHistoryRail: React.FC<BriefHistoryRailProps> = ({ brief }) => {
  const { history, currentBriefId } = brief;
  return (
    <aside className="brief-rail">
      <div className="brief-rail-head">
        <span className="brief-rail-title">Saved briefs</span>
        <span className="brief-rail-count">{history.length}</span>
      </div>

      <div className="brief-history-list">
        {history.length === 0 ? (
          <div className="brief-history-empty">
            No saved briefs yet. Briefs auto-save as you research.
          </div>
        ) : (
          history.map((entry) => (
            <div
              key={entry.id}
              className={`brief-history-item${
                entry.id === currentBriefId ? ' brief-history-item-active' : ''
              }`}
            >
              <button className="brief-history-item-main" onClick={() => brief.loadBrief(entry)}>
                <div className="brief-history-item-title">{entry.title}</div>
                <div className="brief-history-item-meta">
                  {entry.sectionCount} sections · {formatWhen(entry.date)}
                </div>
              </button>
              <button
                className="brief-history-del"
                title="Delete this brief"
                aria-label="Delete this brief"
                onClick={() => brief.deleteBrief(entry.id)}
              >
                ×
              </button>
            </div>
          ))
        )}
      </div>

      <div className="brief-rail-foot">
        <button className="brief-btn brief-btn-primary brief-btn-block" onClick={brief.reset}>
          <IconPlus /> New brief
        </button>
      </div>
    </aside>
  );
};
