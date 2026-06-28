import { SourceReference } from '../../types/api';
import { extractCitedNumbers } from '../citations/CitedContent';
import { BriefSection } from './briefTypes';

const CITATION_RE = /\[(\d+(?:,\s*\d+)*)\]/g;

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
    const content = s.content.replace(CITATION_RE, (_m, nums: string) => {
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
