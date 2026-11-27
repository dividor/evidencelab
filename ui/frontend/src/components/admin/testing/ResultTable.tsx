import React, { useState } from 'react';
import type { TestResult } from '../../../types/testing';
import { formatMs, formatScore, prettyJson } from './testingFormat';
import { ClaimCells, ClaimHeaders } from './BriefScoreStats';
import { resultWarnings } from './resultWarnings';
import AssertionResultRow from './AssertionResultRow';
import GeneratedSection from './GeneratedSection';

export function ResultTable({ heading, timeLabel = 'Latency', brief = false, children }: {
  heading: string; timeLabel?: string; brief?: boolean; children: React.ReactNode;
}) {
  return <table className="admin-table testing-result-table" aria-label={heading}><thead><tr>
    <th aria-label="expand" /><th>{heading}</th><th>Status</th>
    <th>{brief ? 'Total Score' : 'Score'}</th>{brief && <ClaimHeaders />}<th>{timeLabel}</th><th>Error</th>
  </tr></thead><tbody>{children}</tbody></table>;
}

/* ------------------------------------------------------------------ */
/*  Human-friendly output: AI summary + sources, or search cards      */
/* ------------------------------------------------------------------ */

type OutputBlob = Record<string, unknown> | null | undefined;

const asArray = (v: unknown): Record<string, unknown>[] =>
  Array.isArray(v) ? (v as Record<string, unknown>[]) : [];

const str = (v: unknown): string => (typeof v === 'string' ? v : '');

const SourceCard: React.FC<{ r: Record<string, unknown>; index: number }> = ({
  r,
  index,
}) => {
  const title =
    str(r.title) || str(r.map_title) || str(r.doc_id) || `Result ${index + 1}`;
  const org = str(r.organization) || str(r.map_organization);
  const score = typeof r.score === 'number' ? r.score : undefined;
  const text = str(r.text);
  return (
    <div className="testing-result-card">
      <div className="testing-result-card-head">
        <span className="testing-result-card-num">{index + 1}</span>
        <span className="testing-result-card-title">{title}</span>
        {score !== undefined && (
          <span className="testing-result-card-score">{score.toFixed(3)}</span>
        )}
      </div>
      {org && <div className="testing-result-card-org">{org}</div>}
      {text && (
        <div className="testing-result-card-snippet">
          {text.length > 500 ? `${text.slice(0, 500)}…` : text}
        </div>
      )}
    </div>
  );
};

const ReferenceItem: React.FC<{ entry: Record<string, unknown> }> = ({ entry }) => {
  const title = str(entry.title) || str(entry.doc_id) || 'Unknown';
  const org = str(entry.organization);
  const year = entry.year !== null && entry.year !== undefined ? String(entry.year) : '';
  const url = str(entry.url);
  const meta = [org, year].filter(Boolean).join(', ');
  const num = entry.number !== undefined ? String(entry.number) : '';
  return (
    <li className="testing-reference">
      {num && <span className="testing-reference-num">[{num}]</span>}{' '}
      {url ? (
        <a href={url} target="_blank" rel="noreferrer">
          {title}
        </a>
      ) : (
        <span>{title}</span>
      )}
      {meta && <span className="text-muted"> — {meta}</span>}
    </li>
  );
};

