// The Fact Checker of an open brief: whether a completed citation check
// applies to the brief as it is now, the passages it flags (per section, for
// the verdicts the reader's group chose), whether the reader has switched the
// highlights on, and which highlighted passage the pointer is resting on.
//
// The API decides everything about the check: which one is current, which
// verdicts to show and what each mark says. This hook fetches that answer
// again whenever the brief's content changes on the server, so a brief edited
// after its check loses the button until it is checked again.

import { RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import type { BriefFactCheckMark, BriefFactCheckRead } from '../../types/testing';
import { getBriefFactCheck } from './briefFactCheckApi';
import {
  allPainted,
  clearFactMarks,
  FACT_ID_ATTR,
  factMarkAt,
  paintFactMarks,
} from './briefFactCheckMarks';

export interface FactMarkHover {
  mark: BriefFactCheckMark;
  // Where the passage sits on screen, so the explanation can be placed by it.
  rect: { top: number; bottom: number; left: number; width: number };
}

export interface UseBriefFactCheckReturn {
  // A completed check judged the brief as it is now.
  available: boolean;
  // The reader switched the highlights on.
  active: boolean;
  toggle: () => void;
  // The flagged passages to paint, keyed by section id; empty while inactive.
  marks: Map<string, BriefFactCheckMark[]>;
  // Passages the reader's group highlights, for the button's tooltip.
  verdictLabels: string[];
  hover: FactMarkHover | null;
  // The pointer moved over the prose: `target` is what it is over now.
  onPointerOver: (target: EventTarget | null) => void;
  onPointerLeave: () => void;
}

const VERDICT_LABELS = new Map<string, string>([
  ['supported', 'Supported'],
  ['partially_supported', 'Partially supported'],
  ['unsupported', 'Unsupported'],
  ['cannot_assess', 'Cannot assess'],
]);

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

  const byId = useMemo(() => {
    const map = new Map<string, BriefFactCheckMark>();
    (result?.marks || []).forEach((m) => map.set(String(m.passage_id), m));
    return map;
  }, [result]);
  const marks = useMemo(
    () => (active && result ? marksBySection(result.marks) : EMPTY),
    [active, result],
  );

  const onPointerOver = useCallback(
    (target: EventTarget | null) => {
      const el = factMarkAt(target);
      const mark = el ? byId.get(el.getAttribute(FACT_ID_ATTR) || '') : undefined;
      if (!el || !mark) {
        setHover(null);
        return;
      }
      const r = el.getBoundingClientRect();
      setHover((prev) =>
        prev && prev.mark === mark
          ? prev
          : { mark, rect: { top: r.top, bottom: r.bottom, left: r.left, width: r.width } },
      );
    },
    [byId],
  );

  return {
    available,
    active,
    toggle: useCallback(() => setActive((v) => !v), []),
    marks,
    verdictLabels: (result?.highlight_verdicts || []).map((v) => VERDICT_LABELS.get(v) || v),
    hover,
    onPointerOver,
    onPointerLeave: useCallback(() => setHover(null), []),
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
