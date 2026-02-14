import React from 'react';
import { DocumentActionsCell } from './DocumentActionsCell';
import { DocumentChunksCell } from './DocumentChunksCell';
import { DocumentErrorCell } from './DocumentErrorCell';
import { DocumentFormatCell } from './DocumentFormatCell';
import { DocumentLinksCell } from './DocumentLinksCell';
import { DocumentMetadataCell } from './DocumentMetadataCell';
import { DocumentStatusCell } from './DocumentStatusCell';
import { DocumentsSummaryCell } from './DocumentsSummaryCell';
import { TaxonomyCell } from './TaxonomyCell';
import { formatTimestamp, getLastUpdatedTimestamp } from './documentsModalUtils';
import API_BASE_URL from '../../config';

// Helper function to construct thumbnail URL using the API endpoint
const getThumbnailUrl = (doc: any, dataSource: string): string | null => {
  const docId = doc.doc_id || doc.id;
  if (!docId) return null;

  const docDataSource = doc.data_source || dataSource;
  return `${API_BASE_URL}/document/${docId}/thumbnail?data_source=${docDataSource}`;
};

export const DocumentsTableRow: React.FC<{
  doc: any;
  index: number;
  onOpenSummary: (summary: string, docTitle: string) => void;
  onOpenTaxonomyModal?: (value: any, definition: string, taxonomyName: string) => void;
  onOpenToc: (doc: any) => void;
  onOpenMetadata: (doc: any) => void;
  onOpenTimeline: (doc: any) => void;
  onOpenLogs: (doc: any) => void;
  onViewChunks: (doc: any) => void;
  onReprocess: (doc: any) => void;
  onOpenQueue: () => void;
  reprocessingDocId: string | null;
  dataSourceConfig?: import('../../App').DataSourceConfigItem;
  dataSource?: string;
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
  reprocessingDocId,
  dataSourceConfig,
  dataSource = 'uneg',
}) => {
    const lastUpdated = formatTimestamp(getLastUpdatedTimestamp(doc.stages || {}));

    // Get taxonomy configurations
    const taxonomies = dataSourceConfig?.pipeline?.tag?.taxonomies || {};

    // Check if document has reached parsed status or later
    // Show thumbnail for any document that has been successfully parsed (exclude 'downloaded' and error states)
    const hasParsedStatus = doc.status && doc.status !== 'downloaded' && !doc.status.includes('error');

    // Construct thumbnail URL (only for parsed or later documents)
    const thumbnailUrl = hasParsedStatus ? getThumbnailUrl(doc, dataSource) : null;

    return (
      <tr key={doc.id || index}>
        <td className="doc-title">
          {hasParsedStatus ? (
            <div className="doc-title-with-thumbnail">
              <div className="doc-title-thumbnail-container">
                {thumbnailUrl ? (
                  <>
                    <img
                      src={thumbnailUrl}
                      alt={doc.title || 'Document thumbnail'}
                      className="doc-title-thumbnail"
                      onError={(e) => {
                        const target = e.target as HTMLImageElement;
                        target.style.display = 'none';
                        const placeholder = target.nextElementSibling as HTMLElement;
                        if (placeholder) {
                          placeholder.style.display = 'flex';
                        }
                      }}
                    />
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
          ) : (
            <div>{doc.title || 'Untitled'}</div>
          )}
        </td>
        <DocumentLinksCell doc={doc} />
        <td className="doc-summary">
          <DocumentsSummaryCell
            summary={doc.full_summary}
            docTitle={doc.title || 'Untitled'}
            onOpenSummary={onOpenSummary}
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
            onOpenTaxonomyModal={onOpenTaxonomyModal}
          />
        ))}
        <DocumentFormatCell fileFormat={doc.file_format} />
        <td>{doc.page_count || '-'}</td>
        <td>{doc.file_size_mb || '-'}</td>
        <DocumentErrorCell doc={doc} />
        <td>{lastUpdated || '-'}</td>
        <DocumentChunksCell doc={doc} onViewChunks={onViewChunks} />
        <DocumentActionsCell
          doc={doc}
          reprocessingDocId={reprocessingDocId}
          onReprocess={onReprocess}
          onOpenQueue={onOpenQueue}
        />
      </tr>
    );
  };
