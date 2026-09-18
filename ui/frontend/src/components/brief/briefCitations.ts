import { SourceReference } from '../../types/api';
import { extractCitedNumbers } from '../citations/CitedContent';
import { BriefSection, ReferenceGrouping } from './briefTypes';

const CITATION_RE = /\[(\d+(?:,\s*\d+)*)\]/g;
// Two markers side by side that carry the same number(s) — `[1][1]`, `[1] [1]`.
// Combining citations by document produces these wherever the model cited two
// passages of one report back to back, and the reader should see `[1]` once.
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

/** The identity a citation number is assigned to: the cited passage (chunk),
 *  or — for single-per-document grouping — the document itself. */
const citationKey = (src: SourceReference, grouping: ReferenceGrouping): string =>
  grouping === 'document-single'
    ? `doc:${src.docId || src.title}`
    : src.chunkId || `${src.docId}#${src.page ?? 'na'}`;

/**
 * Renumber citations across the whole brief into one consecutive sequence:
 * every section's per-section `[n]` markers are remapped to a global number,
 * and the compiled References list is built from the same global registry.
 * Used for both the on-screen render (inline citations, per-section Evidence
 * panels, References) and the Word export, so all three stay in sync as
 * sections are researched.
 *
 * With the default grouping there is one number per cited passage, exactly as
 * the AI summary numbers its sources (assistant_graph assigns global_index per
 * chunk): a report cited from p.32 and p.56 gets two numbers, and the reader
 * can see which page each claim came from. With 'document-single' grouping
 * every passage of a document shares one number and the reference carries no
 * page, so the list reads at the document level only.
 */
export const buildGlobalCitations = (
  sections: BriefSection[],
  grouping: ReferenceGrouping = 'passage',
): { refs: GlobalRef[]; display: Map<string, SectionDisplay> } => {
  const perDocument = grouping === 'document-single';
  const keyToGlobal = new Map<string, number>();
  const refs: GlobalRef[] = [];
  // A section mid-Edit/Update (revising) keeps its old content on screen, so
  // it stays in the numbering — otherwise citations would jump twice per run.
  const isVisible = (s: BriefSection): boolean =>
    (s.status === 'done' || !!s.revising) && !!s.content;
  // Assign global numbers in order of first citation across visible sections.
  sections.forEach((s) => {
    if (!isVisible(s)) return;
    extractCitedNumbers(s.content).forEach((localN) => {
      const src = s.sources.find((x) => x.index === localN);
      if (!src || keyToGlobal.has(citationKey(src, grouping))) return;
      const n = refs.length + 1;
      keyToGlobal.set(citationKey(src, grouping), n);
      // A document-level reference has no page; its source is the first cited
      // passage, so clicking the reference still opens the document.
      refs.push({ n, title: src.title, page: perDocument ? undefined : src.page, source: src });
    });
  });
  // Build per-section display content + sources keyed by the global number.
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
      // Per passage, each number belongs to one passage, so there is nothing to
      // merge. Per document, the other passages ride along as variants so the
      // hover card can still show the passage that supports the hovered claim.
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
