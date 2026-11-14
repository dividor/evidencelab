import React from 'react';
import type { CitationVerdict } from '../../types/testing';
import type { BriefFactCheckDefaults } from '../../types/auth';

/**
 * Group Settings → Fact Checker: which citation-check verdicts the Fact
 * Checker highlights in an open brief for this group's members. A group
 * that does not opt in contributes nothing; the API then highlights the
 * system default (unsupported passages only).
 */

export const DEFAULT_FACT_CHECK_VERDICTS: CitationVerdict[] = ['unsupported'];

export const VERDICT_OPTIONS: { value: CitationVerdict; label: string; help: string }[] = [
  {
    value: 'unsupported',
    label: 'Unsupported',
    help: 'The cited excerpts do not back the passage, or contradict it.',
  },
  {
    value: 'partially_supported',
    label: 'Partially supported',
    help: 'The core statement is there, but an element is absent, overstated or altered.',
  },
  {
    value: 'cannot_assess',
    label: 'Cannot assess',
    help: 'The excerpts were empty or unreadable, a citation had no source, or the judge failed.',
  },
  {
    value: 'supported',
    label: 'Supported',
    help: 'Every factual element is stated in, or follows from, the excerpts.',
  },
];

/** The group's choice, or null when it has not opted in. */
export const readFactCheckDefaults = (
  settings: BriefFactCheckDefaults | null | undefined,
): CitationVerdict[] | null => settings?.briefFactCheckVerdicts ?? null;

/** What a group saves: the key only when the group opted in. */
export const factCheckPayload = (value: CitationVerdict[] | null): BriefFactCheckDefaults =>
  value ? { briefFactCheckVerdicts: value } : {};

interface FactCheckGroupSectionProps {
  value: CitationVerdict[] | null;
  onChange: (value: CitationVerdict[] | null) => void;
}

export const FactCheckGroupSection: React.FC<FactCheckGroupSectionProps> = ({ value, onChange }) => {
  const toggleVerdict = (verdict: CitationVerdict, on: boolean) => {
    const current = value || [];
    const next = on ? [...current, verdict] : current.filter((v) => v !== verdict);
    // Keep the canonical order so the saved list reads the same every time.
    onChange(VERDICT_OPTIONS.map((o) => o.value).filter((v) => next.includes(v)));
  };
  return (
    <div className="filter-section">
      <div className="filter-section-content">
        <p className="admin-group-settings-description">
          On an open brief that has a completed citation check (Testing → Brief), the
          <strong> Fact Checker</strong> button highlights the passages the judge flagged and shows
          its explanation on hover. Choose which verdicts are highlighted for this group.
        </p>
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
          <input
            type="checkbox"
            checked={value !== null}
            onChange={(e) => onChange(e.target.checked ? [...DEFAULT_FACT_CHECK_VERDICTS] : null)}
          />
          Configure the highlighted verdicts for this group
        </label>
        {value !== null && (
          <div className="group-fact-check-verdicts" style={{ marginTop: '10px' }}>
            {VERDICT_OPTIONS.map((option) => (
              <label
                key={option.value}
                className={`rerank-checkbox-label group-fact-check-verdict brief-fact-mark-${option.value}`}
              >
                <input
                  type="checkbox"
                  checked={value.includes(option.value)}
                  onChange={(e) => toggleVerdict(option.value, e.target.checked)}
                />
                <span>{option.label}</span>
                <span className="rerank-tooltip" title={option.help}>
                  ⓘ
                </span>
              </label>
            ))}
            <p style={{ fontSize: '11px', color: '#6b7280', marginTop: '6px' }}>
              Default: Unsupported only. With nothing ticked, the button highlights nothing.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
