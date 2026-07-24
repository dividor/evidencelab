import React from 'react';
import { SectionAuditEntry, SectionAuditKind } from './briefTypes';

// Per-section research/audit log modal — the full provenance of a section:
// every generate/edit/update, its question/instruction, and what it drew in.
// Mirrors BriefHistoryModal's structure/classes so it reads as the same modal.

const KIND_LABEL: Record<SectionAuditKind, string> = {
  generate: 'Generated',
  edit: 'Edited',
  update: 'Updated',
};

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

interface Props {
  title: string;
  audit: SectionAuditEntry[];
  onClose: () => void;
}

export const BriefSectionAudit: React.FC<Props> = ({ title, audit, onClose }) => (
  <div className="brief-modal-overlay" onClick={onClose}>
    <div className="brief-modal" onClick={(e) => e.stopPropagation()}>
      <div className="brief-modal-head">
        <div>
          <div className="brief-modal-title">Research log</div>
          <div className="brief-modal-sub">{title}</div>
        </div>
        <button className="brief-modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>

      {audit.length === 0 ? (
        <div className="brief-modal-empty">No research activity recorded for this section yet.</div>
      ) : (
        <div className="brief-modal-list">
          {[...audit]
            .slice()
            .reverse()
            .map((e) => (
              <div key={e.id} className="brief-modal-row">
                <div className="brief-modal-row-main">
                  <div className="brief-modal-row-title">
                    <span className={`brief-audit-kind brief-audit-kind-${e.kind}`}>
                      {KIND_LABEL[e.kind]}
                    </span>
                  </div>
                  {e.question && (
                    <div className="brief-modal-row-query">
                      <span className="brief-audit-label">Question</span> {e.question}
                    </div>
                  )}
                  {e.instruction && (
                    <div className="brief-modal-row-query">
                      <span className="brief-audit-label">Instruction</span> {e.instruction}
                    </div>
                  )}
                  <div className="brief-modal-row-meta">
                    {formatWhen(e.at)}
                    {e.sourceCount != null
                      ? ` · ${e.sourceCount} source${e.sourceCount === 1 ? '' : 's'}`
                      : ''}
                    {e.addedSourceCount ? ` · ${e.addedSourceCount} new` : ''}
                  </div>
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  </div>
);
