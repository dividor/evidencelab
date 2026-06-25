// CSV parsing for the "Create Dataset + Experiment" import. Each row pairs a
// question (the test-case input) with an expected answer (the per-row LLM-judge
// rubric). Mirrors the lightweight xlsx-based parsing used by DatasetEditor.

import * as XLSX from 'xlsx-js-style';

export interface QaCsvRow {
  query: string;
  expectedAnswer: string;
  tags?: string[];
  notes?: string;
}

// Header aliases, compared case-insensitively after trimming. The example
// export uses "Question" and "Unpacking Question / Probing"; the more generic
// spreadsheet headers people tend to use are accepted too.
const QUESTION_KEYS = ['question', 'query'];
const EXPECTED_KEYS = [
  'unpacking question / probing',
  'expected_answer',
  'expected answer',
  'expected_result',
  'expected result',
  'expected',
  'rubric',
  'probing',
];
const TAGS_KEYS = ['tags'];
const NOTES_KEYS = ['notes'];

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
  const query = pick(row, QUESTION_KEYS);
  if (!query) return null;
  const tags = pick(row, TAGS_KEYS)
    .split(/[;,]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
  const notes = pick(row, NOTES_KEYS);
  return {
    query,
    expectedAnswer: pick(row, EXPECTED_KEYS),
    tags: tags.length > 0 ? tags : undefined,
    notes: notes || undefined,
  };
};

// Parse CSV bytes or text into question/expected-answer rows. Rows without a
// question column are dropped. xlsx handles quoted, multi-line cells and detects
// the file's code page (the sample export is Windows-1252, not UTF-8), so raw
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

export const SAMPLE_QA_CSV = [
  'Question,Unpacking Question / Probing,tags,notes',
  '"What were the effects of COVID-19 on WFP activities?",'
    + '"Retrieve the most commonly cited ways in which WFP programmes changed '
    + 'after the pandemic, and the results of those changes.",covid,Core question',
  '"How timely was WFP in responding to COVID-19 needs?",'
    + '"Was WFP able to respond in due time despite COVID-induced constraints? '
    + 'Did the actions come at the appropriate time?",timeliness,',
].join('\n');
