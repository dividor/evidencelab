import React from 'react';
import { DocumentsChart } from './documents/DocumentsChart';
import { useDocumentsState } from './documents/useDocumentsState';

interface StatsProps {
    dataSource?: string;
    onNavigateToDocuments: (filter: { category: string; value: string }) => void;
}

export const Stats: React.FC<StatsProps> = ({
    dataSource = 'uneg',
    onNavigateToDocuments,
}) => {
    const state = useDocumentsState(dataSource);

    const handleBarClick = (category: string) => {
        // Navigate to Documents tab with the selected filter
        // category is the value (like "UNDP" or "2023")
        // properties of state.chartView determine the column
        // But chartView here is local to Stats page.
        // Wait, chartView maps to a column.
        // 'agency' -> 'organization'
        // 'year' -> 'published_year'
        // 'type' -> 'document_type'
        // 'language' -> 'language'
        // 'format' -> 'file_format'
        // 'status' -> 'status'
        // 'location' -> 'country' (if implemented)

        let column = 'organization'; // default
        switch (state.chartView) {
            case 'agency': column = 'organization'; break;
            case 'year': column = 'published_year'; break;
            case 'type': column = 'document_type'; break;
            case 'language': column = 'language'; break;
            case 'format': column = 'file_format'; break;
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
                <h2 className="statistics-title">Document Statistics</h2>
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
