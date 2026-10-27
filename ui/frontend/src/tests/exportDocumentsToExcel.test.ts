import { saveAs } from 'file-saver';
import {
  exportDocumentsToExcel,
  EXCEL_MAX_CELL_LENGTH,
  buildDocumentRow,
  buildDocumentsSheet,
  buildExportFilename,
  buildHeaderRow,
  cellValue,
  metadataJson,
  taxonomyColumnsFromConfig,
  truncateCell,
} from '../utils/exportDocumentsToExcel';

jest.mock('file-saver', () => ({ saveAs: jest.fn() }));

const TAXONOMIES = [{ key: 'sdg', label: 'SDG' }];
const FIXED_DATE = '2026-10-08T12:00:00Z';

const doc = (overrides: Record<string, any> = {}) => ({
  title: 'Evaluation of X',
  organization: 'UNDP',
  status: 'indexed',
  document_type: 'Evaluation',
  published_year: '2024',
  language: 'en',
  report_url: 'https://example.org/report',
  pdf_url: 'https://example.org/report.pdf',
  full_summary: '## Summary\n\nA long summary.',
  toc: '[H1] Introduction\n[H2] Scope',
  taxonomies: {
    sdg: [{ code: 'sdg3', name: 'SDG3 - Good Health', reason: 'Health outcomes' }],
  },
  file_format: 'pdf',
  page_count: 42,
  file_size_mb: 1.2,
  error_message: null,
  last_updated: '2026-03-16',
  ocr_applied: false,
  stages: { tag: { at: '2026-03-16', success: true } },
  ...overrides,
});

const headerIndex = (name: string) => buildHeaderRow(TAXONOMIES).indexOf(name);

describe('cellValue', () => {
  it('writes strings as they are, so summaries stay readable', () => {
    expect(cellValue('## Summary\n\ntext')).toBe('## Summary\n\ntext');
  });

  it('writes structured values as formatted JSON', () => {
    expect(cellValue([{ code: 'sdg3' }])).toBe(JSON.stringify([{ code: 'sdg3' }], null, 2));
  });

  it('writes nothing for null and undefined', () => {
    expect(cellValue(null)).toBe('');
    expect(cellValue(undefined)).toBe('');
  });

  it('keeps numbers and booleans', () => {
    expect(cellValue(42)).toBe('42');
    expect(cellValue(false)).toBe('false');
  });

  it('truncates a cell Excel would refuse to open', () => {
    const long = 'x'.repeat(EXCEL_MAX_CELL_LENGTH + 500);
    const written = cellValue(long);
    expect(written.length).toBe(EXCEL_MAX_CELL_LENGTH);
    expect(written.endsWith('...')).toBe(true);
  });

  it('truncateCell leaves a short cell alone', () => {
    expect(truncateCell('short')).toBe('short');
  });
});

describe('the exported columns', () => {
  it('has no column for chunks, status logs or the timeline', () => {
    const header = buildHeaderRow(TAXONOMIES).join(' ').toLowerCase();
    expect(header).not.toContain('chunk');
    expect(header).not.toContain('log');
    expect(header).not.toContain('timeline');
  });

  it('gives every configured taxonomy its own column, labelled as the table labels it', () => {
    const columns = taxonomyColumnsFromConfig({
      pipeline: { tag: { taxonomies: { sdg: { name: 'SDG' }, theme: {} } } },
    } as any);
    expect(columns).toEqual([
      { key: 'sdg', label: 'SDG' },
      { key: 'theme', label: 'theme' },
    ]);
    expect(buildHeaderRow(columns)).toContain('SDG');
    expect(buildHeaderRow(columns)).toContain('theme');
  });
});

