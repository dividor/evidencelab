import React, { useState, useEffect } from 'react';
import { usePipelineData } from '../hooks/usePipelineData';
// @ts-ignore
import Plot from 'react-plotly.js';

interface StatsData {
  total_documents: number;
  indexed_documents: number;
  total_agencies: number;
  status_breakdown: Record<string, number>;
}

interface SankeyData {
  nodes: string[];
  node_colors: string[];
  links: {
    source: number[];
    target: number[];
    value: number[];
    color: string[];
  };
  annotations: {
    num_orgs: number;
    total_records: number;
    layer2_count: number;
    layer3_count: number;
    layer4_count: number;
  };
}



interface HistogramData {
  x: string[];
  y: number[];
}

interface PhaseDistributionData {
  x: string[];
  Parsing: number[];
  Summarizing: number[];
  Tagging: number[];
  Indexing: number[];
}

interface TimelineData {
  histogram: HistogramData;
  phase_distribution: PhaseDistributionData;
  pages_histogram: HistogramData;
  errors_histogram: {
    x: string[];
    "Parse Failed": number[];
    "Summarization Failed": number[];
    "Indexing Failed": number[];
  };
}

const formatSankeyNodeLabel = (label: string): string => {
  const match = label.match(/\((\d+)\)\s*$/);
  if (!match) {
    return label;
  }
  const formattedCount = Number(match[1]).toLocaleString();
  return label.replace(/\(\d+\)\s*$/, `(${formattedCount})`);
};

const buildCutoff = (timeRange: '24h' | '48h' | 'all'): Date | null => {
  if (timeRange === 'all') {
    return null;
  }
  const hours = timeRange === '24h' ? 24 : 48;
  const cutoff = new Date();
  cutoff.setHours(cutoff.getHours() - hours);
  return cutoff;
};

const filterByCutoff = (
  x: string[],
  y: number[],
  cutoff: Date
): HistogramData => {
  const filteredX: string[] = [];
  const filteredY: number[] = [];
  for (let i = 0; i < x.length; i++) {
    if (new Date(x[i]) >= cutoff) {
      filteredX.push(x[i]);
      filteredY.push(y[i]);
    }
  }
  return { x: filteredX, y: filteredY };
};

const filterErrorsHistogram = (
  errors: TimelineData["errors_histogram"],
  cutoff: Date
): TimelineData["errors_histogram"] => {
  const filteredErrX: string[] = [];
  const filteredParseFailed: number[] = [];
  const filteredSummFailed: number[] = [];
  const filteredIndexFailed: number[] = [];

  for (let i = 0; i < errors.x.length; i++) {
    if (new Date(errors.x[i]) >= cutoff) {
      filteredErrX.push(errors.x[i]);
      filteredParseFailed.push(errors["Parse Failed"]?.[i] || 0);
      filteredSummFailed.push(errors["Summarization Failed"]?.[i] || 0);
      filteredIndexFailed.push(errors["Indexing Failed"]?.[i] || 0);
    }
  }

  return {
    x: filteredErrX,
    "Parse Failed": filteredParseFailed,
    "Summarization Failed": filteredSummFailed,
    "Indexing Failed": filteredIndexFailed,
  };
};

const filterPhaseDistribution = (
  distribution: PhaseDistributionData,
  cutoff: Date
): PhaseDistributionData => {
  const filteredDistX: string[] = [];
  const filteredParsing: number[] = [];
  const filteredSummarizing: number[] = [];
  const filteredTagging: number[] = [];
  const filteredIndexing: number[] = [];

  for (let i = 0; i < distribution.x.length; i++) {
    if (new Date(distribution.x[i]) >= cutoff) {
      filteredDistX.push(distribution.x[i]);
      filteredParsing.push(distribution.Parsing[i]);
      filteredSummarizing.push(distribution.Summarizing[i]);
      filteredTagging.push(distribution.Tagging[i]);
      filteredIndexing.push(distribution.Indexing[i]);
    }
  }

  return {
    x: filteredDistX,
    Parsing: filteredParsing,
    Summarizing: filteredSummarizing,
    Tagging: filteredTagging,
    Indexing: filteredIndexing,
  };
};

