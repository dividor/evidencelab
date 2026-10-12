import * as XLSX from 'xlsx-js-style';
import { saveAs } from 'file-saver';

/**
 * Excel export of the Documents Library table.
 *
 * Exports the page currently on screen — the same rows, in the same order,
 * after sorting and filtering — so what you see is what you get. The page
 * size chosen in the table controls therefore decides how many rows are
 * exported.
 *
 * Three columns hold more than the table shows:
 *   - Summary is the whole AI summary, not the truncated preview.
 *   - Contents is the document's table of contents behind the "Contents" link.
 *   - Metadata is the full document record behind the "Metadata" link, as JSON.
 * Each AI tag taxonomy (SDG and any others configured) gets its own column
 * holding the full tag objects as JSON — code, name and the model's reason —
 * rather than the codes alone.
 *
 * Deliberately not exported: the status logs and processing timeline, and the
 * chunks, which are per-document detail rather than properties of the row.
 */

/** Excel refuses to open a file with a cell longer than this. */
export const EXCEL_MAX_CELL_LENGTH = 32767;

/** Document fields that are detail views, not row properties. */
const EXCLUDED_METADATA_KEYS = ['stages', 'sys_stages', 'chunks', 'sys_chunks'];

export interface TaxonomyColumn {
  key: string;
  label: string;
}

export const truncateCell = (text: string): string => (
  text.length > EXCEL_MAX_CELL_LENGTH
    ? `${text.slice(0, EXCEL_MAX_CELL_LENGTH - 3)}...`
    : text
);

/**
 * A cell's text. Strings are written as they are — JSON-quoting a summary or a
 * table of contents would only make it harder to read — and anything
 * structured is written as formatted JSON.
 */
export const cellValue = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return truncateCell(value);
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return truncateCell(JSON.stringify(value, null, 2));
  } catch {
    return '';
  }
};

/** The full document record, minus the detail views we do not export. */
export const metadataJson = (doc: Record<string, unknown>): string => {
  const kept = Object.fromEntries(
    Object.entries(doc).filter(([key]) => !EXCLUDED_METADATA_KEYS.includes(key)),
  );
  return cellValue(kept);
};

export const buildHeaderRow = (taxonomies: TaxonomyColumn[]): string[] => [
  'Title',
  'Organization',
  'Status',
  'Type',
  'Year',
  'Language',
  'Hosting page',
  'Document URL',
  'Summary',
  'Contents',
  'Metadata',
  ...taxonomies.map((taxonomy) => taxonomy.label),
  'Format',
  'Pages',
  'Size (MB)',
  'Error',
  'Last updated',
  'OCR',
];

export const buildDocumentRow = (
  doc: Record<string, any>,
  taxonomies: TaxonomyColumn[],
): string[] => [
  cellValue(doc.title),
  cellValue(doc.organization),
  cellValue(doc.status),
  cellValue(doc.document_type),
  cellValue(doc.published_year),
  cellValue(doc.language),
  cellValue(doc.report_url),
  cellValue(doc.pdf_url),
  cellValue(doc.full_summary),
  cellValue(doc.toc),
  metadataJson(doc),
  // The whole tag objects, so the export carries the model's reason too.
  ...taxonomies.map((taxonomy) => cellValue(doc.taxonomies?.[taxonomy.key])),
  cellValue(doc.file_format),
  cellValue(doc.page_count),
  cellValue(doc.file_size_mb),
  cellValue(doc.error_message ?? doc.sys_error_message),
  cellValue(doc.last_updated ?? doc.sys_last_updated),
  cellValue(doc.ocr_applied),
];

export const buildDocumentsSheet = (
  documents: Array<Record<string, any>>,
  taxonomies: TaxonomyColumn[],
): string[][] => [
  buildHeaderRow(taxonomies),
  ...documents.map((doc) => buildDocumentRow(doc, taxonomies)),
];

/** Taxonomy columns in config order, labelled as the table labels them. */
export const taxonomyColumnsFromConfig = (
  dataSourceConfig?: { pipeline?: { tag?: { taxonomies?: Record<string, { name?: string }> } } },
): TaxonomyColumn[] => {
  const configured = dataSourceConfig?.pipeline?.tag?.taxonomies || {};
  return Object.entries(configured).map(([key, taxonomy]) => ({
    key,
    label: taxonomy?.name || key,
  }));
};

export const buildExportFilename = (dataSource?: string, now: Date = new Date()): string => {
  const stamp = now.toISOString().slice(0, 10);
  const source = (dataSource || 'documents').replace(/[^A-Za-z0-9_-]+/g, '-');
  return `evidence-lab-documents-${source}-${stamp}.xlsx`;
};

const HEADER_STYLE = {
  font: { color: { rgb: 'FFFFFF' }, bold: true },
  fill: { fgColor: { rgb: '1F2A44' } },
  alignment: { wrapText: true, vertical: 'top' },
};

/** Build the workbook and hand it to the browser as a download. */
export const exportDocumentsToExcel = (
  documents: Array<Record<string, any>>,
  taxonomies: TaxonomyColumn[],
  dataSource?: string,
): void => {
  const rows = buildDocumentsSheet(documents, taxonomies);
  const sheet = XLSX.utils.aoa_to_sheet(rows);

  sheet['!cols'] = buildHeaderRow(taxonomies).map((_, index) => {
    // The three long-form columns need room; the rest stay readable.
    const wide = [8, 9, 10].includes(index);
    return { wch: wide ? 60 : 20 };
  });

  buildHeaderRow(taxonomies).forEach((_, index) => {
    const address = XLSX.utils.encode_cell({ r: 0, c: index });
    if (sheet[address]) sheet[address].s = HEADER_STYLE;
  });

  const book = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(book, sheet, 'Documents');
  const buffer = XLSX.write(book, { bookType: 'xlsx', type: 'array' });
  saveAs(
    new Blob([buffer], { type: 'application/octet-stream' }),
    buildExportFilename(dataSource),
  );
};
