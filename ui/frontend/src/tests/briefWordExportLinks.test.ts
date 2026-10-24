import JSZip from 'jszip';
import { Packer } from 'docx';
import { briefWordExportOptions } from '../components/brief/BriefTab';
import { buildExportDocument } from '../utils/exportResultsToDocx';
import type { SearchResult } from '../types/api';

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: true,
  APP_BASE_PATH: '',
}));

const REPORT = 'https://docs.wfp.org/api/documents/WFP-1/download/';
const RESULT = {
  chunk_id: 'c1',
  doc_id: 'd1',
  text: 'An excerpt.',
  page_num: 26,
  headings: [],
  score: 0.9,
  title: 'School feeding in Kenya',
  report_url: REPORT,
} as unknown as SearchResult;

const brief = (wordLinkTarget: 'source' | 'evidence_lab') => ({
  briefTitle: 'School feeding',
  referenceGrouping: 'passage' as const,
  wordLinkTarget,
});

const linkTargets = async (opts: ReturnType<typeof briefWordExportOptions>): Promise<string> => {
  const doc = buildExportDocument({ ...opts, siteOrigin: 'https://lab.example.org', now: () => new Date('2026-10-07T00:00:00Z') });
  const zip = await JSZip.loadAsync(await Packer.toBuffer(doc));
  return zip.file('word/_rels/document.xml.rels')!.async('string');
};

describe("the brief's Word export follows the chosen link target", () => {
  test('passes the choice and the API base to the export', () => {
    const opts = briefWordExportOptions(brief('evidence_lab'), 'Text [1].', [RESULT], 'wfp');
    expect(opts.linkTarget).toBe('evidence_lab');
    expect(opts.apiBaseUrl).toBe('/api');
    expect(briefWordExportOptions(brief('source'), 'Text [1].', [RESULT], 'wfp').linkTarget).toBe('source');
  });

  test('source links open the source document at the cited page', async () => {
    const rels = await linkTargets(briefWordExportOptions(brief('source'), 'Text [1].', [RESULT], 'wfp'));
    expect(rels).toContain(`Target="${REPORT}#page=26"`);
    expect(rels).not.toContain('/api/pdf/d1');
  });

  test('Evidence Lab links open its copy at the cited page', async () => {
    const rels = await linkTargets(briefWordExportOptions(brief('evidence_lab'), 'Text [1].', [RESULT], 'wfp'));
    expect(rels).toContain('Target="https://lab.example.org/api/pdf/d1?data_source=wfp#page=26"');
    expect(rels).not.toContain(REPORT);
  });
});
