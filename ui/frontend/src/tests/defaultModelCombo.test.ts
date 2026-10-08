import { resolveDefaultModelCombo } from '../utils/defaultModelCombo';
import { ModelComboConfig } from '../types/api';

const combo = (overrides: Partial<ModelComboConfig> = {}): ModelComboConfig => ({
  embedding_model: 'e5_large',
  summarization_model: {} as ModelComboConfig['summarization_model'],
  semantic_highlighting_model: {} as ModelComboConfig['semantic_highlighting_model'],
  reranker_model: 'none',
  ...overrides,
});

describe('resolveDefaultModelCombo', () => {
  it('starts on the combo flagged default in config.json', () => {
    const combos = {
      Azure: combo(),
      Huggingface: combo(),
      Vertex: combo({ default: true }),
    };
    expect(resolveDefaultModelCombo(Object.keys(combos), combos)).toBe('Vertex');
  });

  it('falls back to the first combo when none is flagged', () => {
    const combos = { Azure: combo(), Vertex: combo() };
    expect(resolveDefaultModelCombo(Object.keys(combos), combos)).toBe('Azure');
  });

  it('ignores a flagged combo this datasource does not offer', () => {
    // The API filters combos to those whose embedding model is indexed for
    // the datasource, so the flagged one can legitimately be missing.
    const combos = { Azure: combo(), Vertex: combo({ default: true }) };
    expect(resolveDefaultModelCombo(['Azure'], combos)).toBe('Azure');
  });

  it('uses the first flagged combo when several are flagged', () => {
    const combos = {
      Azure: combo({ default: true }),
      Vertex: combo({ default: true }),
    };
    expect(resolveDefaultModelCombo(Object.keys(combos), combos)).toBe('Azure');
  });

  it('treats a non-true default as not flagged', () => {
    const combos = {
      Azure: combo(),
      Vertex: combo({ default: false }),
    };
    expect(resolveDefaultModelCombo(Object.keys(combos), combos)).toBe('Azure');
  });

  it('returns an empty string when there are no combos', () => {
    expect(resolveDefaultModelCombo([], {})).toBe('');
  });

  it('falls back to the first combo when the config is missing', () => {
    expect(resolveDefaultModelCombo(['Azure', 'Vertex'])).toBe('Azure');
  });
});
