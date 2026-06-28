import React, { useMemo, useState } from 'react';
import { IconCopy, IconSearch } from './BriefIcons';
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
  const { history } = brief;
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return history;
    return history.filter(
      (e) => e.title.toLowerCase().includes(q) || (e.query || '').toLowerCase().includes(q),
    );
  }, [history, query]);

  if (!brief.historyOpen) return null;

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

        {history.length > 0 && (
          <div className="brief-modal-search">
            <IconSearch size={15} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search briefs…"
              aria-label="Search briefs"
            />
          </div>
        )}

        {history.length === 0 ? (
          <div className="brief-modal-empty">
            No saved briefs yet. Generate and research a brief — it’ll appear here automatically.
          </div>
        ) : filtered.length === 0 ? (
          <div className="brief-modal-empty">No briefs match “{query.trim()}”.</div>
        ) : (
          <div className="brief-modal-list">
            {filtered.map((entry) => (
              <div key={entry.id} className="brief-modal-row">
                <button className="brief-modal-row-main" onClick={() => brief.loadBrief(entry)}>
                  <div className="brief-modal-row-title">{entry.title}</div>
                  <div className="brief-modal-row-query">{entry.query}</div>
                  <div className="brief-modal-row-meta">
                    {entry.sectionCount} sections · {entry.sourceCount} sources ·{' '}
                    {formatWhen(entry.date)}
                  </div>
                </button>
                <button
                  className="brief-modal-row-act"
                  title="Duplicate this brief"
                  aria-label="Duplicate this brief"
                  onClick={() => brief.cloneBrief(entry)}
                >
                  <IconCopy size={14} />
                </button>
                <button
                  className="brief-modal-row-del"
                  title="Delete this brief"
                  aria-label="Delete this brief"
                  onClick={() => brief.deleteBrief(entry.id)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
