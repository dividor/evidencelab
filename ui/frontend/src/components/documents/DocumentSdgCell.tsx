import React, { useState } from 'react';

interface TaxonomyValue {
    code: string;
    name: string;
    reason?: string;
}

interface DocumentSdgCellProps {
    doc: any;
    dataSourceConfig?: import('../../App').DataSourceConfigItem;
    onOpenTaxonomyModal?: (value: TaxonomyValue, definition: string, taxonomyName: string) => void;
}

export const DocumentSdgCell: React.FC<DocumentSdgCellProps> = ({
    doc,
    dataSourceConfig,
    onOpenTaxonomyModal
}) => {
    const [expanded, setExpanded] = useState(false);

    const sdgs = doc.taxonomies?.sdg;

    if (!sdgs || !Array.isArray(sdgs) || sdgs.length === 0) {
        return <td>-</td>;
    }

    // Access taxonomy definitions if available
    const sdgDefinitions = dataSourceConfig?.pipeline?.tag?.taxonomies?.sdg?.values;

    // Normalize to new format (backward compatible)
    const normalizedSdgs: TaxonomyValue[] = sdgs.map((s: any) => {
        if (typeof s === 'string') {
            // Old format: "sdg1" or "sdg1 - No Poverty"
            const match = s.match(/sdg(\d+)/i);
            const code = match ? `sdg${match[1]}` : s.toLowerCase();
            const name = s.includes(' - ') ? s.split(' - ').slice(1).join(' - ') : '';
            return {
                code,
                name,
                reason: 'Legacy data - no reason available'
            };
        } else {
            // New format: {code, name, reason}
            return s;
        }
    });

    const MAX_VISIBLE = 3;
    const showMore = normalizedSdgs.length > MAX_VISIBLE;
    const visibleSdgs = expanded ? normalizedSdgs : normalizedSdgs.slice(0, MAX_VISIBLE);
    const remainingCount = normalizedSdgs.length - MAX_VISIBLE;

    return (
        <td>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', alignItems: 'center' }}>
                {visibleSdgs.map((sdgValue: TaxonomyValue, index: number) => {
                    const match = sdgValue.code.match(/sdg(\d+)/i);
                    const num = match ? match[1] : '';
                    const definition = sdgDefinitions?.[sdgValue.code]?.definition || '';
                    const tooltip = definition || (num ? `Sustainable Development Goal ${num}` : sdgValue.code);

                    return (
                        <button
                            key={`${sdgValue.code}-${index}`}
                            onClick={(e) => {
                                e.stopPropagation();
                                if (onOpenTaxonomyModal && sdgValue.reason) {
                                    onOpenTaxonomyModal(sdgValue, definition, 'SDG');
                                }
                            }}
                            style={{
                                display: 'inline-block',
                                padding: '2px 6px',
                                borderRadius: '4px',
                                background: '#e0f2fe',
                                color: '#0369a1',
                                fontSize: '0.75rem',
                                border: 'none',
                                cursor: onOpenTaxonomyModal && sdgValue.reason ? 'pointer' : 'default',
                                fontWeight: 500,
                                whiteSpace: 'nowrap',
                                textDecoration: onOpenTaxonomyModal && sdgValue.reason ? 'underline' : 'none'
                            }}
                            title={tooltip}
                            disabled={!onOpenTaxonomyModal || !sdgValue.reason}
                        >
                            {sdgValue.code.toUpperCase()}
                        </button>
                    );
                })}
                {showMore && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            setExpanded(!expanded);
                        }}
                        style={{
                            background: 'none',
                            border: 'none',
                            color: '#666',
                            fontSize: '0.75rem',
                            cursor: 'pointer',
                            textDecoration: 'underline',
                            padding: '0 4px',
                            fontWeight: 500,
                        }}
                    >
                        {expanded ? 'Show less' : `+${remainingCount} more`}
                    </button>
                )}
            </div>
        </td>
    );
};
