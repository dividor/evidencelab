import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { FootprintMeasure, FootprintRanges, formatFootprintRange } from '../../utils/footprintDisplay';
import EcoLogitsLink from '../EcoLogitsLink';

const PERIODS = [
  { value: '30-days', label: 'Last 30 days' },
  { value: 'year-to-date', label: 'Year to date' },
] as const;

type Period = (typeof PERIODS)[number]['value'];

const METRICS: ReadonlyArray<{ measure: FootprintMeasure; label: string; unit: string }> = [
  { measure: 'energy_kwh', label: 'Electricity', unit: 'watt-hours' },
  { measure: 'gwp_kgco2eq', label: 'Greenhouse gas emissions', unit: 'grams of CO₂ equivalent' },
  { measure: 'water_l', label: 'Water use', unit: 'millilitres' },
];

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
        <p>We didn’t record any AI-written text for your account in this period.</p>
      ) : (
        <dl className="personal-impact-metrics">
          {METRICS.map(({ measure, label, unit }) => {
            const range = formatFootprintRange(summary, measure);
            return (
              <div key={measure}>
                <dt>{label}</dt>
                <dd>
                  <span>{range ?? 'No estimate'}</span>
                  {range !== null && <small>{unit}</small>}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
      {summary.footprint_unestimated_tokens > 0 && (
        <p className="text-muted">
          We recorded {summary.completion_tokens.toLocaleString()} tokens of AI-written text for your account.
          We couldn’t estimate the impact of {summary.footprint_unestimated_tokens.toLocaleString()} of them.
          A token is a small piece of text, like a word or part of a word.
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
          We use <EcoLogitsLink /> to estimate the impact of text AI writes for you.
          Some models and older activity don’t have estimates.
          The figures leave out automatic document processing and the work of finding and sorting search results.
        </p>
      </div>
    </dialog>
  );
};

export default EnvironmentalImpactModal;
