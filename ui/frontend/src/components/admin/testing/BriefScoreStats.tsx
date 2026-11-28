import React from 'react';
import type { CheckSummaryStats, RunProgress } from '../../../types/testing';
import { formatElapsed, formatPercent, formatScore, formatCostUsd, formatTokens, formatTimestamp } from './testingFormat';

export const CLAIM_MEAN = 'Factual Claim Mean Score';
export const CLAIM_RATE = 'Factual Claim Pass Rate';
const meanHelp = 'Average score across graded factual claims. Each claim counts once.';
const rateHelp = 'Percentage of graded factual claims that passed their grading threshold.';

export function ClaimHeaders() {
  return <><th title={meanHelp}>{CLAIM_MEAN}</th><th title={rateHelp}>{CLAIM_RATE}</th></>;
}

type Scores = Pick<CheckSummaryStats, 'factual_claim_mean_score' | 'factual_claim_pass_rate'>;
export function ClaimCells({ stats }: { stats?: Scores | null }) {
  return <><td>{formatScore(stats?.factual_claim_mean_score)}</td><td>{formatPercent(stats?.factual_claim_pass_rate)}</td></>;
}

type RunStatsProps = {
  stats?: CheckSummaryStats | null; brief: boolean; total?: number; passed?: number; failed?: number;
  errored?: number; started?: string | null; finished?: string | null;
};

export function RunStats({ stats, brief, total, passed, failed, errored, started, finished }: RunStatsProps) {
  const tiles = [
    ['Pass rate', formatPercent(stats?.pass_rate), 'Percentage of all sections or cases that passed.'],
    ['Mean Total Score', formatScore(stats?.mean_score), 'Average of the scored section or case totals.'],
    ...(brief ? [[CLAIM_MEAN, formatScore(stats?.factual_claim_mean_score), meanHelp],
      [CLAIM_RATE, formatPercent(stats?.factual_claim_pass_rate), rateHelp]] : []),
    [brief ? 'Total sections' : 'Total cases', String(total ?? '-')],
    ['Passed', String(passed ?? '-')], ['Failed', String(failed ?? '-')], ['Errored', String(errored ?? '-')],
    ['Tokens', formatTokens(stats?.total_tokens)], ['Cost', formatCostUsd(stats?.cost_usd)],
    ['Started', formatTimestamp(started)], ['Finished', formatTimestamp(finished)],
    ['Duration', formatElapsed(stats?.duration_ms), 'Elapsed time for the run.'],
  ];
  return <div className="testing-summary-header">{tiles.map(([label, value, help]) => <div className="testing-summary-stat" key={label} title={help}>
    <span className="testing-summary-label">{label}</span><span>{value}</span>
  </div>)}</div>;
}

/* Live progress for an in-flight run: "k of N cases (z%)" plus a bar. The
   backend publishes `progress` on summary_stats while running and replaces it
   with the real stats on completion. */
export const RunProgressBar: React.FC<{ progress?: RunProgress | null; unit: string }> = ({ progress, unit }) => {
  if (!progress) {
    return (
      <div className="testing-run-progress" role="status">
        <span className="testing-run-progress-label">Starting…</span>
      </div>
    );
  }
  const { completed, total } = progress;
  const fraction = total > 0 ? completed / total : 0;
  return (
    <div className="testing-run-progress" role="status">
      <div className="testing-run-progress-label">
        <span>
          {completed} of {total} {unit}{total === 1 ? '' : 's'} processed
        </span>
        <span className="testing-run-progress-pct">{formatPercent(fraction)}</span>
      </div>
      <div
        className="testing-run-progress-track"
        role="progressbar"
        aria-valuenow={completed}
        aria-valuemin={0}
        aria-valuemax={total}
      >
        <div
          className="testing-run-progress-fill"
          style={{ width: `${Math.round(fraction * 100)}%` }}
        />
      </div>
    </div>
  );
};
