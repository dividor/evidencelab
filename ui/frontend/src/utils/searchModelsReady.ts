export interface SearchModelsState {
  combosLoading: boolean;
  comboCount: number;
  searchModel: string | null;
  summaryModelConfig: unknown;
  semanticHighlightModelConfig: unknown;
}

/**
 * True once a search can name its models: the model combos have loaded and,
 * when there are any, the selected combo has been applied. A search sent
 * before then goes out without an embedding model or a reranker.
 */
export const areSearchModelsReady = (state: SearchModelsState): boolean =>
  !state.combosLoading
  && (
    state.comboCount === 0
    || Boolean(
      state.searchModel && state.summaryModelConfig && state.semanticHighlightModelConfig
    )
  );
