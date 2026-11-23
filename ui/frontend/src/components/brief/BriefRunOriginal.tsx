import React from 'react';
import { formatWhen, KIND_LABEL } from './BriefSectionAudit';
import { SectionRunDetail, UnresolvedMarker } from './briefTypes';

// A stored original of a section, as the API returned it: the agent's text
// with its own `[n]` markers, its source records, and the table that traces
// each agent number to the brief source it was mapped to and (for the current
// run) the number readers see. Read-only; the original is never edited.
// Administrators only (Section History → Original).

interface TraceRow {
  agent: number;
  display?: number;
  sourceId?: string;
  title?: string;
  page?: number | null;
  chunkId?: string;
  // Set for a marker the agent cited without a usable source.
  unresolved?: UnresolvedMarker['reason'];
}

const UNRESOLVED_TEXT: Record<UnresolvedMarker['reason'], string> = {
  'no-source': 'The agent returned no source with this number',
  'no-chunk-id': 'The source record had no chunk id',
};

const STATUS_LABEL: Record<SectionRunDetail['status'], string> = {
  current: 'Current',
  superseded: 'Superseded',
  rejected: 'Rejected',
};

// `[3]` or `[2, 25]`: the same marker shape the API numbers.
const MARKER_RE = /(\[\d+(?:,\s*\d+)*\])/g;

const markerNumbers = (marker: string): number[] =>
  marker
    .slice(1, -1)
    .split(',')
    .map((part) => Number(part.trim()));

const traceRows = (detail: SectionRunDetail): TraceRow[] => {
  const byIndex = new Map<number, SectionRunDetail['sources'][number]>();
  detail.sources.forEach((src) => {
    if (src.index != null) byIndex.set(src.index, src);
  });
  const mapped: TraceRow[] = Object.entries(detail.mapping).map(([agent, sourceId]) => {
    const n = Number(agent);
    const src = byIndex.get(n);
    return {
      agent: n,
      display: detail.displayNumbers[agent],
      sourceId,
      title: src?.title || '',
      page: src?.page,
      chunkId: src?.chunkId,
    };
  });
  const seen = new Set<number>();
  const missing: TraceRow[] = [];
  detail.unresolved.forEach((u) => {
    if (seen.has(u.n)) return;
    seen.add(u.n);
    missing.push({ agent: u.n, unresolved: u.reason });
  });
  return [...mapped, ...missing].sort((a, b) => a.agent - b.agent);
};

// The agent's text, unchanged, with its citation markers picked out: the
// ones without a source in the warning colour.
const OriginalText: React.FC<{ content: string; unresolved: Set<number> }> = ({
  content,
  unresolved,
}) => (
  <pre className="brief-original-text">
    {content.split(MARKER_RE).map((part, i) => {
      if (i % 2 === 0) return part;
      const bad = markerNumbers(part).some((n) => unresolved.has(n));
      return (
        <span
          key={i}
          className={`brief-original-marker${bad ? ' brief-original-marker-bad' : ''}`}
          title={bad ? 'Cites a number with no source' : undefined}
        >
          {part}
        </span>
      );
    })}
  </pre>
);

const Fact: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="brief-original-fact">
    <dt>{label}</dt>
    <dd>{children}</dd>
  </div>
);

const RunFacts: React.FC<{ detail: SectionRunDetail }> = ({ detail }) => (
  <dl className="brief-original-facts">
    <Fact label="Run">
      {detail.id} · {STATUS_LABEL[detail.status]}
    </Fact>
    <Fact label="Sources returned">{detail.sources.length}</Fact>
    <Fact label="Sources kept">
      {detail.sourcesRetained === 'exact'
        ? 'Exactly as returned'
        : 'Cited records only, without excerpts (an earlier run)'}
    </Fact>
    {detail.runId && (
      <Fact label="Agent run">
        <span className="brief-original-mono">{detail.runId}</span>
      </Fact>
    )}
  </dl>
);

const UnresolvedNotice: React.FC<{ unresolved: UnresolvedMarker[] }> = ({ unresolved }) => {
  if (!unresolved.length) return null;
  const rows = traceRowsOfUnresolved(unresolved);
  return (
    <div className="brief-section-warning brief-original-notice" role="status">
      <div className="brief-original-notice-title">
        {rows.length === 1
          ? 'One citation marker has no source'
          : `${rows.length} citation markers have no source`}
      </div>
      <ul>
        {rows.map((u) => (
          <li key={u.n}>
            <strong>[{u.n}]</strong>, shown to readers as <strong>[?{u.n}]</strong>:{' '}
            {UNRESOLVED_TEXT[u.reason].toLowerCase()}.
          </li>
        ))}
      </ul>
    </div>
  );
};