const filterTimelineData = (
  timelineData: TimelineData | null,
  timeRange: '24h' | '48h' | 'all'
) => {
  if (!timelineData) return null;

  const cutoff = buildCutoff(timeRange);
  if (!cutoff) {
    return timelineData;
  }

  return {
    histogram: filterByCutoff(timelineData.histogram.x, timelineData.histogram.y, cutoff),
    pages_histogram: filterByCutoff(
      timelineData.pages_histogram.x,
      timelineData.pages_histogram.y,
      cutoff
    ),
    phase_distribution: filterPhaseDistribution(timelineData.phase_distribution, cutoff),
    errors_histogram: filterErrorsHistogram(
      timelineData.errors_histogram ?? {
        x: [],
        "Parse Failed": [],
        "Summarization Failed": [],
        "Indexing Failed": [],
      },
      cutoff
    ),
  };
};

const PipelineLoading = () => (
  <div className="statistics-container">
    <div className="statistics-loading">
      <div className="stats-loading-animation">
        <div className="dot-wave">
          {[1, 2, 3, 4].map((dot) => (
            <div key={dot} className={`dot dot-${dot}`}></div>
          ))}
        </div>
      </div>
      <span className="generating-text">
        {'Loading pipeline data ...'.split('').map((char, index) => (
          <span
            key={index}
            className="wave-char"
            style={{ animationDelay: `${index * 0.05}s` }}
          >
            {char === ' ' ? '\u00A0' : char}
          </span>
        ))}
      </span>
    </div>
  </div>
);

const PipelineError = ({ error }: { error: string }) => (
  <div className="statistics-container">
    <div className="statistics-error">{error}</div>
  </div>
);

const PipelineEmpty = () => (
  <div className="statistics-container">
    <div className="statistics-error">No data available</div>
  </div>
);

const PipelineStatsGrid = ({
  animatedTotalDocs,
  animatedIndexedDocs,
  animatedAgencies,
  animatedSuccessRate
}: {
  animatedTotalDocs: number;
  animatedIndexedDocs: number;
  animatedAgencies: number;
  animatedSuccessRate: number;
}) => (
  <div className="stats-grid">
    <div className="stat-card stat-card-primary">
      <div className="stat-value">{animatedTotalDocs.toLocaleString()}</div>
      <div className="stat-label">Total Reports</div>
    </div>

    <div className="stat-card stat-card-success">
      <div className="stat-value">{animatedIndexedDocs.toLocaleString()}</div>
      <div className="stat-label">Indexed Reports</div>
    </div>

    <div className="stat-card stat-card-info">
      <div className="stat-value">{animatedAgencies}</div>
      <div className="stat-label">Agencies</div>
    </div>

    <div className="stat-card stat-card-accent">
      <div className="stat-value">{animatedSuccessRate.toFixed(1)}%</div>
      <div className="stat-label">Success Rate</div>
    </div>
  </div>
);

