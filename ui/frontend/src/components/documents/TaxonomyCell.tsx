import React, { useState } from 'react';

interface TaxonomyValue {
    code: string;
    name: string;
    reason?: string;
}

interface TaxonomyCellProps {
    doc: any;
    taxonomyKey: string;
    taxonomyConfig: any;
    onOpenTaxonomyModal?: (value: TaxonomyValue, definition: string, taxonomyName: string) => void;
}

export const TaxonomyCell: React.FC<TaxonomyCellProps> = ({
    doc,
    taxonomyKey,
    taxonomyConfig,
    onOpenTaxonomyModal
}) => {
    const [expanded, setExpanded] = useState(false);

    const values = doc.taxonomies?.[taxonomyKey];

    if (!values || !Array.isArray(values) || values.length === 0) {
        return <td>-</td>;
    }

    // Access taxonomy definitions from config
    const taxonomyDefinitions = taxonomyConfig?.values;
    const taxonomyName = taxonomyConfig?.name || taxonomyKey;

    // Normalize to new format (backward compatible)
    const normalizedValues: TaxonomyValue[] = values.map((v: any) => {
        if (typeof v === 'string') {
            // Old format: "sdg1" or "sdg1 - No Poverty"
            const code = v.includes(' - ') ? v.split(' - ')[0] : v;
            const name = v.includes(' - ') ? v.split(' - ').slice(1).join(' - ') : '';
            return {
                code: code.toLowerCase(),
                name,
                reason: 'Legacy data - no reason available'
            };
        } else {
            // New format: {code, name, reason}
            return v;
        }
    });

    const MAX_VISIBLE = 3;
    const showMore = normalizedValues.length > MAX_VISIBLE;
    const visibleValues = expanded ? normalizedValues : normalizedValues.slice(0, MAX_VISIBLE);
    const remainingCount = normalizedValues.length - MAX_VISIBLE;

    return (
        <td>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', alignItems: 'center' }}>
                {visibleValues.map((taxValue: TaxonomyValue, index: number) => {
                    const definition = taxonomyDefinitions?.[taxValue.code]?.definition || '';
                    const displayName = taxValue.name || taxonomyDefinitions?.[taxValue.code]?.name || taxValue.code;
                    const tooltip = definition || displayName;

                    return (
                        <button
                            key={`${taxValue.code}-${index}`}
                            onClick={(e) => {
                                e.stopPropagation();
                                if (onOpenTaxonomyModal && taxValue.reason) {
                                    onOpenTaxonomyModal(taxValue, definition, taxonomyName);
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
                                cursor: onOpenTaxonomyModal && taxValue.reason ? 'pointer' : 'default',
                                fontWeight: 500,
                                whiteSpace: 'nowrap',
                                textDecoration: onOpenTaxonomyModal && taxValue.reason ? 'underline' : 'none'
                            }}
                            title={tooltip}
                            disabled={!onOpenTaxonomyModal || !taxValue.reason}
                        >
                            {taxValue.code.toUpperCase()}
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
