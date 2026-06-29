import React, { useMemo, useState } from 'react';
import { IconCopy, IconPlus, IconSearch } from './BriefIcons';
import { SavedBrief } from './briefTypes';
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

// How many briefs the rail shows before offering "See more".
const VISIBLE_CAP = 10;

/**
 * Left rail in the builder: the user's brief history. The brief currently open
 * is pinned at the top under a "Selected" label, separated from the searchable
 * list of the others. Rows open, clone, or delete a brief.
 */
export const BriefHistoryRail: React.FC<BriefHistoryRailProps> = ({ brief }) => {
  const { history, currentBriefId } = brief;
  const [query, setQuery] = useState('');

  const selected = useMemo(
    () => history.find((e) => e.id === currentBriefId),
    [history, currentBriefId],
  );

  const others = useMemo(() => {
    const q = query.trim().toLowerCase();
    return history.filter((e) => {
      if (e.id === currentBriefId) return false;
      if (!q) return true;
      return e.title.toLowerCase().includes(q) || (e.query || '').toLowerCase().includes(q);
    });
  }, [history, currentBriefId, query]);

  const renderRow = (entry: SavedBrief, isSelected: boolean): React.ReactNode => (
    <div className={`brief-history-item${isSelected ? ' brief-history-item-active' : ''}`}>
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
      {!isSelected && (
        <button
          className="brief-history-del"
          title="Delete this brief"
          aria-label="Delete this brief"
          onClick={() => brief.deleteBrief(entry.id)}
        >
          ×
        </button>
      )}
    </div>
  );

  return (
    <aside className="brief-rail">
      <div className="brief-rail-head">
        <span className="brief-rail-title">History</span>
        <span className="brief-rail-count">{history.length}</span>
      </div>

      {selected && (
        <div className="brief-history-selected">
          <div className="brief-history-selected-label">Selected</div>
          {renderRow(selected, true)}
        </div>
      )}

      {others.length > 0 && (
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
        ) : others.length === 0 ? (
          <div className="brief-history-empty">
            {query.trim() ? `No briefs match “${query.trim()}”.` : 'No other saved briefs.'}
          </div>
        ) : (
          others.slice(0, VISIBLE_CAP).map((entry) => (
            <React.Fragment key={entry.id}>{renderRow(entry, false)}</React.Fragment>
          ))
        )}
      </div>

      {others.length > VISIBLE_CAP && (
        <button className="brief-see-more" onClick={() => brief.setHistoryOpen(true)}>
          See more
        </button>
      )}

      <div className="brief-rail-foot">
        <button className="brief-btn brief-btn-primary brief-btn-block" onClick={brief.reset}>
          <IconPlus /> New brief
        </button>
      </div>
    </aside>
  );
};
