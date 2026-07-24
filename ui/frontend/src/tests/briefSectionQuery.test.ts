import { buildSectionQuery } from '../utils/briefStream';

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
