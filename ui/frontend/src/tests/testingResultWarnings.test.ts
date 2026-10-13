import { resultWarnings } from '../components/admin/testing/resultWarnings';

describe('resultWarnings', () => {
  it('returns the string warnings stored on a case output', () => {
    expect(resultWarnings({ summary: 'x', warnings: ['Reranker unavailable', ''] })).toEqual([
      'Reranker unavailable',
    ]);
  });

  it('is empty when the output has no warnings or is not an object', () => {
    expect(resultWarnings({ summary: 'x' })).toEqual([]);
    expect(resultWarnings({ warnings: 'not a list' })).toEqual([]);
    expect(resultWarnings(null)).toEqual([]);
    expect(resultWarnings(undefined)).toEqual([]);
  });
});
