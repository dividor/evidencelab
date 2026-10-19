import React from 'react';
import { formatWhen, KIND_LABEL } from './BriefSectionAudit';
import { SectionRunDetail } from './briefTypes';

// A stored original of a section, as the API returned it: the agent's text
// with its own `[n]` markers, its source records, and the table that traces
// each agent number to the brief source it was mapped to and (for the current
// run) the number readers see. Read-only; the original is never edited.

interface TraceRow {
  agent: number;
  display?: number;
  sourceId: string;
  title: string;
  page?: number | null;
  chunkId?: string;
}

const traceRows = (detail: SectionRunDetail): TraceRow[] => {
  const byIndex = new Map<number, SectionRunDetail['sources'][number]>();
  detail.sources.forEach((src) => {
    if (src.index != null) byIndex.set(src.index, src);
  });
  return Object.entries(detail.mapping)
    .map(([agent, sourceId]) => {
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
    })
    .sort((a, b) => a.agent - b.agent);
};

const retainedNote = (detail: SectionRunDetail): string =>
  detail.sourcesRetained === 'exact'
    ? 'sources kept exactly as returned'
    : 'sources trimmed to the cited records, without excerpts (an earlier run)';

export const BriefRunOriginal: React.FC<{
  title: string;
  detail: SectionRunDetail | null;
  error: string | null;
  onClose: () => void;
}> = ({ title, detail, error, onClose }) => (
  <div className="brief-modal-overlay" onClick={onClose}>
    <div className="brief-modal brief-modal-wide" onClick={(e) => e.stopPropagation()}>
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
      {error && <div className="brief-error">{error}</div>}
      {!detail && !error && <div className="brief-modal-empty">Loading the stored original…</div>}
      {detail && (
        <div className="brief-original">
          <div className="brief-original-meta">
            Run {detail.id}
            {detail.runId ? ` · agent run ${detail.runId}` : ''} · {detail.status} ·{' '}
            {retainedNote(detail)}
          </div>
          {detail.unresolved.length > 0 && (
            <div className="brief-section-warning" role="status">
              Markers with no source, shown as{' '}
              {detail.unresolved.map((u) => `[?${u.n}]`).join(', ')}:{' '}
              {detail.unresolved
                .map((u) => `[${u.n}] ${u.reason === 'no-chunk-id' ? 'record had no chunk id' : 'never returned'}`)
                .join('; ')}
              .
            </div>
          )}
          {detail.rejected.length > 0 && (
            <div className="brief-section-warning" role="status">
              Source records rejected for having no chunk id:{' '}
              {detail.rejected.map((r) => `[${r.index ?? '?'}]`).join(', ')}.
            </div>
          )}
          <div className="brief-modal-section-title">Text as the agent returned it</div>
          <pre className="brief-original-text">{detail.content}</pre>
          <div className="brief-modal-section-title">
            Where each number went
            {Object.keys(detail.displayNumbers).length === 0 && ' (shown-as numbers apply to the current run only)'}
          </div>
          <table className="brief-trace-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Shown as</th>
                <th>Brief source</th>
                <th>Document</th>
                <th>Page</th>
                <th>Chunk</th>
              </tr>
            </thead>
            <tbody>
              {traceRows(detail).map((r) => (
                <tr key={r.agent}>
                  <td>[{r.agent}]</td>
                  <td>{r.display != null ? `[${r.display}]` : '—'}</td>
                  <td>{r.sourceId}</td>
                  <td>{r.title}</td>
                  <td>{r.page ?? ''}</td>
                  <td className="brief-trace-chunk">{r.chunkId || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  </div>
);
