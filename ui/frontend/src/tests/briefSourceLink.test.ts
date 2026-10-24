import { sourceToResult } from '../components/brief/BriefTab';
import { resolveResultLink, type DocLinks } from '../utils/exportResultsToDocx';
import type { SourceReference } from '../types/api';

// Regression: brief citation/footnote links must point at the document's public
// URL (Report URL) by default, not Evidence Lab. The URL travels on the source
// as `reportUrl`/`pdfUrl` from the assistant stream.
const SITE: DocLinks = { siteOrigin: 'http://localhost:3000', target: 'source', apiBase: '/api' };
const WFP_URL = 'https://docs.wfp.org/api/documents/WFP-0000139144/download/';

const source = (over: Partial<SourceReference>): SourceReference => ({
  chunkId: 'c1',
  docId: 'd1',
  title: 'Some Evaluation',
  text: 'excerpt',
  score: 0.5,
  page: 12,
  index: 1,
  ...over,
});

describe('brief source → export link resolution', () => {
  test('a source with reportUrl links to the Report URL at the cited page', () => {
    const r = sourceToResult(source({ reportUrl: WFP_URL }), 'wfp');
    expect(resolveResultLink(r, SITE, 'wfp')).toBe(`${WFP_URL}#page=12`);
  });

  test('falls back to pdfUrl when a source has no reportUrl', () => {
    const r = sourceToResult(source({ pdfUrl: WFP_URL }), 'wfp');
    expect(resolveResultLink(r, SITE, 'wfp')).toBe(`${WFP_URL}#page=12`);
  });

  test('only a source that carries no URL falls back to its copy in Evidence Lab', () => {
    const r = sourceToResult(source({}), 'wfp');
    // This happens only when the source itself has neither reportUrl nor pdfUrl
    // (e.g. researched before the backend began enriching sources with links).
    expect(resolveResultLink(r, SITE, 'wfp')).toBe('http://localhost:3000/api/pdf/d1?data_source=wfp#page=12');
  });

  test('with the Evidence Lab target, a source with a Report URL links to Evidence Lab', () => {
    const r = sourceToResult(source({ reportUrl: WFP_URL }), 'wfp');
    expect(resolveResultLink(r, { ...SITE, target: 'evidence_lab' }, 'wfp')).toBe(
      'http://localhost:3000/api/pdf/d1?data_source=wfp#page=12',
    );
  });
});
