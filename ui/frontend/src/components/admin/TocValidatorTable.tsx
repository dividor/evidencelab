import React from 'react';
import type { TocValidationResult } from '../../types/api';
import TocValidationResultCell from './TocValidationResultCell';
import TocValidatorFilterPopover from './TocValidatorFilterPopover';
import type { FilterColumn } from './useTocValidator';

interface TocValidatorTableProps {
  documents: any[];
  results: Map<string, TocValidationResult>;
  changedIds: Set<string>;
  selectedIds: Set<string>;
  approvedIds: Set<string>;
  onToggle: (docId: string) => void;
  onTogglePage: () => void;
  allOnPageSelected: boolean;
  onOpenMetadata: (doc: any) => void;
  onOpenToc: (doc: any) => void;
  // Column filtering
  columnFilters: Record<string, string>;
  activeFilterColumn: FilterColumn | null;
  filterPosition: { top: number; left: number };
  onFilterClick: (column: FilterColumn, event: React.MouseEvent<HTMLButtonElement>) => void;
  onApplyFilter: (column: FilterColumn, value: string) => void;
  onClearFilter: (column: FilterColumn) => void;
  hasActiveFilter: (column: FilterColumn) => boolean;
  getCategoricalOptions: (column: FilterColumn) => string[];
  onCloseFilter: () => void;
}

const docKey = (doc: any): string => String(doc.doc_id || doc.id || '');

/** Funnel icon, matching the Documents Library header filter button. */
const FunnelIcon: React.FC = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M0.5 1.5h11l-4.5 5.25v3.75l-2 1.5v-5.25l-4.5-5.25z"
      stroke="currentColor"
      strokeWidth="1"
      fill="none"
    />
  </svg>
);

/** Column header with a filter funnel button. */
const FilterableHeader: React.FC<{
  column: FilterColumn;
  label: string;
  onFilterClick: (column: FilterColumn, event: React.MouseEvent<HTMLButtonElement>) => void;
  hasActiveFilter: (column: FilterColumn) => boolean;
}> = ({ column, label, onFilterClick, hasActiveFilter }) => (
  <th>
    <div className="toc-th-inner">
      <span>{label}</span>
      <button
        type="button"
        className={`filter-icon-button ${hasActiveFilter(column) ? 'active' : ''}`}
        onClick={(event) => onFilterClick(column, event)}
        aria-label={`Filter ${label.toLowerCase()}`}
      >
        <FunnelIcon />
      </button>
    </div>
  </th>
);

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
  approvedIds,
  onToggle,
  onTogglePage,
  allOnPageSelected,
  onOpenMetadata,
  onOpenToc,
  columnFilters,
  activeFilterColumn,
  filterPosition,
  onFilterClick,
  onApplyFilter,
  onClearFilter,
  hasActiveFilter,
  getCategoricalOptions,
  onCloseFilter,
}) => (
  <>
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
          <FilterableHeader
            column="title"
            label="Title"
            onFilterClick={onFilterClick}
            hasActiveFilter={hasActiveFilter}
          />
          <FilterableHeader
            column="organization"
            label="Organization"
            onFilterClick={onFilterClick}
            hasActiveFilter={hasActiveFilter}
          />
          <FilterableHeader
            column="status"
            label="Status"
            onFilterClick={onFilterClick}
            hasActiveFilter={hasActiveFilter}
          />
          <FilterableHeader
            column="review"
            label="Table of Contents review"
            onFilterClick={onFilterClick}
            hasActiveFilter={hasActiveFilter}
          />
          <th>Links</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((doc) => {
          const key = docKey(doc);
          const status = doc.status || doc.sys_status || 'downloaded';
          const approved = approvedIds.has(key);
          const rowClass = [
            selectedIds.has(key) ? 'admin-row-selected' : '',
            changedIds.has(key) ? 'toc-validator-row-changed' : '',
            approved ? 'toc-validator-row-approved' : '',
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
                approved={approved}
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
    {activeFilterColumn && (
      <TocValidatorFilterPopover
        column={activeFilterColumn}
        position={filterPosition}
        currentValue={columnFilters[activeFilterColumn] || ''}
        options={getCategoricalOptions(activeFilterColumn)}
        onApply={onApplyFilter}
        onClear={onClearFilter}
        onClose={onCloseFilter}
      />
    )}
  </>
);

export default TocValidatorTable;
