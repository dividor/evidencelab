import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { FOOTPRINT_COLUMNS, FootprintRanges, formatFootprintRange } from '../../utils/footprintDisplay';

const PERIODS = [
  { value: '30-days', label: 'Last 30 days' },
  { value: 'year-to-date', label: 'Year to date' },
] as const;

type Period = (typeof PERIODS)[number]['value'];

interface ImpactSummary extends FootprintRanges {
  from_date: string;
  to_date: string;
  completion_tokens: number;
  footprint_unestimated_tokens: number;
}

const dateFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeZone: 'UTC' });

const ImpactResults: React.FC<{ period: Period }> = ({ period }) => {
  const [summary, setSummary] = useState<ImpactSummary>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    axios.get<ImpactSummary>(`${API_BASE_URL}/llm-usage/me/footprint`, {
      params: { period },
      signal: controller.signal,
    }).then(({ data }) => {
      if (!controller.signal.aborted) setSummary(data);
    }).catch(() => {
      if (!controller.signal.aborted) setFailed(true);
    });
    return () => controller.abort();
  }, [period]);

  if (failed) return <p role="alert">Couldn’t load your environmental impact.</p>;
  if (!summary) return <p role="status">Loading your environmental impact…</p>;

  return (
    <div aria-live="polite">
      <p className="text-muted personal-impact-dates">
        {dateFormatter.format(new Date(summary.from_date))} – {dateFormatter.format(new Date(summary.to_date))} (UTC)
      </p>
      {summary.completion_tokens === 0 ? (
        <p>No text generation was recorded for your account in this period.</p>
      ) : (
        <dl className="personal-impact-metrics">
          {FOOTPRINT_COLUMNS.map(({ measure, label }) => (
            <div key={measure}>
              <dt>{label}</dt>
              <dd>{formatFootprintRange(summary, measure) ?? 'No estimate'}</dd>
            </div>
          ))}
        </dl>
      )}
      {summary.footprint_unestimated_tokens > 0 && (
        <p className="text-muted">
          The estimates leave out {summary.footprint_unestimated_tokens.toLocaleString()} of{' '}
          {summary.completion_tokens.toLocaleString()} output tokens (pieces of text the model generated).
        </p>
      )}
    </div>
  );
};

const EnvironmentalImpactModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [period, setPeriod] = useState<Period>('30-days');
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="personal-impact-modal"
      aria-labelledby="personal-impact-title"
      onCancel={(event) => { event.preventDefault(); onClose(); }}
    >
      <div className="modal-header">
        <h2 id="personal-impact-title">Environmental impact</h2>
        <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>&times;</button>
      </div>
      <div className="modal-body">
        <div className="login-tabs" role="group" aria-label="Reporting period">
          {PERIODS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              className={period === value ? 'login-tab login-tab-active' : 'login-tab'}
              aria-pressed={period === value}
              onClick={() => setPeriod(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <ImpactResults key={period} period={period} />
        <p className="text-muted personal-impact-coverage">
          EcoLogits estimates the impact of AI text generation recorded for your account.
          The figures exclude document processing, embedding for search and reranking search results.
        </p>
      </div>
    </dialog>
  );
};

export default EnvironmentalImpactModal;