// One line per number, in the order the text cites them.
const traceRowsOfUnresolved = (unresolved: UnresolvedMarker[]): UnresolvedMarker[] => {
  const seen = new Set<number>();
  return unresolved.filter((u) => {
    if (seen.has(u.n)) return false;
    seen.add(u.n);
    return true;
  });
};

const shownAs = (row: TraceRow, hasDisplay: boolean): React.ReactNode => {
  if (row.unresolved) return `[?${row.agent}]`;
  if (row.display != null) return `[${row.display}]`;
  return <span className="brief-trace-muted">{hasDisplay ? 'Not cited' : '—'}</span>;
};

const TraceTable: React.FC<{ detail: SectionRunDetail }> = ({ detail }) => {
  const hasDisplay = Object.keys(detail.displayNumbers).length > 0;
  const rows = traceRows(detail);
  return (
    <div className="brief-trace-wrap">
      <table className="brief-trace-table">
        <thead>
          <tr>
            <th>Agent no.</th>
            <th>Shown as</th>
            <th>Brief source</th>
            <th>Document</th>
            <th>Page</th>
            <th>Chunk</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) =>
            r.unresolved ? (
              <tr key={r.agent} className="brief-trace-row-bad">
                <td>[{r.agent}]</td>
                <td>{shownAs(r, hasDisplay)}</td>
                <td colSpan={4}>{UNRESOLVED_TEXT[r.unresolved]}</td>
              </tr>
            ) : (
              <tr key={r.agent}>
                <td>[{r.agent}]</td>
                <td>{shownAs(r, hasDisplay)}</td>
                <td>{r.sourceId}</td>
                <td>{r.title}</td>
                <td>{r.page ?? ''}</td>
                <td className="brief-original-mono">{r.chunkId || ''}</td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
};

const OriginalBody: React.FC<{ detail: SectionRunDetail }> = ({ detail }) => {
  const unresolved = new Set(detail.unresolved.map((u) => u.n));
  const hasDisplay = Object.keys(detail.displayNumbers).length > 0;
  return (
    <div className="brief-original">
      <RunFacts detail={detail} />
      <UnresolvedNotice unresolved={detail.unresolved} />
      {detail.rejected.length > 0 && (
        <div className="brief-section-warning brief-original-notice" role="status">
          Source records rejected for having no chunk id:{' '}
          {detail.rejected.map((r) => `[${r.index ?? '?'}]`).join(', ')}.
        </div>
      )}
      <section>
        <h3 className="brief-modal-section-title">Text as the agent returned it</h3>
        <p className="brief-original-hint">
          Unchanged, with the agent&apos;s own citation numbers.
        </p>
        <OriginalText content={detail.content} unresolved={unresolved} />
      </section>
      <section>
        <h3 className="brief-modal-section-title">Where each number went</h3>
        <p className="brief-original-hint">
          {hasDisplay
            ? 'Every source the agent returned, and the number readers see for the ones it cited.'
            : 'Every source the agent returned. Shown-as numbers apply to the current run only.'}
        </p>
        <TraceTable detail={detail} />
      </section>
    </div>
  );
};

export const BriefRunOriginal: React.FC<{
  title: string;
  detail: SectionRunDetail | null;
  error: string | null;
  onClose: () => void;
}> = ({ title, detail, error, onClose }) => (
  <div className="brief-modal-overlay" onClick={onClose}>
    <div
      className="brief-modal brief-modal-wide"
      role="dialog"
      aria-label="Original output"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="brief-modal-head">
        <div>
          <div className="brief-modal-title">Original output</div>
          <div className="brief-modal-sub">
            {title}
            {detail ? ` · ${KIND_LABEL[detail.mode]} · ${formatWhen(detail.at)}` : ''}
          </div>
        </div>
        <button className="brief-modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      {error && <div className="brief-error brief-original-error">{error}</div>}
      {!detail && !error && <div className="brief-modal-empty">Loading the stored original…</div>}
      {detail && <OriginalBody detail={detail} />}
    </div>
  </div>
);