const PipelineSankeySection = ({ sankeyData }: { sankeyData: SankeyData }) => {
  const formattedNodes = sankeyData.nodes.map(formatSankeyNodeLabel);

  return (
    <div className="chart-section">
      <div className="sankey-container">
        <Plot
          data={[
            {
              type: 'sankey',
              orientation: 'h',
              node: {
                pad: 10,
                thickness: 20,
                line: {
                  color: 'white',
                  width: 0
                },
                label: formattedNodes,
                color: sankeyData.node_colors,
                hovertemplate: '<b>%{label}</b><br>Reports: %{value:,}<extra></extra>',
              },
              link: {
                source: sankeyData.links.source,
                target: sankeyData.links.target,
                value: sankeyData.links.value,
                color: sankeyData.links.color,
                line: {
                  color: 'rgba(0,0,0,0)',
                  width: 0
                },
                hovertemplate: '<b>%{source.label}</b> → <b>%{target.label}</b><br>' +
                  'Reports: %{value:,}<br>' +
                  '<extra></extra>',
              },
              textfont: {
                size: 13,
                family: 'Poppins, sans-serif'
              },
              arrangement: 'snap',
              valueformat: ',',
            }
          ]}
          layout={{
            title: {},
            font: {
              size: 12,
              family: 'Open Sans, sans-serif'
            },
            height: 600,
            paper_bgcolor: 'white',
            plot_bgcolor: 'white',
            margin: { t: 60, b: 50, l: 20, r: 20 },
            hoverlabel: {
              bgcolor: '#2C3E50',
              font: {
                family: 'Open Sans, sans-serif',
                size: 13,
                color: 'white'
              },
              bordercolor: '#2C3E50',
              align: 'left',
              namelength: -1
            },
            transition: {
              duration: 500,
              easing: 'cubic-in-out'
            },
            annotations: [
              {
                x: 0.02,
                y: -0.08,
                xref: 'paper',
                yref: 'paper',
                text: `UN Organization (orgs=${sankeyData.annotations.num_orgs.toLocaleString()}, reports=${sankeyData.annotations.total_records.toLocaleString()})`,
                showarrow: false,
                font: { size: 11, color: '#2C3E50', family: 'Open Sans, sans-serif' },
                xanchor: 'left'
              },
              {
                x: 0.35,
                y: -0.08,
                xref: 'paper',
                yref: 'paper',
                text: `reports=${sankeyData.annotations.layer2_count.toLocaleString()}`,
                showarrow: false,
                font: { size: 11, color: '#2C3E50', family: 'Open Sans, sans-serif' },
                xanchor: 'center',
                bgcolor: 'rgba(255,255,255,0.8)',
                borderpad: 8,
                bordercolor: 'rgba(200,200,200,0.5)',
                borderwidth: 1
              },
              {
                x: 0.65,
                y: -0.08,
                xref: 'paper',
                yref: 'paper',
                text: `reports=${sankeyData.annotations.layer3_count.toLocaleString()}`,
                showarrow: false,
                font: { size: 11, color: '#2C3E50', family: 'Open Sans, sans-serif' },
                xanchor: 'center',
                bgcolor: 'rgba(255,255,255,0.8)',
                borderpad: 8,
                bordercolor: 'rgba(200,200,200,0.5)',
                borderwidth: 1
              },
              {
                x: 0.98,
                y: -0.08,
                xref: 'paper',
                yref: 'paper',
                text: `reports=${sankeyData.annotations.layer4_count.toLocaleString()}`,
                showarrow: false,
                font: { size: 11, color: '#2C3E50', family: 'Open Sans, sans-serif' },
                xanchor: 'right',
                bgcolor: 'rgba(255,255,255,0.8)',
                borderpad: 8,
                bordercolor: 'rgba(200,200,200,0.5)',
                borderwidth: 1
              }
            ]
          }}
          config={{
            displayModeBar: true,
            displaylogo: false,
            modeBarButtonsToRemove: ['lasso2d', 'select2d'],
            toImageButtonOptions: {
              format: 'png',
              filename: 'pipeline_flow',
              height: 800,
              width: 1200,
              scale: 2
            },
            animated: true
          }}
          style={{ width: '100%', height: '600px' }}
          useResizeHandler={true}
          frames={[]}
        />
      </div>
    </div>
  );
};


const timelineButtonStyle = (isActive: boolean) => ({
  padding: '6px 16px',
  backgroundColor: isActive ? '#2C3E50' : 'transparent',
  color: isActive ? 'white' : '#666',
  border: 'none',
  borderRadius: '6px',
  cursor: 'pointer',
  fontWeight: 500,
});

const buildTimeRangeWindow = (
  timeRange: '24h' | '48h' | 'all'
): [string, string] | undefined => {
  if (timeRange === 'all') {
    return undefined;
  }
  const hours = timeRange === '24h' ? 24 : 48;
  return [
    new Date(Date.now() - hours * 3600000).toISOString(),
    new Date().toISOString(),
  ];
};

const PipelineTimelineControls = ({
  timeRange,
  onChange,
}: {
  timeRange: '24h' | '48h' | 'all';
  onChange: (range: '24h' | '48h' | 'all') => void;
}) => (
  <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '10px' }}>
    <div
      style={{
        display: 'flex',
        gap: '5px',
        backgroundColor: '#f0f0f0',
        padding: '5px',
        borderRadius: '8px',
      }}
    >
      <button onClick={() => onChange('24h')} style={timelineButtonStyle(timeRange === '24h')}>
        Last 24 hours
      </button>
      <button onClick={() => onChange('48h')} style={timelineButtonStyle(timeRange === '48h')}>
        Last 48 hours
      </button>
      <button onClick={() => onChange('all')} style={timelineButtonStyle(timeRange === 'all')}>
        All Time
      </button>
    </div>
  </div>
);

