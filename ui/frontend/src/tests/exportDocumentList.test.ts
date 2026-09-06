import JSZip from 'jszip';
import { Packer } from 'docx';
import { buildExportDocument } from '../utils/exportResultsToDocx';
import type { SearchResult } from '../types/api';

const result = (chunkId: string, docId: string, title: string, score: number, year: string, extra: Partial<SearchResult> = {}): SearchResult => ({
  chunk_id: chunkId, doc_id: docId, text: `Excerpt ${chunkId}`, page_num: 4, headings: [], score, title, organization: 'WFP', year, metadata: {}, ...extra,
});

const ALPHA = 'Alpha Report';
const BRAVO = 'Bravo Review';
const ALPHA_PDF = 'https://docs.example.org/alpha.pdf';
const DOC_LIST = 'Document List';

const RESULTS = [
  result('a1', 'A', ALPHA, 0.5, '2019', { pdf_url: ALPHA_PDF }),
  result('a2', 'A', ALPHA, 0.5, '2019', { pdf_url: ALPHA_PDF }),
  result('b1', 'B', BRAVO, 0.9, '2024'),
];
const SUMMARY = 'Alpha says this [1] and again [2]. Bravo adds [3].';

const buildXml = async (opts: Parameters<typeof buildExportDocument>[0]) => {
  const doc = buildExportDocument({ now: () => new Date('2026-01-01T00:00:00Z'), siteOrigin: 'https://lab.example.org', ...opts });
  const buf = await Packer.toBuffer(doc);
  const zip = await JSZip.loadAsync(buf);
  return { xml: await zip.file('word/document.xml')!.async('string'), rels: await zip.file('word/_rels/document.xml.rels')!.async('string') };
};

const cellTexts = (xml: string): string[] =>
  Array.from(xml.matchAll(/<w:tc>.*?<\/w:tc>/gs)).map((m) => m[0].replace(/<[^>]+>/g, ''));

describe('Word export Document List', () => {
  test('is absent unless the export is in group-by-document mode', async () => {
    const { xml } = await buildXml({ query: 'q', aiSummary: SUMMARY, results: RESULTS });
    expect(xml).not.toContain(DOC_LIST);
  });

  test('lists each document once with source, year, citation count and an online link, in on-screen order', async () => {
    const { xml, rels } = await buildXml({ query: 'q', aiSummary: SUMMARY, results: RESULTS, documentList: { sortBy: 'relevance' } });
    expect(xml).toContain(DOC_LIST);
    const cells = cellTexts(xml);
    expect(cells.slice(0, 4)).toEqual(['Document', 'Source', 'Year', 'Citations']);
    // Alpha: two excerpts at 0.5 (cumulative 1.0) outranks Bravo's single 0.9
    expect(cells.slice(4, 12)).toEqual([ALPHA, 'WFP', '2019', '2', BRAVO, 'WFP', '2024', '1']);
    expect(rels).toContain(`Target="${ALPHA_PDF}"`);
    expect(rels).toContain('Target="https://lab.example.org/document/B"');
  });

  test('follows the publication-date order when asked', async () => {
    const { xml } = await buildXml({ query: 'q', aiSummary: SUMMARY, results: RESULTS, documentList: { sortBy: 'date' } });
    const cells = cellTexts(xml);
    expect(cells[4]).toBe(BRAVO);
    expect(cells[8]).toBe(ALPHA);
  });

  test('without an AI summary it still lists the documents under a References heading with zero citations', async () => {
    const { xml } = await buildXml({ query: 'q', results: RESULTS, documentList: { sortBy: 'relevance' } });
    expect(xml).toContain('References');
    expect(xml).toContain(DOC_LIST);
    expect(cellTexts(xml).slice(4, 8)).toEqual([ALPHA, 'WFP', '2019', '0']);
  });
});
