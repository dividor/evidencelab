// Comment state for the open brief: loading, adding, replying, editing,
// resolving and deleting. Threads are one level deep — a reply carries the id
// of the comment that opened the thread.

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BriefComment,
  createComment,
  deleteComment,
  listComments,
  NewComment,
  updateComment,
} from './briefCommentsApi';

export interface CommentThread {
  root: BriefComment;
  replies: BriefComment[];
}

export interface UseBriefCommentsReturn {
  comments: BriefComment[];
  threads: CommentThread[];
  openCount: number;
  loading: boolean;
  error: string | null;
  add: (comment: NewComment) => Promise<void>;
  edit: (commentId: string, body: string) => Promise<void>;
  setResolved: (commentId: string, resolved: boolean) => Promise<void>;
  remove: (commentId: string) => Promise<void>;
  refresh: () => Promise<void>;
  setError: (message: string | null) => void;
}

/** Group flat comments into threads, oldest first. */
export const buildThreads = (comments: BriefComment[]): CommentThread[] => {
  const roots = comments.filter((c) => !c.parentId);
  const repliesByParent = new Map<string, BriefComment[]>();
  comments
    .filter((c) => c.parentId)
    .forEach((c) => {
      const list = repliesByParent.get(c.parentId as string) || [];
      list.push(c);
      repliesByParent.set(c.parentId as string, list);
    });
  return roots.map((root) => ({ root, replies: repliesByParent.get(root.id) || [] }));
};

export const useBriefComments = (
  briefId: string | null,
  enabled: boolean,
): UseBriefCommentsReturn => {
  const [comments, setComments] = useState<BriefComment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!briefId || !enabled) {
      setComments([]);
      return;
    }
    setLoading(true);
    try {
      setComments(await listComments(briefId));
      setError(null);
    } catch {
      setError('Could not load comments.');
    } finally {
      setLoading(false);
    }
  }, [briefId, enabled]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const add = useCallback(
    async (comment: NewComment) => {
      if (!briefId) return;
      try {
        const created = await createComment(briefId, comment);
        setComments((prev) => [...prev, created]);
        setError(null);
      } catch {
        setError('Could not add the comment.');
      }
    },
    [briefId],
  );

  const edit = useCallback(
    async (commentId: string, body: string) => {
      if (!briefId) return;
      try {
        const saved = await updateComment(briefId, commentId, { body });
        setComments((prev) => prev.map((c) => (c.id === commentId ? saved : c)));
        setError(null);
      } catch {
        setError('Could not save the edit.');
      }
    },
    [briefId],
  );

  const setResolved = useCallback(
    async (commentId: string, resolved: boolean) => {
      if (!briefId) return;
      try {
        const saved = await updateComment(briefId, commentId, { resolved });
        setComments((prev) => prev.map((c) => (c.id === commentId ? saved : c)));
        setError(null);
      } catch {
        setError('Could not update the comment.');
      }
    },
    [briefId],
  );

  const remove = useCallback(
    async (commentId: string) => {
      if (!briefId) return;
      try {
        await deleteComment(briefId, commentId);
        // Deleting a thread's opening comment takes its replies with it, as the
        // server cascades — mirror that here so the rail matches immediately.
        setComments((prev) =>
          prev.filter((c) => c.id !== commentId && c.parentId !== commentId),
        );
        setError(null);
      } catch {
        setError('Could not delete the comment.');
      }
    },
    [briefId],
  );

  const threads = useMemo(() => buildThreads(comments), [comments]);
  const openCount = useMemo(
    () => threads.filter((t) => !t.root.resolved).length,
    [threads],
  );

  return {
    comments,
    threads,
    openCount,
    loading,
    error,
    add,
    edit,
    setResolved,
    remove,
    refresh,
    setError,
  };
};