const PipelineThroughputChart = ({
  histogram,
  pagesHistogram,
  timeRangeWindow,
}: {
  histogram: HistogramData;
  pagesHistogram: HistogramData;
  timeRangeWindow: [string, string] | undefined;
}) => (
  <div style={{ width: '100%', height: '500px', marginBottom: '20px' }}>
    <Plot
      data={[
        {
          type: 'bar',
          x: histogram.x,
          y: histogram.y,
          xaxis: 'x',
          yaxis: 'y2',
          name: 'Indexed Docs',
          marker: { color: 'rgba(50, 171, 96, 0.6)' },
          hoverinfo: 'y+x',
        },
        {
          type: 'bar',
          x: pagesHistogram.x,
          y: pagesHistogram.y,
          xaxis: 'x',
          yaxis: 'y1',
          name: 'Pages Indexed',
          marker: { color: 'rgba(255, 165, 0, 0.6)' },
          hoverinfo: 'y+x',
        },
      ]}
      layout={{
        grid: { rows: 2, columns: 1, pattern: 'independent', roworder: 'top to bottom' },
        xaxis: {
          title: '',
          type: 'date',
          range: timeRangeWindow,
          anchor: 'y1',
        },
        yaxis2: { title: 'Docs', domain: [0.55, 1], anchor: 'x' },
        yaxis1: { title: 'Pages', domain: [0, 0.45], anchor: 'x' },
        height: 500,
        margin: { t: 30, b: 40, l: 80, r: 20 },
        paper_bgcolor: 'white',
        plot_bgcolor: 'white',
        showlegend: true,
        legend: { orientation: 'h', y: 1.1, x: 0.5, xanchor: 'center' },
      }}
      style={{ width: '100%', height: '100%' }}
      config={{ responsive: true, displayModeBar: false }}
    />
  </div>
);

const PipelinePhaseDistributionChart = ({
  phaseDistribution,
  timeRangeWindow,
}: {
  phaseDistribution: PhaseDistributionData;
  timeRangeWindow: [string, string] | undefined;
}) => (
  <div style={{ width: '100%', height: '350px', marginBottom: '20px' }}>
    <Plot
      data={[
        {
          type: 'bar',
          x: phaseDistribution.x,
          y: phaseDistribution.Parsing,
          name: 'Parsing %',
          marker: { color: '#636EFA' },
          stackgroup: 'one',
          groupnorm: 'percent',
        },
        {
          type: 'bar',
          x: phaseDistribution.x,
          y: phaseDistribution.Summarizing,
          name: 'Summarizing %',
          marker: { color: '#EF553B' },
          stackgroup: 'one',
        },
        {
          type: 'bar',
          x: phaseDistribution.x,
          y: phaseDistribution.Tagging,
          name: 'Tagging %',
          marker: { color: '#00CC96' },
          stackgroup: 'one',
        },
        {
          type: 'bar',
          x: phaseDistribution.x,
          y: phaseDistribution.Indexing,
          name: 'Indexing %',
          marker: { color: '#AB63FA' },
          stackgroup: 'one',
        },
      ]}
      layout={{
        xaxis: {
          title: '',
          type: 'date',
          range: timeRangeWindow,
        },
        yaxis: { title: 'Phase %', tickformat: ',.0%', automargin: true },
        height: 350,
        margin: { t: 20, b: 30, l: 80, r: 20 },
        paper_bgcolor: 'white',
        plot_bgcolor: 'white',
        showlegend: true,
        legend: { orientation: 'h', y: -0.2, x: 0.5, xanchor: 'center' },
      }}
      style={{ width: '100%', height: '100%' }}
      config={{ responsive: true, displayModeBar: false }}
    />
  </div>
);

