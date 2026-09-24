import { buildGlobalCitations, stripLeadingTitle } from '../components/brief/briefCitations';
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

    // One number per cited passage (as the AI summary numbers its sources), so
    // Doc One's two pages are [1] and [4], not one combined number.
    expect(refs.map((r) => r.n)).toEqual([1, 2, 3, 4]);
    expect(refs.map((r) => r.title)).toEqual([
      'Doc One',
      'Doc Two',
      'Doc Three',
      'Doc One',
    ]);
    expect(refs.map((r) => r.page)).toEqual([5, 3, 1, 9]);

    // Section A keeps 1, 2.
    expect(display.get('a')?.content).toBe('Intro [1] and more [2].');
    // Section B: local [7] → [3]; local [21] is a different passage of Doc One
    // (p.9, not p.5) so it gets its own number rather than reusing [1].
    expect(display.get('b')?.content).toBe('New finding [3] and a repeat of doc one [4].');
  });

  test('keeps separate numbers for different passages of one document', () => {
    const sections: BriefSection[] = [
      section({
        id: 'a',
        content: 'Claim [3, 4].',
        sources: [
          // Two passages of the same document, on different pages: each keeps
          // its own number so the reader can tell which page backs the claim.
          src({ index: 3, docId: 'dX', title: 'Same Doc', page: 2 }),
          src({ index: 4, docId: 'dX', title: 'Same Doc', page: 8 }),
        ],
      }),
    ];

    const { refs, display } = buildGlobalCitations(sections);

    expect(refs).toHaveLength(2);
    expect(refs.map((r) => r.page)).toEqual([2, 8]);
    expect(display.get('a')?.content).toBe('Claim [1, 2].');
  });

  test('one number per passage, shared by chunks of the same page', () => {
    const sections: BriefSection[] = [
      section({
        id: 'a',
        content: 'Claim [1] and [2].',
        sources: [
          src({ index: 1, chunkId: 'same-chunk', docId: 'dY', title: 'Doc', page: 4 }),
          src({ index: 2, chunkId: 'same-chunk', docId: 'dY', title: 'Doc', page: 4 }),
        ],
      }),
    ];

    const { refs, display } = buildGlobalCitations(sections);

    expect(refs).toHaveLength(1);
    expect(display.get('a')?.content).toBe('Claim [1] and [1].');
  });

  test('ignores sections that are not done', () => {
    const sections: BriefSection[] = [
      section({ id: 'a', status: 'researching', content: 'pending [1].' }),
    ];
    const { refs, display } = buildGlobalCitations(sections);
    expect(refs).toHaveLength(0);
    expect(display.size).toBe(0);
  });

  test('drops a leading title the model repeated at the top of the section', () => {
    const sections: BriefSection[] = [
      section({
        id: 'a',
        title: 'Access to schooling',
        content: '## Access to schooling\n\nEnrolment rose [1].',
        sources: [src({ index: 1, docId: 'd1', title: 'Doc', page: 2 })],
      }),
    ];
    const { display } = buildGlobalCitations(sections);
    // The duplicated heading is removed; only the prose (renumbered) remains.
    expect(display.get('a')?.content).toBe('Enrolment rose [1].');
  });
});

describe('stripLeadingTitle', () => {
  test('strips a leading markdown heading', () => {
    expect(stripLeadingTitle('## Access\n\nBody text.', 'Access')).toBe('Body text.');
    expect(stripLeadingTitle('# Anything\n\nBody.', 'Different')).toBe('Body.');
  });

  test('strips a leading plain or bold line that repeats the title', () => {
    expect(stripLeadingTitle('Access to schooling\n\nBody.', 'Access to schooling')).toBe('Body.');
    expect(stripLeadingTitle('**Access to schooling**\nBody.', 'Access to schooling')).toBe('Body.');
  });

  test('leaves prose that does not start with a title untouched', () => {
    expect(stripLeadingTitle('Kenya has improved enrolment.', 'Access')).toBe(
      'Kenya has improved enrolment.',
    );
  });
});

describe('footnotes react to citation changes', () => {
  test('removing an inline citation drops its footnote and renumbers the rest', () => {
    const sources = [
      src({ index: 1, docId: 'd1', title: 'Doc One', page: 1 }),
      src({ index: 2, docId: 'd2', title: 'Doc Two', page: 2 }),
    ];
    const before: BriefSection[] = [
      section({ id: 'a', content: 'First [1] and second [2].', sources }),
    ];
    const after: BriefSection[] = [
      // An AI edit removed the sentence citing [1]; sources are unchanged.
      section({ id: 'a', content: 'Only the second remains [2].', sources }),
    ];

    expect(buildGlobalCitations(before).refs.map((r) => r.title)).toEqual([
      'Doc One',
      'Doc Two',
    ]);

    const { refs, display } = buildGlobalCitations(after);
    expect(refs.map((r) => r.title)).toEqual(['Doc Two']);
    expect(refs[0].n).toBe(1);
    // The surviving citation is renumbered to the new global sequence.
    expect(display.get('a')?.content).toBe('Only the second remains [1].');
  });

  test('a section mid-revise keeps its citations in the numbering', () => {
    const sections: BriefSection[] = [
      section({
        id: 'a',
        status: 'researching',
        revising: true,
        content: 'Still on screen [1].',
        sources: [src({ index: 1, docId: 'd1', title: 'Doc One', page: 1 })],
      }),
    ];
    const { refs, display } = buildGlobalCitations(sections);
    expect(refs.map((r) => r.title)).toEqual(['Doc One']);
    expect(display.get('a')?.content).toBe('Still on screen [1].');
  });
});

