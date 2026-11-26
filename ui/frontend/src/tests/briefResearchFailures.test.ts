import {
  readResearchFailures,
  researchFailureSnapshot,
  storeResearchFailures,
} from '../components/brief/briefResearchFailures';
import type { BriefSection } from '../components/brief/briefTypes';

const section: BriefSection = {
  id: 'education',
  title: 'Education',
  level: 1,
  status: 'done',
  progress: 100,
  content: 'The previous draft.',
  sources: [],
  activity: [],
  currentRunId: 'run-1',
};

describe('Brief research failure status', () => {
  beforeEach(() => sessionStorage.clear());

  test('stores the reason and previous version for failed sections in the same brief', () => {
    const researchFailure = { mode: 'generate' as const, message: 'The stream ended early.' };
    const snapshot = researchFailureSnapshot([
      { ...section, researchFailure },
      { ...section, id: 'nutrition' },
    ]);
    storeResearchFailures('brief-one', snapshot);

    expect([...readResearchFailures('brief-one')]).toEqual([
      ['education', { ...researchFailure, currentRunId: 'run-1' }],
    ]);
    expect(readResearchFailures('brief-two').size).toBe(0);
  });

  test('clears the saved failure after the section succeeds', () => {
    storeResearchFailures('brief-one', researchFailureSnapshot([
      { ...section, researchFailure: { mode: 'update', message: 'Saving failed.' } },
    ]));
    expect(readResearchFailures('brief-one').size).toBe(1);

    storeResearchFailures('brief-one', researchFailureSnapshot([section]));
    expect(readResearchFailures('brief-one').size).toBe(0);
  });
});
