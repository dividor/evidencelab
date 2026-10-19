// FROZEN copy of ui/frontend/src/components/brief/briefCitations.ts as of
// rc/v1.6.4 (before Brief citation handling moved into the API), kept only so
// scripts/fixes/convert_brief_citations.py can compare the API's renumbering
// with what the browser produced for the same stored rows. Not used by the app.
// extractCitedNumbers is inlined from components/citations/CitedContent.tsx.

export interface SourceReference {
  chunkId: string;
  docId: string;
  title: string;
  text: string;
  score: number;
  page?: number;
  index?: number;
  variants?: SourceReference[];
  [key: string]: unknown;
}

export type ReferenceGrouping = 'passage' | 'document-multiple' | 'document-single';

export interface BriefSection {
  id: string;
  title: string;
  status: string;
  revising?: boolean;
  content: string;
  sources: SourceReference[];
}

const CITATION_REGEX = /\[(\d+(?:,\s*\d+)*)\]/g;

const parseCitationNumbers = (raw: string): number[] =>
  raw
    .split(',')
    .map((s) => parseInt(s.trim(), 10))
    .filter((n) => !isNaN(n));

export const extractCitedNumbers = (text: string): number[] => {
  const cited = new Set<number>();
  let m: RegExpExecArray | null;
  const re = new RegExp(CITATION_REGEX.source, 'g');
  while ((m = re.exec(text)) !== null) {
    parseCitationNumbers(m[1]).forEach((n) => cited.add(n));
  }
  return Array.from(cited).sort((a, b) => a - b);
};

const CITATION_RE = /\[(\d+(?:,\s*\d+)*)\]/g;
const ADJACENT_DUPLICATE_RE = /\[(\d+(?:, \d+)*)\]\s*\[\1\]/g;

const collapseAdjacentDuplicates = (content: string): string => {
  let out = content;
  let prev: string;
  do {
    prev = out;
    out = out.replace(ADJACENT_DUPLICATE_RE, '[$1]');
  } while (out !== prev);
  return out;
};

const normaliseHeadingLine = (s: string): string =>
  s
    .replace(/^#{1,6}\s+/, '')
    .replace(/^\d+(\.\d+)*\.?\s+/, '')
    .replace(/[*_`]/g, '')
    .trim()
    .toLowerCase();

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

const citationKey = (src: SourceReference, grouping: ReferenceGrouping): string =>
  grouping === 'document-single'
    ? `doc:${src.docId || src.title}`
    : src.chunkId || `${src.docId}#${src.page ?? 'na'}`;

export const buildGlobalCitations = (
  sections: BriefSection[],
  grouping: ReferenceGrouping = 'passage',
): { refs: GlobalRef[]; display: Map<string, SectionDisplay> } => {
  const perDocument = grouping === 'document-single';
  const keyToGlobal = new Map<string, number>();
  const refs: GlobalRef[] = [];
  const isVisible = (s: BriefSection): boolean =>
    (s.status === 'done' || !!s.revising) && !!s.content;
  sections.forEach((s) => {
    if (!isVisible(s)) return;
    extractCitedNumbers(s.content).forEach((localN) => {
      const src = s.sources.find((x) => x.index === localN);
      if (!src || keyToGlobal.has(citationKey(src, grouping))) return;
      const n = refs.length + 1;
      keyToGlobal.set(citationKey(src, grouping), n);
      refs.push({ n, title: src.title, page: perDocument ? undefined : src.page, source: src });
    });
  });
  const display = new Map<string, SectionDisplay>();
  sections.forEach((s) => {
    if (!isVisible(s)) return;
    const localToGlobal = new Map<number, number>();
    const sources: SourceReference[] = [];
    const byGlobal = new Map<number, SourceReference>();
    s.sources.forEach((src) => {
      if (src.index == null) return;
      const g = keyToGlobal.get(citationKey(src, grouping));
      if (g == null) return;
      localToGlobal.set(src.index, g);
      const existing = byGlobal.get(g);
      if (!existing) {
        const entry = { ...src, index: g };
        byGlobal.set(g, entry);
        sources.push(entry);
        return;
      }
      if (perDocument && src.chunkId !== existing.chunkId) {
        existing.variants = [...(existing.variants || []), src];
      }
    });
    const renumbered = stripLeadingTitle(s.content, s.title).replace(
      CITATION_RE,
      (_m, nums: string) => {
        const mapped = Array.from(
          new Set(
            nums
              .split(',')
              .map((x) => localToGlobal.get(parseInt(x.trim(), 10)))
              .filter((g): g is number => g != null),
          ),
        );
        return mapped.length ? `[${mapped.join(', ')}]` : '';
      },
    );
    display.set(s.id, { content: collapseAdjacentDuplicates(renumbered), sources });
  });
  return { refs, display };
};
