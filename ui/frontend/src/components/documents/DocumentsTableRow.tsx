import React from 'react';
import { DocumentActionsCell, DocumentModerationCell } from './DocumentActionsCell';
import { DocumentChunksCell } from './DocumentChunksCell';
import { DocumentErrorCell } from './DocumentErrorCell';
import { DocumentFormatCell } from './DocumentFormatCell';
import { DocumentLinksCell } from './DocumentLinksCell';
import { DocumentMetadataCell } from './DocumentMetadataCell';
import { DocumentStatusCell } from './DocumentStatusCell';
import { DocumentsSummaryCell } from './DocumentsSummaryCell';
import { TaxonomyCell } from './TaxonomyCell';
import { formatTimestamp, getLastUpdatedTimestamp } from './documentsModalUtils';
import { summaryProvenance } from './summary/summaryProvenance';
import API_BASE_URL, { USER_FEEDBACK } from '../../config';

const hasSuccessfulParse = (status: string | undefined): boolean =>
  Boolean(status) && status !== 'downloaded' && !status!.includes('error') && !status!.includes('failed');

const getThumbnailUrl = (doc: any, dataSource: string): string | null => {
  const docId = doc.doc_id || doc.id;
  if (!docId) return null;
  const docDataSource = doc.data_source || dataSource;
  return `${API_BASE_URL}/document/${docId}/thumbnail?data_source=${docDataSource}`;
};

const handleThumbnailError = (e: React.SyntheticEvent<HTMLImageElement>) => {
  const target = e.target as HTMLImageElement;
  target.style.display = 'none';
  const container = target.closest('.doc-title-thumbnail-container');
  const placeholder = container?.querySelector('.doc-title-thumbnail-placeholder') as HTMLElement;
  if (placeholder) placeholder.style.display = 'flex';
};

const DocumentThumbnail: React.FC<{ doc: any; thumbnailUrl: string }> = ({ doc, thumbnailUrl }) => {
  const img = (
    <img
      src={thumbnailUrl}
      alt={doc.title || 'Document thumbnail'}
      className="doc-title-thumbnail"
      onError={handleThumbnailError}
    />
  );

  if (doc.pdf_url) {
    return (
      <a
        href={doc.pdf_url}
        target="_blank"
        rel="noopener noreferrer"
        title={doc.organization ? `${doc.organization} Document` : 'Document'}
      >
        {img}
      </a>
    );
  }
  return img;
};

/** Title cell: an optional selection checkbox, the thumbnail and the title. */
const DocumentTitleCell: React.FC<{
  doc: any;
  thumbnailUrl: string | null;
  selected: boolean;
  onToggleSelect?: (doc: any) => void;
}> = ({ doc, thumbnailUrl, selected, onToggleSelect }) => (
  <td className="doc-title">
    <div className="doc-title-with-thumbnail">
      {onToggleSelect && (
        <input
          type="checkbox"
          className="doc-select-checkbox"
          checked={selected}
          onChange={() => onToggleSelect(doc)}
          aria-label={`Select ${doc.title || 'Untitled'}`}
        />
      )}
      <div className="doc-title-thumbnail-container">
        {thumbnailUrl ? (
          <>
            <DocumentThumbnail doc={doc} thumbnailUrl={thumbnailUrl} />
            <div className="doc-title-thumbnail-placeholder" style={{ display: 'none' }}>
              No preview
            </div>
          </>
        ) : (
          <div className="doc-title-thumbnail-placeholder">
            No preview
          </div>
        )}
      </div>
      <div className="doc-title-text">
        {doc.title || 'Untitled'}
      </div>
    </div>
  </td>
);

