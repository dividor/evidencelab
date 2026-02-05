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
}) => {
    const lastUpdated = formatTimestamp(getLastUpdatedTimestamp(doc.stages || {}));

    // Get taxonomy configurations
    const taxonomies = dataSourceConfig?.pipeline?.tag?.taxonomies || {};

    return (
      <tr key={doc.id || index}>
        <td className="doc-title">{doc.title || 'Untitled'}</td>
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
