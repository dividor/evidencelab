// CSV parsing for the "Create Dataset + Experiment" import. The format mirrors
// the regular dataset CSV upload (columns: query, tags, notes, filters) with one
// extra column, "expectation", whose value becomes that row's LLM-judge rubric.

import * as XLSX from 'xlsx-js-style';

export interface QaCsvRow {
  // Same shape as the regular dataset CSV case input: { query, filters? }.
  input: Record<string, unknown>;
  tags?: string[];
  notes?: string;
  // Becomes the per-row llm_judge rubric (the "expected answer").
  expectation: string;
}

// Header aliases, compared case-insensitively after trimming.
const QUERY_KEYS = ['query', 'question'];
const EXPECTATION_KEYS = ['expectation', 'expected_answer', 'expected_result'];

// First non-empty value among the given header aliases.
const pick = (row: Record<string, string>, keys: string[]): string => {
  for (const key of keys) {
    const value = row[key];
    if (value) return value;
  }
  return '';
};

// Lower-case + trim the header keys and stringify/trim the cell values so
// matching is robust to spreadsheet capitalisation and stray whitespace.
const normaliseRow = (raw: Record<string, unknown>): Record<string, string> => {
  const out: Record<string, string> = {};
  Object.keys(raw).forEach((key) => {
    out[key.trim().toLowerCase()] = String(raw[key] ?? '').trim();
  });
  return out;
};

const toQaRow = (raw: Record<string, unknown>): QaCsvRow | null => {
  const row = normaliseRow(raw);
  const query = pick(row, QUERY_KEYS);
  if (!query) return null;
  const input: Record<string, unknown> = { query };
  if (row.filters) {
    try {
      const parsed = JSON.parse(row.filters);
      if (parsed && typeof parsed === 'object') input.filters = parsed;
    } catch {
      // Ignore malformed filters JSON — keep the query-only case.
    }
  }
  const tags = (row.tags || '')
    .split(/[;,]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
  return {
    input,
    tags: tags.length > 0 ? tags : undefined,
    notes: row.notes || undefined,
    expectation: pick(row, EXPECTATION_KEYS),
  };
};

// Parse CSV bytes or text into rows. Rows without a query column are dropped.
// xlsx handles quoted, multi-line cells and detects the file's code page, so raw
// bytes are preferred over a UTF-8 text decode.
export const parseQaCsv = (data: ArrayBuffer | string): QaCsvRow[] => {
  const workbook =
    typeof data === 'string'
      ? XLSX.read(data, { type: 'string' })
      : XLSX.read(new Uint8Array(data), { type: 'array' });
  const sheet = workbook.Sheets[workbook.SheetNames[0]];
  if (!sheet) return [];
  const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, {
    defval: '',
  });
  return rows.map(toQaRow).filter((row): row is QaCsvRow => row !== null);
};

// Same columns as the regular dataset CSV plus an "expectation" column.
// Regular dataset sample (query, tags, notes, filters). The QA sample below is
// the same shape plus one extra `expectation` column.
export const SAMPLE_DATASET_CSV = [
  'query,tags,notes,filters',
  'girls education in Kenya,regression;baseline,Core evaluation question,',
  'cash vs in-kind transfers in Kenya,regression,Comparison question,',
  'nutrition outcomes for children,smoke,,"{""country"": ""Kenya""}"',
].join('\n');

export const SAMPLE_QA_CSV = [
  'query,tags,notes,filters,expectation',
  '"What were the effects of COVID-19 on WFP activities?",covid,Core question,,'
    + '"The summary should cover the most commonly cited ways WFP programmes '
    + 'changed after the pandemic and the results of those changes."',
  '"How timely was WFP in responding to COVID-19 needs?",timeliness,,,'
    + '"Whether WFP responded in due time despite COVID constraints and whether '
    + 'the actions came at the appropriate time."',
].join('\n');
