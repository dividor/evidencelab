import React from 'react';
import { render } from '@testing-library/react';
import RunPassRateChart from '../components/admin/testing/RunPassRateChart';
import type { SummaryStats, TestRun } from '../types/testing';

// Capture the props Plotly is rendered with so we can assert on the plotted data
// without depending on Plotly's DOM output.
let lastPlotProps: { data?: Array<{ x?: number[]; y?: number[] }> } | null = null;
jest.mock('react-plotly.js', () => ({
  __esModule: true,
  default: (props: { data?: Array<{ x?: number[]; y?: number[] }> }) => {
    lastPlotProps = props;
    return <div data-testid="plot" />;
  },
}));

const stats = (pass_rate: number): SummaryStats => ({
  total: 10,
  passed: Math.round(pass_rate * 10),
  failed: 10 - Math.round(pass_rate * 10),
  errored: 0,
  pass_rate,
  mean_score: pass_rate,
  duration_ms: 1000,
});

const makeRun = (
  run_number: number,
  summary_stats: SummaryStats | null,
  status: TestRun['status'] = 'completed',
): TestRun => ({
  id: `run-${run_number}`,
  experiment_id: 'exp-1',
  run_number,
  status,
  summary_stats,
  started_at: '2026-01-01T00:00:00Z',
  finished_at: '2026-01-01T00:01:00Z',
  created_at: '2026-01-01T00:00:00Z',
  results: [],
});

beforeEach(() => {
  lastPlotProps = null;
});

describe('RunPassRateChart', () => {
  it('test_chart_when_single_completed_run_then_plots_one_point', () => {
    const { getByTestId } = render(<RunPassRateChart runs={[makeRun(1, stats(0.5))]} />);
    expect(getByTestId('plot')).toBeInTheDocument();
    const trace = lastPlotProps?.data?.[0];
    expect(trace?.x).toEqual([1]);
    expect(trace?.y).toEqual([0.5]);
  });

  it('test_chart_when_multiple_runs_then_plots_ascending_by_run_number', () => {
    // API returns runs newest-first; the chart must sort them ascending.
    const runs = [makeRun(3, stats(0.75)), makeRun(2, stats(0.5)), makeRun(1, stats(0.2))];
    const { getByTestId } = render(<RunPassRateChart runs={runs} />);

    expect(getByTestId('plot')).toBeInTheDocument();
    const trace = lastPlotProps?.data?.[0];
    expect(trace?.x).toEqual([1, 2, 3]);
    expect(trace?.y).toEqual([0.2, 0.5, 0.75]);
  });

  it('test_chart_when_run_lacks_pass_rate_then_excluded_from_trend', () => {
    // A still-running run reports progress but no pass_rate; it must be dropped
    // so the x-axis reflects only the runs that actually completed.
    const runs = [
      makeRun(3, null, 'running'),
      makeRun(2, stats(0.6)),
      makeRun(1, stats(0.4)),
    ];
    render(<RunPassRateChart runs={runs} />);

    const trace = lastPlotProps?.data?.[0];
    expect(trace?.x).toEqual([1, 2]);
    expect(trace?.y).toEqual([0.4, 0.6]);
  });

  it('test_chart_when_no_run_has_pass_rate_then_renders_nothing', () => {
    // Every run failed / is still running, so none has a pass_rate to plot.
    const runs = [makeRun(2, null, 'failed'), makeRun(1, null, 'running')];
    const { container, queryByTestId } = render(<RunPassRateChart runs={runs} />);
    expect(container).toBeEmptyDOMElement();
    expect(queryByTestId('plot')).toBeNull();
  });
});