describe('buildDocumentRow', () => {
  it('writes the whole summary, not the table preview', () => {
    const row = buildDocumentRow(doc(), TAXONOMIES);
    expect(row[headerIndex('Summary')]).toBe('## Summary\n\nA long summary.');
  });

  it('writes the contents behind the Contents link', () => {
    const row = buildDocumentRow(doc(), TAXONOMIES);
    expect(row[headerIndex('Contents')]).toContain('[H1] Introduction');
  });

  it('expands AI tags as JSON, keeping the model\'s reason', () => {
    const row = buildDocumentRow(doc(), TAXONOMIES);
    const parsed = JSON.parse(row[headerIndex('SDG')]);
    expect(parsed).toEqual([
      { code: 'sdg3', name: 'SDG3 - Good Health', reason: 'Health outcomes' },
    ]);
  });

  it('leaves a taxonomy cell empty when the document has no tags', () => {
    const row = buildDocumentRow(doc({ taxonomies: {} }), TAXONOMIES);
    expect(row[headerIndex('SDG')]).toBe('');
  });

  it('falls back to the sys_ fields for error and last updated', () => {
    const row = buildDocumentRow(
      doc({ error_message: null, last_updated: null, sys_error_message: 'boom', sys_last_updated: '2026-01-01' }),
      TAXONOMIES,
    );
    expect(row[headerIndex('Error')]).toBe('boom');
    expect(row[headerIndex('Last updated')]).toBe('2026-01-01');
  });
});

describe('the Metadata column', () => {
  it('is the document record as JSON', () => {
    const parsed = JSON.parse(metadataJson(doc()));
    expect(parsed.title).toBe('Evaluation of X');
    expect(parsed.organization).toBe('UNDP');
  });

  it('leaves out the status logs and timeline', () => {
    const parsed = JSON.parse(metadataJson(doc()));
    expect(parsed.stages).toBeUndefined();
  });

  it('leaves out chunks', () => {
    const parsed = JSON.parse(metadataJson(doc({ chunks: [{ id: 'c1' }] })));
    expect(parsed.chunks).toBeUndefined();
  });
});

describe('buildDocumentsSheet', () => {
  it('writes a header plus one row per document on the page', () => {
    const rows = buildDocumentsSheet([doc(), doc({ title: 'Second' })], TAXONOMIES);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toEqual(buildHeaderRow(TAXONOMIES));
    expect(rows[2][0]).toBe('Second');
  });

  it('exports exactly the rows it is given, so the page size decides the size', () => {
    const page = Array.from({ length: 50 }, (_, i) => doc({ title: `Doc ${i}` }));
    expect(buildDocumentsSheet(page, TAXONOMIES)).toHaveLength(51);
  });

  it('writes just a header when the page is empty', () => {
    expect(buildDocumentsSheet([], TAXONOMIES)).toHaveLength(1);
  });
});

describe('buildExportFilename', () => {
  it('names the file after the data source and the date', () => {
    expect(buildExportFilename('uneg', new Date(FIXED_DATE)))
      .toBe('evidence-lab-documents-uneg-2026-10-08.xlsx');
  });

  it('keeps the filename safe when the data source has spaces', () => {
    expect(buildExportFilename('UN Humanitarian Reports', new Date(FIXED_DATE)))
      .toBe('evidence-lab-documents-UN-Humanitarian-Reports-2026-10-08.xlsx');
  });

  it('falls back when no data source is given', () => {
    expect(buildExportFilename(undefined, new Date(FIXED_DATE)))
      .toBe('evidence-lab-documents-documents-2026-10-08.xlsx');
  });
});

describe('exportDocumentsToExcel', () => {
  beforeEach(() => (saveAs as unknown as jest.Mock).mockClear());

  it('hands the browser a non-empty workbook named for the data source', () => {
    exportDocumentsToExcel([doc()], TAXONOMIES, 'uneg');

    expect(saveAs).toHaveBeenCalledTimes(1);
    const [blob, filename] = (saveAs as unknown as jest.Mock).mock.calls[0];
    expect(filename).toMatch(/^evidence-lab-documents-uneg-\d{4}-\d{2}-\d{2}\.xlsx$/);
    expect(blob.size).toBeGreaterThan(0);
  });

  it('still produces a workbook when the page is empty', () => {
    exportDocumentsToExcel([], TAXONOMIES, 'uneg');
    expect(saveAs).toHaveBeenCalledTimes(1);
  });
});
