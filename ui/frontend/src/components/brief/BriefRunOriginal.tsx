import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatWhen, KIND_LABEL } from './BriefSectionAudit';
import { SectionRunDetail } from './briefTypes';

// A stored original of a section, as the API returned it: the agent's text
// with its own `[n]` markers, its source records, and the table that traces
// each agent number to the brief source it was mapped to and (for the current
// run) the number readers see. Read-only; the original is never edited.
//
// The text is shown formatted by default (headings, lists, emphasis), with the
// agent's own `[n]` numbers left as they are; "Raw" shows the markdown exactly
// as returned, for checking what the agent wrote.

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
    ? 'kept exactly as returned'
    : 'trimmed to the cited records, without excerpts (an earlier run)';

/** A chunk id's first block, enough to tell rows apart; the full id is its tooltip. */
export const shortChunkId = (chunkId: string): string =>
  chunkId.length > 9 ? `${chunkId.slice(0, 8)}…` : chunkId;

type TextView = 'formatted' | 'raw';

const ViewSwitch: React.FC<{ view: TextView; onChange: (v: TextView) => void }> = ({
  view,
  onChange,
}) => (
  <div className="brief-original-switch" role="group" aria-label="How to show the text">
    {(['formatted', 'raw'] as const).map((v) => (
      <button
        key={v}
        type="button"
        aria-pressed={view === v}
        className={view === v ? 'is-active' : ''}
        onClick={() => onChange(v)}
      >
        {v === 'formatted' ? 'Formatted' : 'Raw'}
      </button>
    ))}
  </div>
);

const Warnings: React.FC<{ detail: SectionRunDetail }> = ({ detail }) => (
  <>
    {detail.unresolved.length > 0 && (
      <div className="brief-section-warning" role="status">
        Markers with no source, shown as{' '}
        {detail.unresolved.map((u) => `[?${u.n}]`).join(', ')}:{' '}
        {detail.unresolved
          .map(
            (u) =>
              `[${u.n}] ${u.reason === 'no-chunk-id' ? 'record had no chunk id' : 'never returned'}`,
          )
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
  </>
);

const TraceTable: React.FC<{ detail: SectionRunDetail }> = ({ detail }) => (
  <div className="brief-trace-scroll">
    <table className="brief-trace-table">
      <thead>
        <tr>
          <th className="brief-trace-num">Agent</th>
          <th className="brief-trace-num">Shown as</th>
          <th>Brief source</th>
          <th className="brief-trace-doc">Document</th>
          <th className="brief-trace-num">Page</th>
          <th>Chunk</th>
        </tr>
      </thead>
      <tbody>
        {traceRows(detail).map((r) => (
          <tr key={r.agent}>
            <td className="brief-trace-num">[{r.agent}]</td>
            <td className="brief-trace-num">{r.display != null ? `[${r.display}]` : '—'}</td>
            <td>{r.sourceId}</td>
            <td className="brief-trace-doc">{r.title}</td>
            <td className="brief-trace-num">{r.page ?? ''}</td>
            <td>
              {r.chunkId && (
                <code className="brief-trace-chunk" title={r.chunkId}>
                  {shortChunkId(r.chunkId)}
                </code>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

export const BriefRunOriginal: React.FC<{
  title: string;
  detail: SectionRunDetail | null;
  error: string | null;
  onClose: () => void;
}> = ({ title, detail, error, onClose }) => {
  const [view, setView] = useState<TextView>('formatted');
  return (
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
        {!detail && !error && (
          <div className="brief-modal-empty">Loading the stored original…</div>
        )}
        {detail && (
          <div className="brief-original">
            <dl className="brief-original-meta">
              <div>
                <dt>Run</dt>
                <dd>
                  {detail.id}
                  {detail.runId ? ` (agent run ${detail.runId})` : ''}
                </dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{detail.status}</dd>
              </div>
              <div>
                <dt>Sources</dt>
                <dd>{retainedNote(detail)}</dd>
              </div>
            </dl>
            <Warnings detail={detail} />
            <section className="brief-original-part">
              <div className="brief-original-part-head">
                <h3 className="brief-modal-section-title">Text as the agent returned it</h3>
                <ViewSwitch view={view} onChange={setView} />
              </div>
              {view === 'formatted' ? (
                <div className="brief-original-text" data-testid="original-formatted">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.content}</ReactMarkdown>
                </div>
              ) : (
                <pre className="brief-original-text brief-original-raw">{detail.content}</pre>
              )}
            </section>
            <section className="brief-original-part">
              <div className="brief-original-part-head">
                <h3 className="brief-modal-section-title">Where each number went</h3>
              </div>
              {Object.keys(detail.displayNumbers).length === 0 && (
                <p className="brief-original-note">
                  &ldquo;Shown as&rdquo; numbers apply to the section&rsquo;s current run only.
                </p>
              )}
              <TraceTable detail={detail} />
            </section>
          </div>
        )}
      </div>
    </div>
  );
};
