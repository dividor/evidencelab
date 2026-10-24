import { runConfigHeadline, runConfigRows } from '../components/admin/testing/runConfig';

const base = {
  model_combo: 'Google Vertex',
  group_id: 'g1',
  group_name: 'OEV',
  embedding_model: 'emb',
  summary_model: 'gemini',
  judge_model: 'gemini',
  rerank_model: 'vertex-ai-ranker',
  max_rerank_candidates: null,
  rerank: true,
  dense_weight: 0.8,
  min_chunk_size: 100,
  section_types: 'findings,recommendations',
  summary_prompt: 'Be concise.',
  temperature: 0,
  max_results: 20,
  custom_flag: 'x',
};

describe('runConfigRows', () => {
  it('groups known keys into sections, formats values, and hides identifiers', () => {
    const rows = runConfigRows(base, null);
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));
    expect(byKey.model_combo.section).toBe('Models');
    expect(byKey.rerank.value).toBe('on');
    expect(byKey.max_rerank_candidates.value).toBe('all');
    expect(byKey.summary_prompt.value).toBe('group prompt (11 chars)');
    expect(byKey.custom_flag.section).toBe('Other');
    expect(byKey.group_id).toBeUndefined();
    expect(rows.every((r) => !r.changed)).toBe(true);
  });

  it('marks values that differ from the previous run', () => {
    const previous = { ...base, dense_weight: 0.5, rerank: false, group_name: undefined };
    const rows = runConfigRows(base, previous);
    const changed = rows.filter((r) => r.changed).map((r) => r.key).sort();
    expect(changed).toEqual(['dense_weight', 'group_name', 'rerank']);
  });

  it('returns nothing for runs that predate config tracking', () => {
    expect(runConfigRows(null, base)).toEqual([]);
    expect(runConfigRows(undefined, undefined)).toEqual([]);
  });
});

describe('runConfigHeadline', () => {
  it('summarises combo, group, summary model and reranker', () => {
    expect(runConfigHeadline(base)).toBe(
      'Google Vertex · group OEV · summary gemini · rerank vertex-ai-ranker (all)',
    );
    expect(runConfigHeadline({ ...base, rerank: false })).toBe(
      'Google Vertex · group OEV · summary gemini · no rerank',
    );
    expect(runConfigHeadline({ ...base, max_rerank_candidates: 10 })).toContain('(10)');
    expect(runConfigHeadline(null)).toBe('');
  });
});
