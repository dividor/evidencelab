import JSZip from 'jszip';
import { Packer } from 'docx';
import { buildExportDocument } from '../utils/exportResultsToDocx';
import { DEFAULT_SITE_URL } from '../utils/deploymentText';
import type { SearchResult } from '../types/api';

const result: SearchResult = {
  chunk_id: 'a1', doc_id: 'A', text: 'Excerpt', page_num: 2, headings: [], score: 0.9,
  title: 'Alpha Report', organization: 'WFP', year: '2019', metadata: {},
};

const relsFor = async (opts: Partial<Parameters<typeof buildExportDocument>[0]>) => {
  const doc = buildExportDocument({
    now: () => new Date('2026-01-01T00:00:00Z'),
    query: 'q',
    aiSummary: 'Alpha says this [1].',
    results: [result],
    ...opts,
  });
  const zip = await JSZip.loadAsync(await Packer.toBuffer(doc));
  return zip.file('word/_rels/document.xml.rels')!.async('string');
};

describe('Word export deep links', () => {
  test('use the explicit site origin when one is given', async () => {
    const rels = await relsFor({ siteOrigin: 'https://lab.example.org' });
    expect(rels).toContain('https://lab.example.org/');
    expect(rels).not.toContain(DEFAULT_SITE_URL);
  });

  test('fall back to the deployment site URL, not a hard-coded host', async () => {
    const rels = await relsFor({});
    // No REACT_APP_SITE_URL in the test environment, so the reference deployment.
    expect(rels).toContain(`${DEFAULT_SITE_URL}/`);
  });
});
