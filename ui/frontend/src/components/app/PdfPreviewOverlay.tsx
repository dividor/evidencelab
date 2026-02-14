import React from 'react';
import { SearchResult, SummaryModelConfig } from '../../types/api';
import { PDFViewer } from '../PDFViewer';

interface PdfPreviewOverlayProps {
  selectedDoc: SearchResult | null;
  query: string;
  dataSource: string;
  semanticHighlightModelConfig?: SummaryModelConfig | null;
  onClose: () => void;
  onOpenMetadata?: (metadata: Record<string, any>) => void;
  // Search settings
  searchDenseWeight: number;
  rerankEnabled: boolean;
  recencyBoostEnabled: boolean;
  recencyWeight: number;
  recencyScaleDays: number;
  sectionTypes: string[];
  keywordBoostShortQueries: boolean;
  minChunkSize: number;
  minScore: number;
  rerankModel: string | null;
  searchModel: string | null;
}

const buildInitialBBox = (selectedDoc: SearchResult) => {
  if (!selectedDoc.bbox) {
    return [];
  }

  return selectedDoc.bbox.map((item: any) => {
    if (Array.isArray(item) && item.length === 2) {
      return {
        page: item[0],
        bbox: { l: item[1][0], b: item[1][1], r: item[1][2], t: item[1][3] },
        text: selectedDoc.text || '',
        semanticMatches: selectedDoc.semanticMatches || [],
      };
    }

    return {
      page: selectedDoc.page_num,
      bbox: { l: item[0], b: item[1], r: item[2], t: item[3] },
      text: selectedDoc.text || '',
      semanticMatches: selectedDoc.semanticMatches || [],
    };
  });
};

export const PdfPreviewOverlay: React.FC<PdfPreviewOverlayProps> = ({
  selectedDoc,
  query,
  dataSource,
  semanticHighlightModelConfig,
  onClose,
  onOpenMetadata,
  searchDenseWeight,
  rerankEnabled,
  recencyBoostEnabled,
  recencyWeight,
  recencyScaleDays,
  sectionTypes,
  keywordBoostShortQueries,
  minChunkSize,
  minScore,
  rerankModel,
  searchModel,
}) => {
  if (!selectedDoc) {
    return null;
  }

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="preview-panel" onClick={(event) => event.stopPropagation()}>
        <PDFViewer
          docId={selectedDoc.doc_id}
          chunkId={selectedDoc.chunk_id}
          pageNum={selectedDoc.page_num}
          onClose={onClose}
          title={selectedDoc.title}
          searchQuery={query}
          metadata={{ ...selectedDoc, ...selectedDoc.metadata }}
          dataSource={dataSource}
          semanticHighlightModelConfig={semanticHighlightModelConfig}
          initialBBox={buildInitialBBox(selectedDoc)}
          onOpenMetadata={onOpenMetadata}
          searchDenseWeight={searchDenseWeight}
          rerankEnabled={rerankEnabled}
          recencyBoostEnabled={recencyBoostEnabled}
          recencyWeight={recencyWeight}
          recencyScaleDays={recencyScaleDays}
          sectionTypes={sectionTypes}
          keywordBoostShortQueries={keywordBoostShortQueries}
          minChunkSize={minChunkSize}
          minScore={minScore}
          rerankModel={rerankModel}
          searchModel={searchModel}
        />
      </div>
    </div>
  );
};
