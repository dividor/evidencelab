// Everything to do with annotating a brief: the text selection and the actions
// offered on it, the comment being composed, which passages carry comments,
// which thread is open, and whether comments are shown at all.
//
// Kept out of BriefTab so the tab stays a layout component and this concern
// (which will grow — "Research this further" and friends) has one home.

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { buildAnchor } from './briefCommentAnchors';
import { CommentMark } from './briefCommentMarks';
import { IconComment } from './BriefIcons';
import { BriefSelection, HighlightRect, SelectionAction } from './BriefSelectionMenu';
import { BriefSection } from './briefTypes';
import { UseBriefCommentsReturn } from './useBriefComments';

// Whether the reader wants comments shown; remembered across briefs.
const SHOW_COMMENTS_KEY = 'evidencelab_brief_show_comments';

// Below this width there is no comment rail, so a passage opens its thread in
// a modal instead of scrolling the rail.
const RAIL_BREAKPOINT = '(max-width: 1024px)';

export interface PendingComment {
  sectionId: string;
  quote: string;
  prefix: string;
  suffix: string;
  // Where the passage sits on screen, so it stays marked while the box is open.
  rects: HighlightRect[];
}

export interface UseBriefAnnotationsReturn {
  showComments: boolean;
  toggleComments: (show: boolean) => void;
  commentMarks: Map<string, CommentMark[]>;
  orphanedThreadIds: string[];
  activeThreadId: string | null;
  threadModalId: string | null;
  closeThreadModal: () => void;
  openThreadFromText: (threadId: string) => void;
  jumpToThreadPassage: (threadId: string | null) => void;
  selection: BriefSelection | null;
  setSelection: (selection: BriefSelection | null) => void;
  selectionActions: SelectionAction[];
  pendingComment: PendingComment | null;
  clearPendingComment: () => void;
}

const readShowComments = (): boolean => {
  try {
    return localStorage.getItem(SHOW_COMMENTS_KEY) !== 'false';
  } catch {
    return true;
  }
};

export const useBriefAnnotations = (
  sections: BriefSection[],
  comments: UseBriefCommentsReturn | null,
): UseBriefAnnotationsReturn => {
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [threadModalId, setThreadModalId] = useState<string | null>(null);
  const [selection, setSelection] = useState<BriefSelection | null>(null);
  const [pendingComment, setPendingComment] = useState<PendingComment | null>(null);
  const [orphanedThreadIds, setOrphanedThreadIds] = useState<string[]>([]);
  // A reading preference, kept per browser so a reader who turns comments off
  // does not meet them again on the next brief.
  const [showComments, setShowComments] = useState<boolean>(readShowComments);

  const toggleComments = useCallback((show: boolean) => {
    setShowComments(show);
    try {
      localStorage.setItem(SHOW_COMMENTS_KEY, show ? 'true' : 'false');
    } catch {
      /* a browser refusing storage should not break the toggle */
    }
  }, []);

  // Commented passages per section, painted into the prose.
  const threads = comments?.threads;
  const commentMarks = useMemo(() => {
    const map = new Map<string, CommentMark[]>();
    (threads || []).forEach((thread) => {
      const sectionId = thread.root.sectionId;
      if (!sectionId || !thread.root.quote) return;
      const list = map.get(sectionId) || [];
      list.push({
        threadId: thread.root.id,
        quote: thread.root.quote,
        resolved: thread.root.resolved,
        count: 1 + thread.replies.length,
      });
      map.set(sectionId, list);
    });
    return map;
    // Keyed on `threads` rather than the hook's return value, whose identity
    // changes every render and would rebuild the marks constantly.
  }, [threads]);

  // Threads whose quoted passage is no longer in the brief (its section was
  // re-researched): the card says so rather than appearing broken.
  useEffect(() => {
    if (!threads) return;
    // Marks are painted into the DOM, so read back what actually landed.
    const timer = window.setTimeout(() => {
      const painted = new Set(
        Array.from(document.querySelectorAll('.brief-comment-mark')).map((m) =>
          m.getAttribute('data-thread-id'),
        ),
      );
      const next = threads
        .filter((t) => t.root.quote && !painted.has(t.root.id))
        .map((t) => t.root.id);
      // Only update on a real change: a fresh array each pass would re-render,
      // re-run this effect and repaint the marks on a loop.
      setOrphanedThreadIds((prev) =>
        prev.length === next.length && prev.every((id, i) => id === next[i]) ? prev : next,
      );
    }, 300);
    return () => window.clearTimeout(timer);
  }, [threads, showComments]);

  // A speech bubble in the prose: with no rail to scroll (narrow screen), the
  // thread opens as a modal instead.
  const openThreadFromText = useCallback((threadId: string) => {
    setActiveThreadId(threadId);
    if (window.matchMedia(RAIL_BREAKPOINT).matches) {
      setThreadModalId(threadId);
      return;
    }
    window.requestAnimationFrame(() => {
      document
        .querySelector(`[data-thread-card="${threadId}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }, []);

  // A card in the rail: scroll the brief to the passage it annotates.
  const jumpToThreadPassage = useCallback((threadId: string | null) => {
    setActiveThreadId(threadId);
    if (!threadId) return;
    window.requestAnimationFrame(() => {
      const mark = document.querySelector(`.brief-comment-mark[data-thread-id="${threadId}"]`);
      if (!mark) return;
      const bar = document.querySelector('.top-bar');
      const offset = (bar instanceof HTMLElement ? bar.offsetHeight : 0) + 24;
      window.scrollTo({
        top: mark.getBoundingClientRect().top + window.scrollY - offset,
        behavior: 'smooth',
      });
    });
  }, []);

  // Turn a selection into a comment anchor and open the composer. Written as a
  // selection *action* so later ones slot in beside it.
  const commentOnSelection = useCallback(
    (sel: BriefSelection) => {
      const content = sections.find((s) => s.id === sel.sectionId)?.content || '';
      const at = content.indexOf(sel.text);
      const anchor =
        at >= 0
          ? buildAnchor(content, at, at + sel.text.length)
          : { quote: sel.text, quotePrefix: '', quoteSuffix: '' };
      setSelection(null);
      setPendingComment({
        sectionId: sel.sectionId,
        quote: anchor.quote,
        prefix: anchor.quotePrefix,
        suffix: anchor.quoteSuffix,
        rects: sel.rects,
      });
    },
    [sections],
  );

  const selectionActions = useMemo<SelectionAction[]>(
    () => [
      {
        key: 'comment',
        label: 'Comment',
        title: 'Comment on the selected text',
        icon: <IconComment />,
        onRun: commentOnSelection,
      },
    ],
    [commentOnSelection],
  );

  return {
    showComments,
    toggleComments,
    commentMarks,
    orphanedThreadIds,
    activeThreadId,
    threadModalId,
    closeThreadModal: useCallback(() => setThreadModalId(null), []),
    openThreadFromText,
    jumpToThreadPassage,
    selection,
    setSelection,
    selectionActions,
    pendingComment,
    clearPendingComment: useCallback(() => setPendingComment(null), []),
  };
};
