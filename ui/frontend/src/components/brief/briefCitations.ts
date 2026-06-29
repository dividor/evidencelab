import { SourceReference } from '../../types/api';
import { extractCitedNumbers } from '../citations/CitedContent';
import { BriefSection } from './briefTypes';

const CITATION_RE = /\[(\d+(?:,\s*\d+)*)\]/g;

// Normalise a line to compare it against a heading title: drop markdown heading
// hashes, leading "1." / "2.1" numbering, and emphasis markers.
const normaliseHeadingLine = (s: string): string =>
  s
    .replace(/^#{1,6}\s+/, '')
    .replace(/^\d+(\.\d+)*\.?\s+/, '')
    .replace(/[*_`]/g, '')
    .trim()
    .toLowerCase();

/**
 * Remove a section's leading title line so it isn't shown twice — the brief
 * already renders the section's own (editable) heading above the prose. Strips
 * the first non-blank line when it is a markdown heading, or when it simply
 * repeats the section title, then drops the blank line(s) that followed.
 */
export const stripLeadingTitle = (md: string, title: string): string => {
  const lines = md.replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  while (i < lines.length && lines[i].trim() === '') i++;
  if (i >= lines.length) return md;
  const first = lines[i];
  const isHeading = /^#{1,6}\s+/.test(first);
  const repeatsTitle = !!title && normaliseHeadingLine(first) === normaliseHeadingLine(title);
  if (!isHeading && !repeatsTitle) return md;
  i++;
  while (i < lines.length && lines[i].trim() === '') i++;
  return lines.slice(i).join('\n');
};

export interface GlobalRef {
  n: number;
  title: string;
  page?: number;
  source: SourceReference;
}

export interface SectionDisplay {
  content: string;
  sources: SourceReference[];
}

/**
 * Renumber citations across the whole brief into one consecutive sequence,
 * combined by document: every section's per-section `[n]` markers are remapped
 * to a global number (same document → same number everywhere), and the compiled
 * References list is built from the same global registry. Used for both the
 * on-screen render (inline citations, per-section Evidence panels, References)
 * and the Word export, so all three stay in sync as sections are researched.
 */
export const buildGlobalCitations = (
  sections: BriefSection[],
): { refs: GlobalRef[]; display: Map<string, SectionDisplay> } => {
  const docToGlobal = new Map<string, number>();
  const refs: GlobalRef[] = [];
  // Assign global numbers in order of first citation across done sections.
  sections.forEach((s) => {
    if (s.status !== 'done' || !s.content) return;
    extractCitedNumbers(s.content).forEach((localN) => {
      const src = s.sources.find((x) => x.index === localN);
      if (!src || docToGlobal.has(src.docId)) return;
      const n = refs.length + 1;
      docToGlobal.set(src.docId, n);
      refs.push({ n, title: src.title, page: src.page, source: src });
    });
  });
  // Build per-section display content + sources keyed by the global number.
  const display = new Map<string, SectionDisplay>();
  sections.forEach((s) => {
    if (s.status !== 'done' || !s.content) return;
    const localToGlobal = new Map<number, number>();
    const sources: SourceReference[] = [];
    const seen = new Set<number>();
    s.sources.forEach((src) => {
      if (src.index == null) return;
      const g = docToGlobal.get(src.docId);
      if (g == null) return;
      localToGlobal.set(src.index, g);
      if (!seen.has(g)) {
        seen.add(g);
        sources.push({ ...src, index: g });
      }
    });
    const content = stripLeadingTitle(s.content, s.title).replace(CITATION_RE, (_m, nums: string) => {
      const mapped = Array.from(
        new Set(
          nums
            .split(',')
            .map((x) => localToGlobal.get(parseInt(x.trim(), 10)))
            .filter((g): g is number => g != null),
        ),
      );
      return mapped.length ? `[${mapped.join(', ')}]` : '';
    });
    display.set(s.id, { content, sources });
  });
  return { refs, display };
};
