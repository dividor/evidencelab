import React, { useEffect } from 'react';
import { DocumentsChart } from './documents/DocumentsChart';
import { useDocumentsState } from './documents/useDocumentsState';

interface StatsProps {
    dataSource?: string;
    onNavigateToDocuments: (filter: { category: string; value: string }) => void;
}

const RefreshIcon: React.FC<{ spinning?: boolean }> = ({ spinning }) => (
    <svg
        className={`refresh-icon${spinning ? ' refresh-icon-spinning' : ''}`}
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
    >
        <path d="M21 2v6h-6" />
        <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
        <path d="M3 22v-6h6" />
        <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
    </svg>
);

export const Stats: React.FC<StatsProps> = ({
    dataSource = '',
    onNavigateToDocuments,
}) => {
    const state = useDocumentsState(dataSource);

    // Auto-switch to first chart view that has data when current view is empty
    useEffect(() => {
        if (!state.stats) return;
        const breakdownMap: Record<string, Record<string, unknown>> = {
            year: state.stats.year_breakdown || {},
            type: state.stats.type_breakdown || {},
            agency: state.stats.agency_breakdown || {},
            language: state.stats.language_breakdown || {},
            format: state.stats.format_breakdown || {},
            country: state.stats.country_breakdown || {},
            status: state.stats.status_breakdown || {},
        };
        const current = breakdownMap[state.chartView];
        if (current && Object.keys(current).length > 0) return;
        const views = ['status', 'year', 'type', 'agency', 'language', 'format', 'country'] as const;
        for (const view of views) {
            if (Object.keys(breakdownMap[view] || {}).length > 0) {
                state.setChartView(view);
                return;
            }
        }
    }, [state.stats, state.chartView, state.setChartView]);

    const handleBarClick = (category: string) => {
        let column = 'organization'; // default
        switch (state.chartView) {
            case 'agency': column = 'organization'; break;
            case 'year': column = 'published_year'; break;
            case 'type': column = 'document_type'; break;
            case 'language': column = 'language'; break;
            case 'format': column = 'file_format'; break;
            case 'country': column = 'country'; break;
            case 'status': column = 'status'; break;
        }

        onNavigateToDocuments({ category: column, value: category });
    };

    if (state.loading) {
        return (
            <div className="statistics-container">
                <div className="statistics-loading">
                    <span className="generating-text">
                        {'Loading analytics ...'.split('').map((char, index) => (
                            <span key={index} className="wave-char" style={{ animationDelay: `${index * 0.05}s` }}>
                                {char === ' ' ? '\u00A0' : char}
                            </span>
                        ))}
                    </span>
                </div>
            </div>
        );
    }

    if (state.error || !state.stats) {
        return (
            <div className="statistics-container">
                <div className="statistics-error">{state.error || 'No data available'}</div>
            </div>
        );
    }

    return (
        <div className="statistics-container">
            <div className="statistics-content">
                <div className="statistics-title-row">
                    <h2 className="statistics-title">Document Statistics</h2>
                    <button
                        className="refresh-button"
                        onClick={state.refreshStats}
                        disabled={state.loading}
                        title="Refresh data"
                    >
                        <RefreshIcon spinning={state.loading} />
                    </button>
                </div>
                <div className="chart-section">
                    <DocumentsChart
                        stats={state.stats}
                        chartView={state.chartView}
                        onChartViewChange={state.setChartView}
                        hoveredBar={state.hoveredBar}
                        tooltipPos={state.tooltipPos}
                        onHoverChange={state.setHoveredBar}
                        onTooltipMove={state.setTooltipPos}
                        onBarClick={handleBarClick}
                    />
                </div>
            </div>
        </div>
    );
};
