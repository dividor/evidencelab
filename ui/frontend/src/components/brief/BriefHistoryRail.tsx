import React, { useMemo, useState } from 'react';
import { IconCopy, IconPlus, IconSearch } from './BriefIcons';
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
 * Left rail in the builder: the user's brief history. Searchable; each row opens
 * that brief, clones it, or deletes it. The footer button starts a fresh brief
 * on the landing page.
 */
export const BriefHistoryRail: React.FC<BriefHistoryRailProps> = ({ brief }) => {
  const { history, currentBriefId } = brief;
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return history;
    return history.filter(
      (e) =>
        e.title.toLowerCase().includes(q) || (e.query || '').toLowerCase().includes(q),
    );
  }, [history, query]);

  return (
    <aside className="brief-rail">
      <div className="brief-rail-head">
        <span className="brief-rail-title">History</span>
        <span className="brief-rail-count">{history.length}</span>
      </div>

      {history.length > 0 && (
        <div className="brief-history-search">
          <IconSearch size={14} />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search briefs…"
            aria-label="Search briefs"
          />
        </div>
      )}

      <div className="brief-history-list">
        {history.length === 0 ? (
          <div className="brief-history-empty">
            No saved briefs yet. Briefs auto-save as you research.
          </div>
        ) : filtered.length === 0 ? (
          <div className="brief-history-empty">No briefs match “{query.trim()}”.</div>
        ) : (
          filtered.map((entry) => (
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
                className="brief-history-act"
                title="Duplicate this brief"
                aria-label="Duplicate this brief"
                onClick={() => brief.cloneBrief(entry)}
              >
                <IconCopy size={13} />
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
