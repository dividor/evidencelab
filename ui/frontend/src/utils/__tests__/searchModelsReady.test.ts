/**
 * A search pressed while the page was still loading went out with no
 * embedding model and no reranker, so the API chose its own. These tests pin
 * when a search may be sent.
 */
import { areSearchModelsReady, SearchModelsState } from '../searchModelsReady';

const applied: SearchModelsState = {
  combosLoading: false,
  comboCount: 3,
  searchModel: 'azure_small',
  summaryModelConfig: { model: 'gpt-4.1-mini' },
  semanticHighlightModelConfig: { model: 'gpt-4.1-mini' },
};

describe('areSearchModelsReady', () => {
  test('is false while the model combos are loading', () => {
    expect(areSearchModelsReady({ ...applied, combosLoading: true })).toBe(false);
  });

  test('is false when combos have loaded but none has been applied yet', () => {
    expect(
      areSearchModelsReady({
        ...applied,
        searchModel: null,
        summaryModelConfig: null,
        semanticHighlightModelConfig: null,
      })
    ).toBe(false);
  });

  test('is false until every model from the combo is set', () => {
    expect(areSearchModelsReady({ ...applied, semanticHighlightModelConfig: null })).toBe(false);
  });

  test('is true once the selected combo has been applied', () => {
    expect(areSearchModelsReady(applied)).toBe(true);
  });

  test('is true when the data source has no model combos', () => {
    expect(
      areSearchModelsReady({
        combosLoading: false,
        comboCount: 0,
        searchModel: null,
        summaryModelConfig: null,
        semanticHighlightModelConfig: null,
      })
    ).toBe(true);
  });
});
