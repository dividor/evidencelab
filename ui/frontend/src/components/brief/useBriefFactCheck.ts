// The Fact Checker of an open brief: whether a completed citation check
// applies to the brief as it is now, the passages it judged (per section,
// every verdict), whether the reader has switched the highlights on, which
// claim the reader has selected, and the evidence behind it.
//
// The API decides everything about the check: which one applies, which of
// the brief's sections it still covers (a check judges one version of the
// brief; sections changed since are reported, not highlighted), what each
// mark, note and legend entry says, and where in each cited excerpt the
// judge's quotes sit. This hook fetches that answer again whenever the
// brief's content changes on the server, and the evidence of a passage the
// first time its card opens.

import { RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBriefCheckRun } from './useBriefCheckRun';
import type {
  BriefFactCheckEvidence,
  BriefFactCheckLegendItem,
  BriefFactCheckMark,
  BriefCheckRun,
  BriefFactCheckSection,
} from '../../types/testing';
import { getBriefFactCheckEvidence } from './briefFactCheckApi';
import {
  allPainted,
  clearFactMarks,
  FACT_ID_ATTR,
  factMarkAt,
  paintFactMarks,
} from './briefFactCheckMarks';

export type FactEvidenceState =
  | { status: 'loading' }
  | { status: 'ready'; blocks: BriefFactCheckEvidence[] }
  | { status: 'failed' };

export interface UseBriefFactCheckReturn {
  // A completed check still covers part of the brief as it is now.
  available: boolean;
  // The reader switched the highlights on.
  active: boolean;
  toggle: () => void;
  run: BriefCheckRun | null;
  busy: boolean;
  notice: string;
  disabledReason?: string | null;
  start: () => void;
  stop: () => void;
  // The judged passages to paint, keyed by section id; empty while inactive.
  marks: Map<string, BriefFactCheckMark[]>;
  // Sections the check no longer covers (changed since it judged the brief),
  // keyed by section id; empty while inactive.
  changedSections: Map<string, BriefFactCheckSection>;
  // Every verdict with its colour's label and count, for the legend.
  legend: BriefFactCheckLegendItem[];
  // How the brief relates to the version the check judged, for the tooltip.
  note: string;
  evidence: FactEvidenceState | null;
  selectClaim: (target: EventTarget | null) => void;
  selectedClaim: BriefFactCheckMark | null;
  closeClaim: () => void;
}

const marksBySection = (marks: BriefFactCheckMark[]): Map<string, BriefFactCheckMark[]> => {
  const map = new Map<string, BriefFactCheckMark[]>();
  marks.forEach((mark) => {
    if (!mark.section_id) return;
    const list = map.get(mark.section_id) || [];
    list.push(mark);
    map.set(mark.section_id, list);
  });
  return map;
};

const EMPTY: Map<string, BriefFactCheckMark[]> = new Map();
const NO_SECTIONS: Map<string, BriefFactCheckSection> = new Map();
const NO_LEGEND: BriefFactCheckLegendItem[] = [];

/**
 * @param briefId the open brief's server id, or null when there is no saved
 *   brief to check (anonymous use, a brief not yet saved)
 * @param revision bumps whenever the API's content for the brief was applied,
 *   so the check is re-evaluated against what the server now holds
 */
export const useBriefFactCheck = (
  briefId: string | null,
  revision: number,
  modelCombo?: string | null,
): UseBriefFactCheckReturn => {
  const { result, active, setActive, ...controls } = useBriefCheckRun(briefId, revision, modelCombo);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Evidence by passage id, for the check that applies; dropped with it.
  const [evidence, setEvidence] = useState<Map<string, FactEvidenceState>>(new Map());

  const available = Boolean(result?.marks.length);
  // Another check (or none) means other evidence.
  const checkId = result?.check?.id ?? null;
  useEffect(() => {
    setSelectedId(null);
    setEvidence(new Map());
  }, [checkId]);

  const byId = useMemo(() => {
    const map = new Map<string, BriefFactCheckMark>();
    (result?.marks || []).forEach((m) => map.set(String(m.passage_id), m));
    return map;
  }, [result]);
  const marks = useMemo(
    () => (active && result ? marksBySection(result.marks) : EMPTY),
    [active, result],
  );
  const changedSections = useMemo(
    () =>
      active && result
        ? new Map((result.changed_sections || []).map((s) => [s.id, s]))
        : NO_SECTIONS,
    [active, result],
  );

  const selectedClaim = active && selectedId ? byId.get(selectedId) ?? null : null;
  const passageId = selectedClaim?.passage_id ?? null;
  const evidenceKey = checkId && passageId != null ? `${checkId}/${passageId}` : null;
  useEffect(() => {
    if (!briefId || !checkId || passageId === null || !evidenceKey || evidence.has(evidenceKey)) return;
    setEvidence((prev) => new Map(prev).set(evidenceKey, { status: 'loading' }));
    getBriefFactCheckEvidence(briefId, checkId, passageId)
      .then((read) => {
        setEvidence((prev) =>
          new Map(prev).set(evidenceKey, { status: 'ready', blocks: read.evidence }),
        );
      })
      .catch((err) => {
        console.error('Could not load the evidence of a fact-checked passage', err);
        setEvidence((prev) => new Map(prev).set(evidenceKey, { status: 'failed' }));
      });
  }, [briefId, checkId, passageId, evidenceKey, evidence]);

  return {
    ...controls,
    available,
    active,
    toggle: useCallback(() => {
      setSelectedId(null);
      setActive((v) => !v);
    }, [setActive]),
    marks,
    changedSections,
    legend: result?.legend || NO_LEGEND,
    note: result?.note || '',
    evidence: !evidenceKey ? null : (evidence.get(evidenceKey) ?? { status: 'loading' }),
    selectClaim: (target) => {
      const id = factMarkAt(target)?.getAttribute(FACT_ID_ATTR);
      if (id && byId.has(id)) {
        setSelectedId(id);
      }
    },
    selectedClaim,
    closeClaim: () => setSelectedId(null),
  };
};

/**
 * Keep a section's fact marks painted over its rendered prose. The marks live
 * in the DOM rather than in React's tree, so a re-render of the prose wipes
 * them; an observer puts them back, disconnected while painting so our own
 * mutations cannot trigger another pass.
 */
export const useFactMarkPainter = (
  proseRef: RefObject<HTMLDivElement | null>,
  content: string,
  marks: BriefFactCheckMark[] | undefined,
): void => {
  const marksRef = useRef(marks);
  marksRef.current = marks;
  useEffect(() => {
    const el = proseRef.current;
    if (!el) return;
    if (!marks || !marks.length) {
      clearFactMarks(el);
      return;
    }
    const options = { childList: true, subtree: true, characterData: true };
    // A re-render replaces whole paragraphs, so some marks can be gone while
    // others remain: repaint as soon as any is missing.
    const observer = new MutationObserver(() => {
      if (!allPainted(el, marksRef.current || [])) repaint();
    });
    function repaint(): void {
      observer.disconnect();
      paintFactMarks(el as HTMLElement, marksRef.current || []);
      observer.observe(el as HTMLElement, options);
    }
    repaint();
    return () => {
      observer.disconnect();
      clearFactMarks(el);
    };
  }, [proseRef, content, marks]);
};
