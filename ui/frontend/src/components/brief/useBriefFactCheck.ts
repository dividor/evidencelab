// The Fact Checker of an open brief: whether a completed citation check
// applies to the brief as it is now, the passages it judged (per section,
// every verdict), whether the reader has switched the highlights on, which
// highlighted passage the pointer is resting on, and the evidence behind it.
//
// The API decides everything about the check: which one applies, which of
// the brief's sections it still covers (a check judges one version of the
// brief; sections changed since are reported, not highlighted), what each
// mark, note and legend entry says, and where in each cited excerpt the
// judge's quotes sit. This hook fetches that answer again whenever the
// brief's content changes on the server, and the evidence of a passage the
// first time its card opens.

import { RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import type {
  BriefFactCheckEvidence,
  BriefFactCheckLegendItem,
  BriefFactCheckMark,
  BriefFactCheckRead,
  BriefFactCheckSection,
} from '../../types/testing';
import { getBriefFactCheck, getBriefFactCheckEvidence } from './briefFactCheckApi';
import {
  allPainted,
  clearFactMarks,
  FACT_ID_ATTR,
  factMarkAt,
  paintFactMarks,
} from './briefFactCheckMarks';

export interface FactMarkHover {
  mark: BriefFactCheckMark;
  // Where the passage sits on screen, so the card can be placed by it.
  rect: { top: number; bottom: number; left: number; width: number };
}

// The evidence of one passage as the card shows it: still loading, loaded,
// or failed to load (reported in the card, since the rest still applies).
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
  // The judged passages to paint, keyed by section id; empty while inactive.
  marks: Map<string, BriefFactCheckMark[]>;
  // Sections the check no longer covers (changed since it judged the brief),
  // keyed by section id; empty while inactive.
  changedSections: Map<string, BriefFactCheckSection>;
  // Every verdict with its colour's label and count, for the legend.
  legend: BriefFactCheckLegendItem[];
  // How the brief relates to the version the check judged, for the tooltip.
  note: string;
  hover: FactMarkHover | null;
  // The evidence of the hovered passage, once asked for.
  evidence: FactEvidenceState | null;
  // The pointer moved over the prose: `target` is what it is over now.
  onPointerOver: (target: EventTarget | null) => void;
  onPointerLeave: () => void;
  // The pointer entered or left the card, which keeps it open while it is
  // being read (its excerpts scroll and its sources open).
  onCardEnter: () => void;
  onCardLeave: () => void;
}

// How long the card stays after the pointer leaves the passage, so it can
// be reached across the prose between the two.
const CLOSE_DELAY_MS = 250;

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
): UseBriefFactCheckReturn => {
  const [result, setResult] = useState<BriefFactCheckRead | null>(null);
  const [active, setActive] = useState(false);
  const [hover, setHover] = useState<FactMarkHover | null>(null);
  // Evidence by passage id, for the check that applies; dropped with it.
  const [evidence, setEvidence] = useState<Map<number, FactEvidenceState>>(new Map());
  const closeTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!briefId) {
      setResult(null);
      return;
    }
    let cancelled = false;
    getBriefFactCheck(briefId)
      .then((read) => {
        if (!cancelled) setResult(read);
      })
      .catch((err) => {
        if (cancelled) return;
        setResult(null);
        // A brief the server does not know yet (saved under a local id until
        // its first save completes) has no check; anything else is reported.
        if (!(axios.isAxiosError(err) && err.response?.status === 404)) {
          console.error('Could not load the brief fact check', err);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [briefId, revision]);

  // Switching briefs, or the check going stale, drops the highlights.
  useEffect(() => {
    setActive(false);
    setHover(null);
  }, [briefId]);
  const available = !!result?.check;
  useEffect(() => {
    if (!available) {
      setActive(false);
      setHover(null);
    }
  }, [available]);
  // Another check (or none) means other evidence.
  const checkId = result?.check?.id ?? null;
  useEffect(() => {
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

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);
  const closeSoon = useCallback(() => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = null;
      setHover(null);
    }, CLOSE_DELAY_MS);
  }, [cancelClose]);
  useEffect(() => cancelClose, [cancelClose]);

  // The evidence of the hovered passage, fetched once per check.
  const hoveredId = hover?.mark.passage_id ?? null;
  useEffect(() => {
    if (!briefId || !checkId || hoveredId === null || evidence.has(hoveredId)) return;
    setEvidence((prev) => new Map(prev).set(hoveredId, { status: 'loading' }));
    getBriefFactCheckEvidence(briefId, checkId, hoveredId)
      .then((read) => {
        setEvidence((prev) =>
          new Map(prev).set(hoveredId, { status: 'ready', blocks: read.evidence }),
        );
      })
      .catch((err) => {
        console.error('Could not load the evidence of a fact-checked passage', err);
        setEvidence((prev) => new Map(prev).set(hoveredId, { status: 'failed' }));
      });
  }, [briefId, checkId, hoveredId, evidence]);

  const onPointerOver = useCallback(
    (target: EventTarget | null) => {
      const el = factMarkAt(target);
      const mark = el ? byId.get(el.getAttribute(FACT_ID_ATTR) || '') : undefined;
      if (!el || !mark) {
        // Over plain prose: the card stays a moment, in case the pointer is
        // on its way to it.
        closeSoon();
        return;
      }
      cancelClose();
      const r = el.getBoundingClientRect();
      setHover((prev) =>
        prev && prev.mark === mark
          ? prev
          : { mark, rect: { top: r.top, bottom: r.bottom, left: r.left, width: r.width } },
      );
    },
    [byId, cancelClose, closeSoon],
  );

  return {
    available,
    active,
    toggle: useCallback(() => setActive((v) => !v), []),
    marks,
    changedSections,
    legend: result?.legend || NO_LEGEND,
    note: result?.note || '',
    hover,
    evidence: hoveredId === null ? null : (evidence.get(hoveredId) ?? { status: 'loading' }),
    onPointerOver,
    onPointerLeave: closeSoon,
    onCardEnter: cancelClose,
    onCardLeave: closeSoon,
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
