import React from 'react';
import Plot from 'react-plotly.js';
import type { TestRun } from '../../../types/testing';

interface RunPassRateChartProps {
  runs: TestRun[];
}

/* Brand primary — matches --brand-primary in App.css. */
const LINE_COLOR = '#5B8FA8';

/* Show the chart once any run has a pass rate; a single run renders one marker. */
const MIN_POINTS = 1;

/* Only completed runs carry a numeric pass_rate; pending/running runs report
   progress instead, so they are excluded from the trend. */
const hasPassRate = (run: TestRun): boolean =>
  typeof run.summary_stats?.pass_rate === 'number';

const byRunNumber = (a: TestRun, b: TestRun): number => a.run_number - b.run_number;

/**
 * Line chart of pass rate across an experiment's runs.
 *
 * The x-axis is the actual run number and the y-axis is the pass rate
 * (0–100%), so the chart reflects exactly which runs executed and updates as
 * new runs are added. A single run renders as one marker; the chart is hidden
 * only when no run has a recorded pass rate (e.g. every run failed).
 *
 * Args:
 *   runs: The experiment's runs, in any order (the API returns them newest
 *     first; this component sorts ascending by run number for plotting).
 *
 * Returns:
 *   A styled Plotly line chart, or ``null`` when no completed run has a pass
 *   rate to plot.
 */
const RunPassRateChart: React.FC<RunPassRateChartProps> = ({ runs }) => {
  const points = runs.filter(hasPassRate).sort(byRunNumber);

  if (points.length < MIN_POINTS) return null;

  const x = points.map((run) => run.run_number);
  const y = points.map((run) => run.summary_stats?.pass_rate ?? 0);

  return (
    <div className="testing-runs-chart">
      <span className="testing-runs-chart-title">Pass rate by run</span>
      <Plot
        data={[
          {
            type: 'scatter',
            mode: 'lines+markers',
            x,
            y,
            line: { color: LINE_COLOR, width: 2 },
            marker: { color: LINE_COLOR, size: 7 },
            hovertemplate: 'Run #%{x}: %{y:.0%} pass<extra></extra>',
          },
        ]}
        layout={{
          height: 240,
          margin: { t: 12, b: 44, l: 56, r: 20 },
          paper_bgcolor: 'white',
          plot_bgcolor: 'white',
          font: { size: 12, color: '#334155' },
          xaxis: {
            title: 'Run number',
            dtick: 1,
            tickformat: 'd',
            fixedrange: true,
            zeroline: false,
          },
          yaxis: {
            title: 'Pass rate',
            tickformat: ',.0%',
            range: [0, 1.05],
            fixedrange: true,
            zeroline: false,
          },
          showlegend: false,
        }}
        style={{ width: '100%', height: '240px' }}
        config={{ responsive: true, displayModeBar: false }}
      />
    </div>
  );
};

export default RunPassRateChart;
