import React, { useState } from 'react';
import { SearchResult } from '../types/api';
import {
  resolveConfiguredFields,
  getConfiguredFieldKeys,
} from './documents/documentsModalUtils';

interface SearchResultMetadataProps {
  result: SearchResult;
  onClose: (e: React.MouseEvent) => void;
  onOpenToc: (docId: string, toc: string, pdfUrl?: string, pageCount?: number | null) => void;
  metadataPanelFields?: Record<string, string>;
}

const EXCLUDE_FIELDS = new Set([
  'text',
  'semanticMatches',
  'metadata',
  'full_summary',
  'toc',
  'year',
  'doc_id',
  'highlightedText',
  'translated_snippet',
  'translated_title',
  'translated_headings_display',
  'translated_language',
  'is_translating',
  'chunk_elements',
  'elements',
  'images',
  'tables',
  'table_data'
]);

const isEmptyValue = (value: unknown) => {
  if (value === null || value === undefined || value === '') {
    return true;
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  if (typeof value === 'object') {
    return Object.keys(value as Record<string, unknown>).length === 0;
  }
  return false;
};

const formatMetadataKey = (key: string) =>
  key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());

const renderValueParts = (valueStr: string) => {
  const urlSplitRegex = /(https?:\/\/[^\s]+)/g;
  const urlMatchRegex = /^https?:\/\/[^\s]+$/;
  const parts = valueStr.split(urlSplitRegex);
  return parts.map((part, index) => {
    if (urlMatchRegex.test(part)) {
      return React.createElement(
        'a',
        {
          key: index,
          href: part,
          target: '_blank',
          rel: 'noopener noreferrer',
          className: 'metadata-link'
        },
        part
      );
    }
    return part || null;
  });
};

const renderValue = (value: unknown) => {
  if (typeof value === 'object' && value !== null) {
    const isArray = Array.isArray(value);
    const isObjectArray = isArray && value.length > 0 && typeof value[0] === 'object';
    if (!isArray || isObjectArray) {
      return <pre className="metadata-json">{JSON.stringify(value, null, 2)}</pre>;
    }
  }

  const valueStr = Array.isArray(value) ? value.join(', ') : String(value);
  return renderValueParts(valueStr);
};

const buildMetadataFields = (result: SearchResult) => {
  const allFields = { ...result, ...result.metadata };
  return Object.entries(allFields)
    .filter(([key, value]) => !EXCLUDE_FIELDS.has(key) && !isEmptyValue(value))
    .sort(([keyA], [keyB]) => keyA.localeCompare(keyB));
};

const MetadataFieldRow = ({
  fieldKey,
  value,
  result,
  onOpenToc
}: {
  fieldKey: string;
  value: unknown;
  result: SearchResult;
  onOpenToc: (docId: string, toc: string, pdfUrl?: string, pageCount?: number | null) => void;
}) => {
  const handleOpenToc = (e: React.MouseEvent) => {
    e.stopPropagation();
    const pageCount =
      result.page_count ??
      result.metadata?.page_count ??
      result.metadata?.sys_page_count ??
      null;
    onOpenToc(
      result.doc_id,
      String(value),
      result.pdf_url,
      pageCount
    );
  };

  const content = fieldKey === 'toc_classified' && value ? (
    <button
      className="doc-link"
      onClick={handleOpenToc}
      style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
    >
      Contents
    </button>
  ) : fieldKey === 'headings' && Array.isArray(value) ? (
    value.join(' > ')
  ) : (
    renderValue(value)
  );

  return (
    <div className="metadata-field">
      <span className="metadata-key">{formatMetadataKey(fieldKey)}:</span>
      <span className="metadata-value">{content}</span>
    </div>
  );
};

export const SearchResultMetadata = ({
  result,
  onClose,
  onOpenToc,
  metadataPanelFields,
}: SearchResultMetadataProps) => {
  const [systemInfoExpanded, setSystemInfoExpanded] = useState(false);
  const metadataFields = buildMetadataFields(result);
  const docId = result.doc_id || result.metadata?.doc_id;

  const allFields = { ...result, ...result.metadata };
  const hasConfiguredFields = metadataPanelFields && Object.keys(metadataPanelFields).length > 0;
  const configuredItems = hasConfiguredFields
    ? resolveConfiguredFields(allFields, metadataPanelFields)
    : [];
  const configuredFieldKeys = hasConfiguredFields
    ? getConfiguredFieldKeys(allFields, metadataPanelFields)
    : new Set<string>();

  // Filter out configured field keys from remaining fields
  const remainingFields = hasConfiguredFields
    ? metadataFields.filter(([key]) => !configuredFieldKeys.has(key))
    : metadataFields;

  if (metadataFields.length === 0 && configuredItems.length === 0) {
    return (
      <div className="metadata-content">
        <div className="metadata-header">
          <span>No additional metadata available</span>
          <button className="metadata-close" onClick={onClose}>
            Hide
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="metadata-content">
      <div className="metadata-header">
        <span className="metadata-header-title">Metadata</span>
        <button className="metadata-close" onClick={onClose}>
          Hide
        </button>
      </div>
      {docId && (
        <MetadataFieldRow
          fieldKey="doc_id"
          value={docId}
          result={result}
          onOpenToc={onOpenToc}
        />
      )}
      {/* Configured fields at top */}
      {hasConfiguredFields && configuredItems.map((item) => (
        <MetadataFieldRow
          key={item.key}
          fieldKey={item.displayKey}
          value={item.value}
          result={result}
          onOpenToc={onOpenToc}
        />
      ))}
      {/* Remaining fields: collapsible when configured fields present */}
      {hasConfiguredFields && remainingFields.length > 0 && (
        <>
          <div
            className="metadata-section-toggle"
            onClick={() => setSystemInfoExpanded(!systemInfoExpanded)}
            style={{ cursor: 'pointer', padding: '4px 0', marginTop: '8px' }}
          >
            <span className="metadata-section-icon">
              {systemInfoExpanded ? '▼' : '▶'}
            </span>
            {' '}
            <strong>System Information</strong>
          </div>
          {systemInfoExpanded && remainingFields.map(([key, value]) => (
            <MetadataFieldRow
              key={key}
              fieldKey={key}
              value={value}
              result={result}
              onOpenToc={onOpenToc}
            />
          ))}
        </>
      )}
      {/* Fallback: no configured fields */}
      {!hasConfiguredFields && metadataFields.map(([key, value]) => (
        <MetadataFieldRow
          key={key}
          fieldKey={key}
          value={value}
          result={result}
          onOpenToc={onOpenToc}
        />
      ))}
    </div>
  );
};
