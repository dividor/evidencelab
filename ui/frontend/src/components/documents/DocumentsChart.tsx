import React from 'react';
import { LANGUAGES } from '../../constants';
import { StatsData } from '../../types/documents';

type ChartView = 'type' | 'agency' | 'year' | 'language' | 'status' | 'format';

type BreakdownValue = number | Record<string, number>;

interface DocumentsChartProps {
  stats: StatsData;
  chartView: ChartView;
  onChartViewChange: (view: ChartView) => void;
  hoveredBar: string | null;
  tooltipPos: { x: number; y: number };
  onHoverChange: (value: string | null) => void;
  onTooltipMove: (pos: { x: number; y: number }) => void;
  onBarClick: (category: string) => void;
}

const CHART_VIEWS: Array<{ key: ChartView; label: string }> = [
  { key: 'year', label: 'Year' },
  { key: 'type', label: 'Type' },
  { key: 'agency', label: 'Organization' },
  { key: 'language', label: 'Language' },
  { key: 'format', label: 'Format' },
  { key: 'status', label: 'Status' },
];

const STATUS_COLORS: Record<string, string> = {
  indexed: '#0ea5e9',
  downloaded: '#64748b',
  parsed: '#8b5cf6',
  summarized: '#10b981',
  tagged: '#f59e0b',
  error: '#ef4444',
  download_error: '#FDE047',
  download_failed: '#FDE047',
  parse_failed: '#ef4444',
  summarize_failed: '#ef4444',
  index_failed: '#ef4444',
  stopped: '#ef4444',
  parsing: '#c8c8c8',
  summarizing: '#c8c8c8',
  tagging: '#c8c8c8',
  indexing: '#c8c8c8',
  other: '#9ca3af',
};

const generateAxisTicks = (max: number): number[] => {
  const ticks: number[] = [];
  const step = Math.ceil(max / 5);
  for (let i = 0; i <= 5; i += 1) {
    ticks.push(i * step);
  }
  return ticks;
};

const getChartData = (stats: StatsData, chartView: ChartView) => {
  switch (chartView) {
    case 'type':
      return { breakdown: stats.type_breakdown, title: 'Type' };
    case 'agency':
      return { breakdown: stats.agency_breakdown, title: 'Organization' };
    case 'year':
      return { breakdown: stats.year_breakdown, title: 'Year' };
    case 'language':
      return { breakdown: stats.language_breakdown || {}, title: 'Language' };
    case 'format':
      return { breakdown: stats.format_breakdown || {}, title: 'Format' };
    case 'status':
      return { breakdown: stats.status_breakdown, title: '' };
    default:
      return { breakdown: stats.type_breakdown, title: 'Type' };
  }
};

const getMaxCount = (breakdown: Record<string, BreakdownValue>): number => {
  const values = Object.values(breakdown).map((val) =>
    typeof val === 'number' ? val : Object.values(val || {}).reduce((a, b) => a + b, 0)
  );
  return values.length ? Math.max(...values) : 0;
};

const getStatusColor = (status: string, chartView: ChartView): string => {
  if (STATUS_COLORS[status]) return STATUS_COLORS[status];

  if (chartView === 'year') {
    if (status === 'index_failed') return STATUS_COLORS.error;
    if (status === 'parse_failed') return '#f97316';
    if (status === 'summarize_failed') return '#fb923c';
    if (status.includes('error') || status.includes('failed')) return '#f87171';
  }

  if (status.includes('error') || status.includes('failed')) return STATUS_COLORS.error;
  return STATUS_COLORS.other;
};

const getAllStatuses = (
  breakdown: Record<string, BreakdownValue>,
  chartView: ChartView
): string[] => {
  const allStatuses = new Set<string>();
  Object.values(breakdown).forEach((val) => {
    if (typeof val === 'object') {
      Object.keys(val).forEach((status) => allStatuses.add(status));
    }
  });
  if (chartView === 'status') {
    Object.keys(breakdown).forEach((status) => allStatuses.add(status));
  }
  return Array.from(allStatuses);
};

const sortStatuses = (statuses: string[]): string[] =>
  statuses.sort((a, b) => {
    if (a === 'indexed') return -1;
    if (b === 'indexed') return 1;
    if (a.includes('error') && !b.includes('error')) return 1;
    if (!a.includes('error') && b.includes('error')) return -1;
    return a.localeCompare(b);
  });

const getChartEntries = (
  breakdown: Record<string, BreakdownValue>,
  chartView: ChartView
): Array<[string, BreakdownValue]> => {
  const entries = Object.entries(breakdown);
  if (chartView === 'year') {
    return [...entries].sort((a, b) => b[0].localeCompare(a[0]));
  }
  return entries.slice(0, 10);
};

const normalizeEntry = (category: string, data: BreakdownValue): {
  total: number;
  statusBreakdown: Record<string, number>;
  displayLabel: string;
} => {
  if (typeof data === 'number') {
    return {
      total: data,
      statusBreakdown: { [category]: data },
      displayLabel: category,
    };
  }
  const total = Object.values(data).reduce((a, b) => a + b, 0);
  return {
    total,
    statusBreakdown: data,
    displayLabel: category,
  };
};

const getDisplayLabel = (chartView: ChartView, category: string): string => {
  if (chartView === 'language' && LANGUAGES[category]) return LANGUAGES[category];
  if (chartView === 'status') return formatStatusLabel(category);
  return category;
};

