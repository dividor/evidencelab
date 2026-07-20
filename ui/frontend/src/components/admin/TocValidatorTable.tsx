import React from 'react';
import type { TocValidationResult } from '../../types/api';
import TocValidationResultCell from './TocValidationResultCell';

interface TocValidatorTableProps {
  documents: any[];
  results: Map<string, TocValidationResult>;
  changedIds: Set<string>;
  selectedIds: Set<string>;
  onToggle: (docId: string) => void;
  onTogglePage: () => void;
  allOnPageSelected: boolean;
  onOpenMetadata: (doc: any) => void;
  onOpenToc: (doc: any) => void;
}

const docKey = (doc: any): string => String(doc.doc_id || doc.id || '');

/** Per-row Metadata / Contents links, mirroring the Documents Library. */
const DocumentLinksCell: React.FC<{
  doc: any;
  onOpenMetadata: (doc: any) => void;
  onOpenToc: (doc: any) => void;
}> = ({ doc, onOpenMetadata, onOpenToc }) => (
  <td className="doc-links">
    <button
      type="button"
      className="doc-link"
      title="Display all fields for this document"
      onClick={() => onOpenMetadata(doc)}
    >
      Metadata
    </button>
    {doc.toc && (
      <button
        type="button"
        className="doc-link"
        title="Display document table of contents and section tags"
        onClick={() => onOpenToc(doc)}
      >
        Contents
      </button>
    )}
  </td>
);

export const TocValidatorTable: React.FC<TocValidatorTableProps> = ({
  documents,
  results,
  changedIds,
  selectedIds,
  onToggle,
  onTogglePage,
  allOnPageSelected,
  onOpenMetadata,
  onOpenToc,
}) => (
  <table className="admin-table toc-validator-table">
    <thead>
      <tr>
        <th className="toc-validator-select-col">
          <input
            type="checkbox"
            checked={allOnPageSelected}
            onChange={onTogglePage}
            aria-label="Select all documents on this page"
          />
        </th>
        <th>Title</th>
        <th>Organization</th>
        <th>Status</th>
        <th>Validation</th>
        <th>Links</th>
      </tr>
    </thead>
    <tbody>
      {documents.map((doc) => {
        const key = docKey(doc);
        const status = doc.status || doc.sys_status || 'downloaded';
        const rowClass = [
          selectedIds.has(key) ? 'admin-row-selected' : '',
          changedIds.has(key) ? 'toc-validator-row-changed' : '',
        ]
          .filter(Boolean)
          .join(' ');
        return (
          <tr key={key} className={rowClass}>
            <td className="toc-validator-select-col">
              <input
                type="checkbox"
                checked={selectedIds.has(key)}
                onChange={() => onToggle(key)}
                aria-label={`Select ${doc.map_title || doc.title || key}`}
              />
            </td>
            <td>{doc.map_title || doc.title || '(untitled)'}</td>
            <td>{doc.organization || doc.map_organization || '-'}</td>
            <td>
              <span
                className={`status-badge status-${status} ${
                  status === 'indexed' ? 'status-badge-success' : ''
                }`}
              >
                {status}
              </span>
            </td>
            <TocValidationResultCell
              result={results.get(key)}
              changed={changedIds.has(key)}
            />
            <DocumentLinksCell
              doc={doc}
              onOpenMetadata={onOpenMetadata}
              onOpenToc={onOpenToc}
            />
          </tr>
        );
      })}
      {documents.length === 0 && (
        <tr>
          <td colSpan={6} className="toc-validator-empty">
            No documents found.
          </td>
        </tr>
      )}
    </tbody>
  </table>
);

export default TocValidatorTable;
