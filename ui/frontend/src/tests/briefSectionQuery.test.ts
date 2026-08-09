import { buildOutlineContext, buildSectionQuery } from '../utils/briefStream';

describe('buildSectionQuery', () => {
  test('weaves the brief topic into a top-level section query', () => {
    const q = buildSectionQuery({ heading: 'Key findings', briefTopic: 'girls education in Kenya' });
    expect(q).toContain('"Key findings"');
    expect(q).toContain('on "girls education in Kenya"');
    expect(q).toContain('Search the document library');
  });

  test('scopes a sub-section to its parent so generated queries stay relevant', () => {
    const q = buildSectionQuery({
      heading: 'Enrolment trends',
      briefTopic: 'girls education in Kenya',
      parentTitle: 'Access to schooling',
    });
    expect(q).toContain('"Enrolment trends"');
    expect(q).toContain('parent section "Access to schooling"');
    expect(q).toContain('avoid repeating material that belongs in sibling sections');
  });

  test('includes brief-level guidance and per-section focus when provided', () => {
    const q = buildSectionQuery({
      heading: 'Recommendations',
      briefTopic: 'girls education in Kenya',
      briefInstructions: 'prioritise RCTs since 2018',
      context: 'emphasise rural areas',
    });
    expect(q).toContain('Overall brief guidance: prioritise RCTs since 2018');
    expect(q).toContain('Focus for this section: emphasise rural areas');
  });

  test('falls back to a generic instruction when no topic is set (manual brief)', () => {
    const q = buildSectionQuery({ heading: 'Background' });
    expect(q).toBe(
      'Write the "Background" section of an evidence brief. ' +
        'Search the document library for evidence relevant to this specific section ' +
        'and cite a source for every claim.',
    );
  });

  test('update mode preserves the draft, date-filters, and keeps citations', () => {
    const q = buildSectionQuery({
      heading: 'Impacts',
      briefTopic: 'girls education',
      mode: 'update',
      existingContent: 'Enrolment rose sharply [1].',
      instruction: 'prioritise enforcement',
      publishedAfterIso: '2023-05-01T00:00:00.000Z',
    });
    // Keeps/embeds the current draft.
    expect(q).toContain('Enrolment rose sharply [1].');
    expect(q).toContain('Preserve its wording, structure and citations');
    // Constrains the search to newer sources (date only).
    expect(q).toContain('PUBLISHED AFTER 2023-05-01');
    // Threads the optional instruction + demands sequential citations back.
    expect(q).toContain('prioritise enforcement');
    expect(q).toContain('sequential [n] citation markers');
  });

  test('update mode without a draft falls back to a normal generate query', () => {
    const q = buildSectionQuery({ heading: 'Impacts', mode: 'update' });
    expect(q).toContain('Write the "Impacts" section');
    expect(q).not.toContain('Preserve its wording');
  });
});

describe('buildOutlineContext', () => {
  const sections = [
    { id: 'a', title: 'Context and scope', level: 1 },
    { id: 'b', title: 'What the evidence shows', level: 1, content: '# What the evidence shows\n\nCash transfers improved food consumption [1].' },
    { id: 'c', title: 'Effectiveness', level: 1 },
    { id: 'c1', title: 'Cost efficiency', level: 2 },
    { id: 'c2', title: 'Outcomes', level: 2 },
  ];

  test('lists every heading and marks the one being written', () => {
    const ctx = buildOutlineContext(sections, 'a');
    expect(ctx).toContain('Context and scope ← the section you are writing');
    expect(ctx).toContain('- What the evidence shows');
    expect(ctx).toContain('  - Cost efficiency');
    expect(ctx).toContain('do NOT repeat or pre-empt material');
  });

  test('includes a gist of already-written sections without markdown or citation markers', () => {
    const ctx = buildOutlineContext(sections, 'a');
    expect(ctx).toContain('already written; covers: What the evidence shows Cash transfers improved food consumption');
    expect(ctx).not.toContain('[1]');
    expect(ctx).not.toContain('#');
  });

  test('tells a parent heading with sub-headings to stay high-level', () => {
    const ctx = buildOutlineContext(sections, 'c');
    expect(ctx).toContain('sub-sections (Cost efficiency; Outcomes)');
    expect(ctx).toContain('high-level introduction');
  });

  test('a sub-section or a section without children gets no high-level instruction', () => {
    expect(buildOutlineContext(sections, 'c1')).not.toContain('high-level introduction');
    expect(buildOutlineContext(sections, 'a')).not.toContain('high-level introduction');
  });

  test('returns empty for a single-section brief', () => {
    expect(buildOutlineContext([sections[0]], 'a')).toBe('');
  });
});

describe('buildSectionQuery with outline context', () => {
  test('appends the outline context to the generate query', () => {
    const q = buildSectionQuery({
      heading: 'Effectiveness',
      briefTopic: 'cash transfers',
      outlineContext: 'For context, the full outline of the brief is:\n- A\n- B',
    });
    expect(q).toContain('full outline of the brief');
    expect(q.indexOf('Write')).toBeLessThan(q.indexOf('full outline'));
  });
});