export const DocumentsTableRow: React.FC<{
  doc: any;
  index: number;
  onOpenSummary: (summary: string, docTitle: string, docId?: string) => void;
  onOpenTaxonomyModal?: (value: any, definition: string, taxonomyName: string, docId?: string, docTitle?: string, docSummary?: string) => void;
  onOpenToc: (doc: any) => void;
  onOpenMetadata: (doc: any) => void;
  onOpenTimeline: (doc: any) => void;
  onOpenLogs: (doc: any) => void;
  onViewChunks: (doc: any) => void;
  onReprocess: (doc: any) => void;
  onOpenQueue: () => void;
  onOpenPdfPreview: (doc: any) => void;
  reprocessingDocId: string | null;
  dataSourceConfig?: import('../../App').DataSourceConfigItem;
  dataSource?: string;
  /** Superusers get a Hide/Restore column */
  canModerate?: boolean;
  moderatingDocId?: string | null;
  onToggleHidden?: (doc: any) => void;
  /** Set for administrators: tick the document for a bulk summary run. */
  selected?: boolean;
  onToggleSelect?: (doc: any) => void;
  /** Administrators can open an empty summary to write or generate one. */
  canEditSummary?: boolean;
}> = ({
  doc,
  index,
  onOpenSummary,
  onOpenTaxonomyModal,
  onOpenToc,
  onOpenMetadata,
  onOpenTimeline,
  onOpenLogs,
  onViewChunks,
  onReprocess,
  onOpenQueue,
  onOpenPdfPreview,
  reprocessingDocId,
  dataSourceConfig,
  dataSource = '',
  canModerate = false,
  moderatingDocId = null,
  onToggleHidden,
  selected = false,
  onToggleSelect,
  canEditSummary = false,
}) => {
    const lastUpdated = formatTimestamp(getLastUpdatedTimestamp(doc.stages || {}));

    // Get taxonomy configurations
    const taxonomies = dataSourceConfig?.pipeline?.tag?.taxonomies || {};

    const hasParsedStatus = hasSuccessfulParse(doc.status);

    // Construct thumbnail URL (only for parsed or later documents)
    const thumbnailUrl = hasParsedStatus ? getThumbnailUrl(doc, dataSource) : null;

    return (
      <tr key={doc.id || index}>
        <DocumentTitleCell
          doc={doc}
          thumbnailUrl={thumbnailUrl}
          selected={selected}
          onToggleSelect={onToggleSelect}
        />
        <DocumentLinksCell doc={doc} dataSource={dataSource} onOpenPdfPreview={onOpenPdfPreview} />
        <td className="doc-summary">
          <DocumentsSummaryCell
            summary={doc.full_summary}
            docTitle={doc.title || 'Untitled'}
            onOpenSummary={(summary, title) => onOpenSummary(summary, title, doc.doc_id)}
            canEdit={canEditSummary}
            provenance={summaryProvenance(doc)}
          />
        </td>
        <DocumentMetadataCell doc={doc} onOpenToc={onOpenToc} onOpenMetadata={onOpenMetadata} />
        <td>{doc.organization || '-'}</td>
        <DocumentStatusCell doc={doc} onOpenTimeline={onOpenTimeline} onOpenLogs={onOpenLogs} />
        <td>{doc.document_type || '-'}</td>
        <td>{doc.published_year || '-'}</td>
        <td>{doc.language || '-'}</td>
        {Object.keys(taxonomies).map((taxonomyKey) => (
          <TaxonomyCell
            key={taxonomyKey}
            doc={doc}
            taxonomyKey={taxonomyKey}
            taxonomyConfig={taxonomies[taxonomyKey]}
            onOpenTaxonomyModal={onOpenTaxonomyModal ? (value: any, definition: string, taxonomyName: string) => onOpenTaxonomyModal(value, definition, taxonomyName, doc.doc_id, doc.title, doc.full_summary) : undefined}
          />
        ))}
        <DocumentFormatCell fileFormat={doc.file_format} />
        <td>{doc.page_count || '-'}</td>
        <td>{doc.file_size_mb || '-'}</td>
        <DocumentErrorCell doc={doc} />
        <td>{lastUpdated || '-'}</td>
        <td>{doc.ocr_applied ? 'Yes' : '-'}</td>
        <DocumentChunksCell doc={doc} onViewChunks={onViewChunks} />
        {USER_FEEDBACK && (
          <DocumentActionsCell
            doc={doc}
            reprocessingDocId={reprocessingDocId}
            onReprocess={onReprocess}
            onOpenQueue={onOpenQueue}
          />
        )}
        {canModerate && onToggleHidden && (
          <DocumentModerationCell
            doc={doc}
            moderatingDocId={moderatingDocId}
            onToggleHidden={onToggleHidden}
          />
        )}
      </tr>
    );
  };