const ResultOutput: React.FC<{ output: OutputBlob }> = ({ output }) => {
  const [showRaw, setShowRaw] = useState(false);
  if (!output) return <p className="text-muted" style={{ margin: 0 }}>No output.</p>;

  const summary = str(output.summary);
  const brief = output.capability === 'brief';
  const references = asArray(output.references);
  const sources = asArray(brief ? output.sources : output.search_results);
  const searchResults = asArray(output.results);

  return (
    <div className="testing-output">
      {summary ? (
        <>
          {!brief && (
            <>
              <span className="testing-case-label">AI summary (with references)</span>
              <div className="testing-summary-text">{summary}</div>
            </>
          )}
          {brief && asArray(output.siblings).map((s, i) => (
            <details key={i}><summary>Compare with {str(s.title)}</summary><p>{str(s.content)}</p></details>
          ))}
          {references.length > 0 && (
            <>
              <span className="testing-case-label">
                Cited references ({references.length})
              </span>
              <ol className="testing-references">
                {references.map((entry, i) => (
                  <ReferenceItem key={i} entry={entry} />
                ))}
              </ol>
            </>
          )}
          {sources.length > 0 && (
            <>
              <span className="testing-case-label">Sources ({sources.length})</span>
              <div className="testing-result-cards">
                {sources.map((r, i) => (
                  <SourceCard key={i} r={r} index={brief && typeof r.index === 'number' ? r.index - 1 : i} />
                ))}
              </div>
            </>
          )}
        </>
      ) : searchResults.length > 0 ? (
        <>
          <span className="testing-case-label">Search results ({searchResults.length})</span>
          <div className="testing-result-cards">
            {searchResults.map((r, i) => (
              <SourceCard key={i} r={r} index={i} />
            ))}
          </div>
        </>
      ) : (
        <pre className="testing-pre testing-pre-scroll">{prettyJson(output)}</pre>
      )}

      <button
        type="button"
        className="testing-raw-toggle"
        onClick={() => setShowRaw((v) => !v)}
      >
        {showRaw ? 'Hide raw output' : 'Show raw output'}
      </button>
      {showRaw && (
        <pre className="testing-pre testing-pre-scroll">{prettyJson(output)}</pre>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Expandable result row                                             */
/* ------------------------------------------------------------------ */

const ResultQuery: React.FC<{
  topic: string; heading: string; input?: Record<string, unknown>;
}> = ({ topic, heading, input }) => {
  const extra = Object.entries(input || {}).filter(([key]) => key !== 'query');
  return (
    <div className="testing-case-block">
      <span className="testing-case-label">Query</span>
      <div className="testing-query">{topic || '(no query)'}</div>
      {heading && <span>{heading}</span>}
      {!input?.heading && extra.length > 0 && (
        <pre className="testing-pre">{prettyJson(Object.fromEntries(extra))}</pre>
      )}
    </div>
  );
};

function TemplateSettings({ assignment }: { assignment?: Record<string, unknown> }) {
  if (!assignment?.template_name) return null;
  const voice = assignment.voice_profile as { name: string; instructions: string } | null;
  return <details className="testing-case-block">
    <summary>Template settings used for this section</summary>
    <p><strong>Template</strong> {str(assignment.template_name)}</p>
    {str(assignment.instructions) && <p><strong>Brief prompt</strong> {str(assignment.instructions)}</p>}
    {str(assignment.guidance) && <p><strong>Section prompt</strong> {str(assignment.guidance)}</p>}
    {typeof assignment.target_words === 'number' && <p><strong>Target words</strong> {assignment.target_words}</p>}
    {voice && <p><strong>Voice and tone</strong> {voice.name} · {voice.instructions}</p>}
  </details>;
}

export const BriefSectionTitle = ({ template, heading, number }: { template: string; heading: string; number?: string }) => (
  <td className="testing-brief-section-title" title={[`${template} ·`, number, heading].filter(Boolean).join(' ')}>
    <strong>{number && <span className="testing-heading-number">{number} </span>}{heading}</strong><small>{template}</small>
  </td>
);

export function RemainingSections({ sections }: { sections?: SectionLabel[] }) {
  return <>{sections?.map((section, index) => (
    <tr key={section.number || index}><td /><BriefSectionTitle {...section} />
      <td>{index === 0 ? 'Running' : 'Queued'}</td><td colSpan={5} /></tr>
  ))}</>;
}

const ResultToggle = ({expanded, label}: {expanded: boolean; label: string}) => (
  <td className="testing-result-caret">
    <button type="button" className="testing-row-toggle" aria-expanded={expanded}
      aria-label={`${expanded ? 'Collapse' : 'Expand'} ${label || 'result'}`}>
      <span className="testing-disclosure-arrow" aria-hidden="true" />
    </button>
  </td>
);

type SectionLabel = { template: string; heading: string; number?: string };
type ResultData = Pick<TestResult, 'factual_claim_mean_score' | 'factual_claim_pass_rate' | 'status' | 'actual_output' | 'brief_evidence' | 'score' | 'latency_ms' | 'error_message' | 'assertion_results'>;

function Expectations({ result, template }: { result: ResultData; template: boolean }) {
  const grades = result.assertion_results || [];
  return <div className="testing-case-block">
    <span className="testing-case-label">Expectations</span>
    {grades.map((grade, index) => <AssertionResultRow key={index} result={grade} testResult={result} />)}
    {!grades.length && <p className="text-muted" style={{ margin: 0 }}>
      {template ? 'This run saved no expectation grades. Run the experiment again to grade it with the current checks.' : 'No expectation results.'}
    </p>}
  </div>;
}

function resultLabels(input?: Record<string, unknown>, assignment?: Record<string, unknown>, savedSection?: SectionLabel) {
  const topic = str(assignment?.topic) || str(input?.query);
  const heading = savedSection?.heading || str(assignment?.heading) || str(input?.heading);
  const label = savedSection || (assignment?.template_name ? {
    template: str(assignment.template_name), heading, number: str(assignment.heading_number),
  } : null);
  return { topic, heading, label };
}

export const ResultRow: React.FC<{ result: ResultData; input?: Record<string, unknown>; savedSection?: SectionLabel; brief?: boolean }> = ({
  result,
  input,
  savedSection,
  brief = false,
}) => {
  const [expanded, setExpanded] = useState(false);
  const [showOutput, setShowOutput] = useState(false);
  const assignment = result.actual_output?.assignment as Record<string, unknown> | undefined;
  const { topic, heading, label } = resultLabels(input, assignment, savedSection);
  const warnings = resultWarnings(result.actual_output);
  return (
    <>
      <tr
        className="testing-clickable-row testing-result-row"
        onClick={() => setExpanded((v) => !v)}
      >
        <ResultToggle expanded={expanded} label={heading || topic} />
        {label ? <BriefSectionTitle {...label} /> : (
          <td className="testing-result-case" title={heading || topic}>{heading || topic || '—'}</td>
        )}
        <td>
          <span
            className={`testing-badge testing-badge-${result.status} testing-result-status`}
          >
            {result.status}
          </span>
        </td>
        <td>{formatScore(result.score)}</td>
        {brief && <ClaimCells stats={result} />}
        <td>{formatMs(result.latency_ms)}</td>
        <td className={result.error_message ? 'testing-result-error' : 'testing-result-warning'}>
          {result.error_message || warnings.join('; ')}
        </td>
      </tr>
      {expanded && (
        <tr className="testing-result-detail-row">
          <td colSpan={brief ? 8 : 6}>
            <div className="testing-result-detail">
              <ResultQuery topic={topic} heading={heading} input={input} />
              <GeneratedSection result={result} label={savedSection ? "Saved section" : "Generated section"} />
              <TemplateSettings assignment={assignment} />
              {warnings.length > 0 && (
                <div className="testing-case-block">
                  <span className="testing-case-label">Warnings</span>
                  <ul className="testing-result-warning-list">
                    {warnings.map((w, i) => (
                      <li key={i} className="testing-result-warning">{w}</li>
                    ))}
                  </ul>
                </div>
              )}
              <Expectations result={result} template={!!assignment?.template_name} />
              <div className="testing-case-block">
                <button
                  type="button"
                  className="testing-collapse-toggle"
                  onClick={() => setShowOutput((v) => !v)}
                  aria-expanded={showOutput}
                >
                  <span className="testing-collapse-caret" aria-hidden>
                    {showOutput ? '▾' : '▸'}
                  </span>
                  <span className="testing-case-label">{result.actual_output?.capability === 'brief' ? 'Sources and supporting details' : 'Output'}</span>
                </button>
                {showOutput && <ResultOutput output={result.actual_output} />}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
};