describe('buildGlobalCitations with single-per-document grouping', () => {
  // Doc One is cited from three pages, Doc Two and Doc Three once each.
  const sections: BriefSection[] = [
    section({
      id: 'a',
      content: 'A fact happened. [1][3] Then something else [2][4][5]',
      sources: [
        src({ index: 1, docId: 'doc1', title: 'Doc One', page: 10 }),
        src({ index: 2, docId: 'doc2', title: 'Doc Two', page: 4 }),
        src({ index: 3, docId: 'doc1', title: 'Doc One', page: 20 }),
        src({ index: 4, docId: 'doc3', title: 'Doc Three', page: 7 }),
        src({ index: 5, docId: 'doc1', title: 'Doc One', page: 30 }),
      ],
    }),
  ];

  test('per passage (default): one number per page, references carry pages', () => {
    const { refs, display } = buildGlobalCitations(sections, 'passage');
    expect(refs.map((r) => [r.n, r.title, r.page])).toEqual([
      [1, 'Doc One', 10],
      [2, 'Doc Two', 4],
      [3, 'Doc One', 20],
      [4, 'Doc Three', 7],
      [5, 'Doc One', 30],
    ]);
    expect(display.get('a')?.content).toBe(
      'A fact happened. [1][3] Then something else [2][4][5]',
    );
  });

  test('per document: one number per document, no pages, prose renumbered', () => {
    const { refs, display } = buildGlobalCitations(sections, 'document-single');
    expect(refs.map((r) => [r.n, r.title, r.page])).toEqual([
      [1, 'Doc One', undefined],
      [2, 'Doc Two', undefined],
      [3, 'Doc Three', undefined],
    ]);
    // [1][3] were both Doc One, so they collapse to a single [1]; [5] is
    // Doc One again and keeps that number.
    expect(display.get('a')?.content).toBe('A fact happened. [1] Then something else [2][3][1]');
  });

  test('per document: the reference opens the first cited passage of the document', () => {
    const { refs } = buildGlobalCitations(sections, 'document-single');
    expect(refs[0].source.page).toBe(10);
    expect(refs[0].source.docId).toBe('doc1');
  });

  test('per document: the other passages ride along as variants of the display source', () => {
    const { display } = buildGlobalCitations(sections, 'document-single');
    const sources = display.get('a')!.sources;
    expect(sources.map((x) => x.index)).toEqual([1, 2, 3]);
    const docOne = sources.find((x) => x.index === 1)!;
    expect(docOne.page).toBe(10);
    expect((docOne.variants || []).map((v) => v.page)).toEqual([20, 30]);
    // Single-passage documents carry no variants.
    expect(sources.find((x) => x.index === 2)!.variants).toBeUndefined();
  });

  test('per document: one number for a document cited across sections', () => {
    const two: BriefSection[] = [
      section({
        id: 'a',
        content: 'First [1].',
        sources: [src({ index: 1, docId: 'doc1', title: 'Doc One', page: 1 })],
      }),
      section({
        id: 'b',
        content: 'Second [7] and [8].',
        sources: [
          src({ index: 7, docId: 'doc2', title: 'Doc Two', page: 2 }),
          src({ index: 8, docId: 'doc1', title: 'Doc One', page: 9 }),
        ],
      }),
    ];
    const { refs, display } = buildGlobalCitations(two, 'document-single');
    expect(refs.map((r) => r.title)).toEqual(['Doc One', 'Doc Two']);
    expect(display.get('b')?.content).toBe('Second [2] and [1].');
  });

  test('per document: a combined marker citing one document twice reads once', () => {
    const one: BriefSection[] = [
      section({
        id: 'a',
        content: 'Claim [1, 2].',
        sources: [
          src({ index: 1, docId: 'doc1', title: 'Doc One', page: 1 }),
          src({ index: 2, docId: 'doc1', title: 'Doc One', page: 5 }),
        ],
      }),
    ];
    expect(buildGlobalCitations(one, 'document-single').display.get('a')?.content).toBe(
      'Claim [1].',
    );
  });

  test('multiple-per-document grouping numbers exactly like per passage', () => {
    expect(buildGlobalCitations(sections, 'document-multiple')).toEqual(
      buildGlobalCitations(sections, 'passage'),
    );
  });
});