const PipelineErrorChart = ({
  errorsHistogram,
  timeRangeWindow,
}: {
  errorsHistogram: TimelineData["errors_histogram"];
  timeRangeWindow: [string, string] | undefined;
}) => (
  <div style={{ width: '100%', height: '350px' }}>
    <Plot
      data={[
        {
          type: 'bar',
          x: errorsHistogram.x,
          y: errorsHistogram["Parse Failed"],
          name: 'Parse Failed',
          marker: { color: '#FF851B' },
          stackgroup: 'errors',
        },
        {
          type: 'bar',
          x: errorsHistogram.x,
          y: errorsHistogram["Summarization Failed"],
          name: 'Summ. Failed',
          marker: { color: '#FFDC00' },
          stackgroup: 'errors',
        },
        {
          type: 'bar',
          x: errorsHistogram.x,
          y: errorsHistogram["Indexing Failed"],
          name: 'Indexing Failed',
          marker: { color: '#85144b' },
          stackgroup: 'errors',
        },
      ]}
      layout={{
        xaxis: {
          title: 'Time',
          type: 'date',
          range: timeRangeWindow,
        },
        yaxis: { title: 'Errors', automargin: true },
        height: 350,
        margin: { t: 20, b: 50, l: 80, r: 20 },
        paper_bgcolor: 'white',
        plot_bgcolor: 'white',
        showlegend: true,
        legend: { orientation: 'h', y: -0.3, x: 0.5, xanchor: 'center' },
      }}
      style={{ width: '100%', height: '100%' }}
      config={{ responsive: true, displayModeBar: false }}
    />
  </div>
);

const PipelineTimelineSection = ({
  filteredData,
  timeRange,
  setTimeRange,
}: {
  filteredData: TimelineData | null;
  timeRange: '24h' | '48h' | 'all';
  setTimeRange: React.Dispatch<React.SetStateAction<'24h' | '48h' | 'all'>>;
}) => {
  if (!filteredData) {
    return <PipelineEmpty />;
  }

  const histogram = filteredData.histogram ?? { x: [], y: [] };
  const pagesHistogram = filteredData.pages_histogram ?? { x: [], y: [] };
  const phaseDistribution = filteredData.phase_distribution ?? {
    x: [],
    Parsing: [],
    Summarizing: [],
    Tagging: [],
    Indexing: [],
  };
  const errorsHistogram = filteredData.errors_histogram ?? {
    x: [],
    "Parse Failed": [],
    "Summarization Failed": [],
    "Indexing Failed": [],
  };

  const hasTimelineData =
    histogram.x.length > 0
    || phaseDistribution.x.length > 0
    || errorsHistogram.x.length > 0;
  if (!hasTimelineData) {
    return <PipelineEmpty />;
  }

  const timeRangeWindow = buildTimeRangeWindow(timeRange);

  return (
    <div className="chart-section" style={{ marginTop: '20px' }}>
      <h3
        className="chart-main-title"
        style={{ margin: '0 0 16px 0', fontSize: '1.1rem', fontWeight: 600, color: '#334155' }}
      >
        How fast, and what went wrong
      </h3>
      <div className="sankey-container">
        <PipelineTimelineControls timeRange={timeRange} onChange={setTimeRange} />
        <PipelineThroughputChart
          histogram={histogram}
          pagesHistogram={pagesHistogram}
          timeRangeWindow={timeRangeWindow}
        />
        <PipelinePhaseDistributionChart
          phaseDistribution={phaseDistribution}
          timeRangeWindow={timeRangeWindow}
        />
        <PipelineErrorChart errorsHistogram={errorsHistogram} timeRangeWindow={timeRangeWindow} />
      </div>
    </div>
  );
};

interface PipelineProps {
  dataSource?: string;
}

