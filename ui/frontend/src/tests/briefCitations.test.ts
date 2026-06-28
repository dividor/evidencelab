import { buildGlobalCitations } from '../components/brief/briefCitations';
import { BriefSection } from '../components/brief/briefTypes';
import { SourceReference } from '../types/api';

const src = (overrides: Partial<SourceReference>): SourceReference => ({
  chunkId: `c-${overrides.docId}-${overrides.index}`,
  docId: 'd?',
  title: 'Untitled',
  text: '',
  score: 0,
  ...overrides,
});

const section = (overrides: Partial<BriefSection>): BriefSection => ({
  id: 'sec',
  title: 'Section',
  level: 1,
  status: 'done',
  progress: 100,
  content: '',
  sources: [],
  activity: [],
  ...overrides,
});

describe('buildGlobalCitations', () => {
  test('renumbers later sections consecutively instead of keeping local numbers', () => {
    const sections: BriefSection[] = [
      section({
        id: 'a',
        content: 'Intro [1] and more [2].',
        sources: [
          src({ index: 1, docId: 'd1', title: 'Doc One', page: 5 }),
          src({ index: 2, docId: 'd2', title: 'Doc Two', page: 3 }),
        ],
      }),
      // Deep research for section B accumulated many sources, so its local
      // citation numbers are large (7, 21) — these must be renumbered to follow
      // section A, not rendered as-is.
      section({
        id: 'b',
        content: 'New finding [7] and a repeat of doc one [21].',
        sources: [
          src({ index: 7, docId: 'd3', title: 'Doc Three', page: 1 }),
          src({ index: 21, docId: 'd1', title: 'Doc One', page: 9 }),
        ],
      }),
    ];

    const { refs, display } = buildGlobalCitations(sections);

    // Three distinct documents → consecutive global numbers 1, 2, 3.
    expect(refs.map((r) => r.n)).toEqual([1, 2, 3]);
    expect(refs.map((r) => r.title)).toEqual(['Doc One', 'Doc Two', 'Doc Three']);

    // Section A keeps 1, 2.
    expect(display.get('a')?.content).toBe('Intro [1] and more [2].');
    // Section B: local [7] → global [3] (new doc, consecutive); local [21] → [1]
    // (same document as section A's [1], so combined to the same number).
    expect(display.get('b')?.content).toBe('New finding [3] and a repeat of doc one [1].');
  });

  test('combines multiple citations to the same document within a marker group', () => {
    const sections: BriefSection[] = [
      section({
        id: 'a',
        content: 'Claim [3, 4].',
        sources: [
          // Both local indices point at the same document → one global number.
          src({ index: 3, docId: 'dX', title: 'Same Doc', page: 2 }),
          src({ index: 4, docId: 'dX', title: 'Same Doc', page: 8 }),
        ],
      }),
    ];

    const { refs, display } = buildGlobalCitations(sections);

    expect(refs).toHaveLength(1);
    expect(display.get('a')?.content).toBe('Claim [1].');
  });

  test('ignores sections that are not done', () => {
    const sections: BriefSection[] = [
      section({ id: 'a', status: 'researching', content: 'pending [1].' }),
    ];
    const { refs, display } = buildGlobalCitations(sections);
    expect(refs).toHaveLength(0);
    expect(display.size).toBe(0);
  });
});