const ChartToggleButtons: React.FC<{
  chartView: ChartView;
  onChange: (view: ChartView) => void;
}> = ({ chartView, onChange }) => (
  <div className="chart-toggle-container">
    {CHART_VIEWS.map((view) => (
      <button
        key={view.key}
        className={`chart-toggle-button ${chartView === view.key ? 'active' : ''}`}
        onClick={() => onChange(view.key)}
      >
        {view.label}
      </button>
    ))}
  </div>
);

const formatStatusLabel = (status: string): string => {
  if (status === 'download_error' || status === 'download_failed') {
    return 'Document unavailable';
  }
  const label = status.replace(/_/g, ' ');
  return label.charAt(0).toUpperCase() + label.slice(1);
};

const ChartLegend: React.FC<{
  statuses: string[];
  chartView: ChartView;
}> = ({ statuses, chartView }) => (
  <div className="chart-legend">
    {statuses.map((status) => (
      <div key={status} className="legend-item">
        <span
          className="legend-color"
          style={{ backgroundColor: getStatusColor(status, chartView) }}
        ></span>
        <span className="legend-label">{formatStatusLabel(status)}</span>
      </div>
    ))}
  </div>
);

const ChartBarItem: React.FC<{
  category: string;
  data: BreakdownValue;
  chartView: ChartView;
  maxCount: number;
  statuses: string[];
  hoveredBar: string | null;
  tooltipPos: { x: number; y: number };
  onHoverChange: (value: string | null) => void;
  onTooltipMove: (pos: { x: number; y: number }) => void;
  onBarClick: (category: string) => void;
}> = ({
  category,
  data,
  chartView,
  maxCount,
  statuses,
  hoveredBar,
  tooltipPos,
  onHoverChange,
  onTooltipMove,
  onBarClick,
}) => {
    const { total, statusBreakdown } = normalizeEntry(category, data);
    const displayLabel = getDisplayLabel(chartView, category);
    const tooltipKey = `${chartView}-${category}`;
    const showTooltip = hoveredBar === tooltipKey;

    return (
      <div className="chart-bar-item">
        <div className="chart-bar-label">
          <span className="chart-bar-status">{displayLabel}</span>
        </div>
        <div
          className="chart-bar-track"
          onClick={() => onBarClick(category)}
          onMouseEnter={(event) => {
            onHoverChange(tooltipKey);
            onTooltipMove({ x: event.clientX, y: event.clientY });
          }}
          onMouseMove={(event) => {
            onTooltipMove({ x: event.clientX, y: event.clientY });
          }}
          onMouseLeave={() => onHoverChange(null)}
        >
          {statuses.map((status) => {
            const count = statusBreakdown[status] || 0;
            if (count === 0) return null;
            const percentage = maxCount ? (count / maxCount) * 100 : 0;
            return (
              <div
                key={`${category}-${status}`}
                className="chart-bar-fill"
                style={{
                  width: `${percentage}%`,
                  backgroundColor: getStatusColor(status, chartView),
                  display: 'inline-block',
                }}
              />
            );
          })}
        </div>
        {showTooltip && (
          <div
            className="chart-tooltip"
            style={{
              left: `${tooltipPos.x + 10}px`,
              top: `${tooltipPos.y + 10}px`,
            }}
          >
            <div>
              <strong>{category}</strong>
            </div>
            <div>Total: {total.toLocaleString()}</div>
            {chartView !== 'status' &&
              statuses.map((status) => {
                const count = statusBreakdown[status] || 0;
                if (count === 0) return null;
                return (
                  <div key={`${category}-${status}-row`}>
                    <span
                      style={{
                        color: getStatusColor(status, chartView),
                        marginRight: '4px',
                      }}
                    >
                      ●
                    </span>
                    {formatStatusLabel(status)}: {count.toLocaleString()}
                  </div>
                );
              })}
          </div>
        )}
      </div>
    );
  };

export const DocumentsChart: React.FC<DocumentsChartProps> = ({
  stats,
  chartView,
  onChartViewChange,
  hoveredBar,
  tooltipPos,
  onHoverChange,
  onTooltipMove,
  onBarClick,
}) => {
  const { breakdown, title } = getChartData(stats, chartView);
  const entries = getChartEntries(breakdown, chartView);
  const maxCount = getMaxCount(breakdown);
  const statuses = sortStatuses(getAllStatuses(breakdown, chartView));

  return (
    <>
      <ChartToggleButtons chartView={chartView} onChange={onChartViewChange} />
      {entries.length === 0 ? (
        <p>No data available for this view.</p>
      ) : (
        <>
          <div className="chart-header-row">
            {title && <h3 className="chart-subtitle">{title}</h3>}
            {chartView !== 'status' && (
              <ChartLegend statuses={statuses} chartView={chartView} />
            )}
          </div>
          <div className="chart-bars">
            {entries.map(([category, data]) => (
              <ChartBarItem
                key={category}
                category={category}
                data={data}
                chartView={chartView}
                maxCount={maxCount}
                statuses={statuses}
                hoveredBar={hoveredBar}
                tooltipPos={tooltipPos}
                onHoverChange={onHoverChange}
                onTooltipMove={onTooltipMove}
                onBarClick={onBarClick}
              />
            ))}
          </div>
          <div className="chart-x-axis">
            <div className="chart-x-axis-ticks">
              {generateAxisTicks(maxCount).map((tick, idx) => (
                <span key={idx}>{tick.toLocaleString()}</span>
              ))}
            </div>
          </div>
          <div className="chart-x-axis-label">Number of Documents</div>
        </>
      )}
    </>
  );
};
