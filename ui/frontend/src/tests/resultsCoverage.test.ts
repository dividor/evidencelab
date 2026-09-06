import { buildResultsCoverageText } from '../utils/resultsCoverage';

describe('buildResultsCoverageText', () => {
  it('states excerpt and document counts for the single-organization case', () => {
    const text = buildResultsCoverageText({
      excerptCount: 50,
      documentCount: 28,
      orgCount: 1,
    });
    expect(text).toContain('50 most relevant text excerpts');
    expect(text).toContain('28 documents');
    // A single org reads awkwardly, so the org clause is omitted.
    expect(text).not.toContain('organization');
    expect(text).toContain('Refine your search query');
  });

  it('includes the organization clause when results span multiple orgs', () => {
    const text = buildResultsCoverageText({
      excerptCount: 42,
      documentCount: 30,
      orgCount: 4,
    });
    expect(text).toContain('30 documents across 4 organizations');
  });

  it('pluralizes correctly for singular counts', () => {
    const text = buildResultsCoverageText({
      excerptCount: 1,
      documentCount: 1,
      orgCount: 1,
    });
    expect(text).toContain('1 most relevant text excerpt ');
    expect(text).toContain('1 document.');
    expect(text).not.toContain('1 documents');
  });

  it('does not hardcode any page-size number', () => {
    const text = buildResultsCoverageText({
      excerptCount: 500,
      documentCount: 120,
      orgCount: 3,
    });
    expect(text).toContain('500 most relevant text excerpts');
    expect(text).toContain('120 documents across 3 organizations');
  });
});
