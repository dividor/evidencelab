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
});