export const Pipeline: React.FC<PipelineProps> = ({ dataSource = 'uneg' }) => {
  const { stats, sankeyData, timelineData, loading, error } =
    usePipelineData(dataSource);

  // Animated counter states
  const [animatedTotalDocs, setAnimatedTotalDocs] = useState(0);
  const [animatedIndexedDocs, setAnimatedIndexedDocs] = useState(0);
  const [animatedAgencies, setAnimatedAgencies] = useState(0);
  const [animatedSuccessRate, setAnimatedSuccessRate] = useState(0);

  // Animate counters when stats change
  useEffect(() => {
    if (!stats) return;

    const duration = 1500; // 1.5 seconds
    const steps = 60;
    const interval = duration / steps;

    const totalDocsTarget = stats.total_documents;
    const indexedDocsTarget = stats.indexed_documents;
    const agenciesTarget = stats.total_agencies;
    const successRateTarget = stats.total_documents > 0
      ? (stats.indexed_documents / stats.total_documents) * 100
      : 0;

    let currentStep = 0;

    const timer = setInterval(() => {
      currentStep++;
      const progress = currentStep / steps;
      const easeOutQuad = 1 - Math.pow(1 - progress, 3); // Ease out cubic

      setAnimatedTotalDocs(Math.round(totalDocsTarget * easeOutQuad));
      setAnimatedIndexedDocs(Math.round(indexedDocsTarget * easeOutQuad));
      setAnimatedAgencies(Math.round(agenciesTarget * easeOutQuad));
      setAnimatedSuccessRate(successRateTarget * easeOutQuad);

      if (currentStep >= steps) {
        clearInterval(timer);
        setAnimatedTotalDocs(totalDocsTarget);
        setAnimatedIndexedDocs(indexedDocsTarget);
        setAnimatedAgencies(agenciesTarget);
        setAnimatedSuccessRate(successRateTarget);
      }
    }, interval);

    return () => clearInterval(timer);
  }, [stats]);

  if (loading) {
    return <PipelineLoading />;
  }

  if (error) {
    return <PipelineError error={error} />;
  }

  if (!stats || !sankeyData) {
    return <PipelineEmpty />;
  }

  const formattedNodes = sankeyData.nodes.map(formatSankeyNodeLabel);

  return (
    <div className="statistics-container">
      <div className="statistics-content">
        <h2 className="statistics-title">Document pipeline status</h2>

        {/* Key Metrics */}
        <div className="stats-grid">
          <div className="stat-card stat-card-primary">
            <div className="stat-value">{animatedTotalDocs.toLocaleString()}</div>
            <div className="stat-label">Total Reports</div>
          </div>

          <div className="stat-card stat-card-success">
            <div className="stat-value">{animatedIndexedDocs.toLocaleString()}</div>
            <div className="stat-label">Indexed Reports</div>
          </div>

          <div className="stat-card stat-card-info">
            <div className="stat-value">{animatedAgencies}</div>
            <div className="stat-label">Agencies</div>
          </div>

          <div className="stat-card stat-card-accent">
            <div className="stat-value">{animatedSuccessRate.toFixed(1)}%</div>
            <div className="stat-label">Success Rate</div>
          </div>
        </div>

        {/* Pipeline Flow Sankey Diagram */}
        <div className="chart-section">
          <div className="sankey-container">
            <Plot
              data={[
                {
                  type: 'sankey',
                  orientation: 'h',
                  node: {
                    pad: 10,
                    thickness: 20,
                    line: {
                      color: 'white',
                      width: 0
                    },
                    label: formattedNodes,
                    color: sankeyData.node_colors,
                    hovertemplate: '<b>%{label}</b><br>Reports: %{value:,}<extra></extra>',
                  },
                  link: {
                    source: sankeyData.links.source,
                    target: sankeyData.links.target,
                    value: sankeyData.links.value,
                    color: sankeyData.links.color,
                    line: {
                      color: 'rgba(0,0,0,0)',
                      width: 0
                    },
                    hovertemplate: '<b>%{source.label}</b> → <b>%{target.label}</b><br>' +
                      'Reports: %{value:,}<br>' +
                      '<extra></extra>',
                  },
                  textfont: {
                    size: 13,
                    family: 'Poppins, sans-serif'
                  },
                  arrangement: 'snap',
                  valueformat: ',',
                }
              ]}
              layout={{
                title: {
                  // Text removed as requested
                  // text: '<b>UN Humanitarian Evaluation Reports Processing Pipeline</b>',
                  // font: {
                  //   size: 20,
                  //   family: 'Poppins, sans-serif',
                  //   color: '#2C3E50'
                  // },
                  // x: 0.5,
                  // xanchor: 'center'
                },
                font: {
                  size: 12,
                  family: 'Open Sans, sans-serif'
                },
                height: 600,
                paper_bgcolor: 'white',
                plot_bgcolor: 'white',
                margin: { t: 60, b: 50, l: 20, r: 20 },
                hoverlabel: {
                  bgcolor: '#2C3E50',
                  font: {
                    family: 'Open Sans, sans-serif',
                    size: 13,
                    color: 'white'
                  },
                  bordercolor: '#2C3E50',
                  align: 'left',
                  namelength: -1
                },
                transition: {
                  duration: 500,
                  easing: 'cubic-in-out'
                },
                annotations: [
                  // Layer 1 label (bottom)
                  {
                    x: 0.02,
                    y: -0.08,
                    xref: 'paper',
                    yref: 'paper',
                    text: `UN Organization (orgs=${sankeyData.annotations.num_orgs.toLocaleString()}, reports=${sankeyData.annotations.total_records.toLocaleString()})`,
                    showarrow: false,
                    font: { size: 11, color: '#2C3E50', family: 'Open Sans, sans-serif' },
                    xanchor: 'left'
                  },
                  // Layer 2 label
                  {
                    x: 0.35,
                    y: -0.08,
                    xref: 'paper',
                    yref: 'paper',
                    text: `reports=${sankeyData.annotations.layer2_count.toLocaleString()}`,
                    showarrow: false,
                    font: { size: 11, color: '#2C3E50', family: 'Open Sans, sans-serif' },
                    xanchor: 'center',
                    bgcolor: 'rgba(255,255,255,0.8)',
                    borderpad: 8,
                    bordercolor: 'rgba(200,200,200,0.5)',
                    borderwidth: 1
                  },
                  // Layer 3 label
                  {
                    x: 0.65,
                    y: -0.08,
                    xref: 'paper',
                    yref: 'paper',
                    text: `reports=${sankeyData.annotations.layer3_count.toLocaleString()}`,
                    showarrow: false,
                    font: { size: 11, color: '#2C3E50', family: 'Open Sans, sans-serif' },
                    xanchor: 'center',
                    bgcolor: 'rgba(255,255,255,0.8)',
                    borderpad: 8,
                    bordercolor: 'rgba(200,200,200,0.5)',
                    borderwidth: 1
                  },
                  // Layer 4 label
                  {
                    x: 0.98,
                    y: -0.08,
                    xref: 'paper',
                    yref: 'paper',
                    text: `reports=${sankeyData.annotations.layer4_count.toLocaleString()}`,
                    showarrow: false,
                    font: { size: 11, color: '#2C3E50', family: 'Open Sans, sans-serif' },
                    xanchor: 'right',
                    bgcolor: 'rgba(255,255,255,0.8)',
                    borderpad: 8,
                    bordercolor: 'rgba(200,200,200,0.5)',
                    borderwidth: 1
                  }
                ]
              }}
              config={{
                displayModeBar: true,
                displaylogo: false,
                modeBarButtonsToRemove: ['lasso2d', 'select2d'],
                toImageButtonOptions: {
                  format: 'png',
                  filename: 'pipeline_flow',
                  height: 800,
                  width: 1200,
                  scale: 2
                },
                animated: true
              }}
              style={{ width: '100%', height: '600px' }}
              useResizeHandler={true}
              frames={[]}
            />
          </div>
        </div>

      </div>
    </div>
  );
};

export const Processing: React.FC<PipelineProps> = ({ dataSource = 'uneg' }) => {
  const { timelineData, loading, error } = usePipelineData(dataSource);
  const [timeRange, setTimeRange] = useState<'24h' | '48h' | 'all'>('all');
  const filteredData = filterTimelineData(timelineData, timeRange);
  const hasTimelineData = Boolean(
    filteredData
    && ((filteredData.histogram?.x?.length ?? 0) > 0
      || (filteredData.phase_distribution?.x?.length ?? 0) > 0
      || (filteredData.errors_histogram?.x?.length ?? 0) > 0)
  );

  if (loading) {
    return <PipelineLoading />;
  }

  if (error) {
    return <PipelineError error={error} />;
  }

  return (
    <div className="statistics-container">
      <div className="statistics-content">
        <h2 className="statistics-title">Document processing performance</h2>
        {hasTimelineData ? (
          <PipelineTimelineSection
            filteredData={filteredData}
            timeRange={timeRange}
            setTimeRange={setTimeRange}
          />
        ) : (
          <PipelineEmpty />
        )}
      </div>
    </div>
  );
};
