import axios from 'axios';
import React, { useCallback, useState } from 'react';
import API_BASE_URL from '../../config';
import { MetadataModal } from '../documents/MetadataModal';
import TocModal from '../TocModal';
import TocValidatorTable from './TocValidatorTable';
import { docKey, useTocValidator } from './useTocValidator';

interface TocValidatorManagerProps {
  dataSource?: string;
  dataSourceConfig?: import('../../App').DataSourceConfigItem;
}

interface TocModalState {
  open: boolean;
  docId: string;
  toc: string;
  loading: boolean;
}

const EMPTY_TOC_STATE: TocModalState = {
  open: false,
  docId: '',
  toc: '',
  loading: false,
};

/**
 * Admin screen: list documents, validate that every section inside each
 * document's human-set main-body page range uses a section type that Search
 * includes by default, and open the metadata / contents views to verify or fix
 * a classification manually.
 */
export const TocValidatorManager: React.FC<TocValidatorManagerProps> = ({
  dataSource = '',
  dataSourceConfig,
}) => {
  const state = useTocValidator(dataSource);
  const [metadataDoc, setMetadataDoc] = useState<any>(null);
  const [tocState, setTocState] = useState<TocModalState>(EMPTY_TOC_STATE);

  const metadataPanelFields =
    dataSourceConfig?.metadata_panel_fields || dataSourceConfig?.filter_fields || {};

  const handleOpenMetadata = useCallback((doc: any) => setMetadataDoc(doc), []);

  const handleOpenToc = useCallback(
    async (doc: any) => {
      const docId = docKey(doc);
      const seeded = doc.toc_classified || doc.sys_toc_classified || doc.toc || '';
      setTocState({ open: true, docId, toc: seeded, loading: true });
      try {
        const response = await axios.get<any>(`${API_BASE_URL}/document/${docId}`, {
          params: { data_source: dataSource || undefined },
        });
        const data = response.data || {};
        setTocState({
          open: true,
          docId,
          toc: data.toc_classified || data.sys_toc_classified || seeded,
          loading: false,
        });
      } catch (err) {
        setTocState((prev) => ({ ...prev, loading: false }));
      }
    },
    [dataSource]
  );

  const closeToc = useCallback(() => setTocState(EMPTY_TOC_STATE), []);

  // Editing the classification changes the answer, so re-check the document.
  const handleTocUpdated = useCallback(
    (newToc: string) => {
      setTocState((prev) => ({ ...prev, toc: newToc }));
      if (tocState.docId) state.revalidate(tocState.docId);
    },
    [state, tocState.docId]
  );

  const pageIds = state.documents.map(docKey);
  const allOnPageSelected =
    pageIds.length > 0 && pageIds.every((id) => state.selectedIds.has(id));
  const selectedCount = state.selectedIds.size;
  // Map lookup keeps the table free of dynamic object indexing.
  const resultsByDocId = React.useMemo(
    () => new Map(Object.entries(state.results)),
    [state.results]
  );

  return (
    <div className="admin-section toc-validator">
      <p className="text-muted">
        Checks that every section inside each document&apos;s main-body page range
        (&ldquo;Introduction &ndash; before beginning of Annexes&rdquo;) is tagged with a
        section type that Search includes by default.
      </p>

      {state.error && <div className="auth-error">{state.error}</div>}

      <div className="admin-controls toc-validator-toolbar">
        <input
          type="text"
          className="admin-search-input"
          placeholder="Filter by title..."
          value={state.search}
          onChange={(event) => {
            state.setPage(1);
            state.setSearch(event.target.value);
          }}
        />
        <p className="text-muted" style={{ margin: 0 }}>
          {selectedCount} selected
        </p>
        <button
          className="btn-sm"
          onClick={state.selectAllMatching}
          disabled={state.loading || state.running}
        >
          Select all {state.total}
        </button>
        <button
          className="btn-sm"
          onClick={state.clearSelection}
          disabled={selectedCount === 0}
        >
          Clear
        </button>
        <button
          className="btn-sm btn-primary"
          style={{ marginLeft: 'auto' }}
          onClick={state.runValidation}
          disabled={selectedCount === 0 || state.running}
        >
          {state.running ? 'Validating…' : `Run validation (${selectedCount})`}
        </button>
      </div>

      {state.loading && <div className="admin-loading">Loading…</div>}

      <TocValidatorTable
        documents={state.documents}
        results={resultsByDocId}
        changedIds={state.changedIds}
        selectedIds={state.selectedIds}
        onToggle={state.toggle}
        onTogglePage={state.togglePage}
        allOnPageSelected={allOnPageSelected}
        onOpenMetadata={handleOpenMetadata}
        onOpenToc={handleOpenToc}
        columnFilters={state.columnFilters}
        activeFilterColumn={state.activeFilterColumn}
        filterPosition={state.filterPosition}
        onFilterClick={state.openFilter}
        onApplyFilter={state.applyFilter}
        onClearFilter={state.clearFilter}
        hasActiveFilter={state.hasActiveFilter}
        getCategoricalOptions={state.getCategoricalOptions}
        onCloseFilter={state.closeFilter}
      />

      <div className="toc-validator-pagination">
        <button
          className="btn-sm"
          onClick={() => state.setPage(Math.max(1, state.page - 1))}
          disabled={state.page <= 1}
        >
          Previous
        </button>
        <span className="text-muted">
          Page {state.page} of {state.totalPages}
        </span>
        <button
          className="btn-sm"
          onClick={() => state.setPage(Math.min(state.totalPages, state.page + 1))}
          disabled={state.page >= state.totalPages}
        >
          Next
        </button>
      </div>

      <MetadataModal
        isOpen={Boolean(metadataDoc)}
        onClose={() => setMetadataDoc(null)}
        metadataDoc={metadataDoc}
        metadataPanelFields={metadataPanelFields}
        onOpenToc={handleOpenToc}
      />

      <TocModal
        isOpen={tocState.open}
        onClose={closeToc}
        toc={tocState.toc}
        docId={tocState.docId}
        dataSource={dataSource}
        loading={tocState.loading}
        onTocUpdated={handleTocUpdated}
      />
    </div>
  );
};

export default TocValidatorManager;
