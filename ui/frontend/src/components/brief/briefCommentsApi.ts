// REST client for brief comments. Mirrors briefCentralApi.ts: same base URL,
// credentials and CSRF handling, so comments behave like the rest of Brief
// Central.

import API_BASE_URL from '../../config';

export interface BriefComment {
  id: string;
  briefId: string;
  parentId: string | null;
  sectionId: string | null;
  quote: string | null;
  quotePrefix: string | null;
  quoteSuffix: string | null;
  body: string;
  resolved: boolean;
  authorName: string;
  authorEmail: string;
  isMine: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface NewComment {
  body: string;
  sectionId?: string | null;
  quote?: string | null;
  quotePrefix?: string | null;
  quoteSuffix?: string | null;
  parentId?: string | null;
}

interface RemoteComment {
  id: string;
  brief_id: string;
  parent_id: string | null;
  section_id: string | null;
  quote: string | null;
  quote_prefix: string | null;
  quote_suffix: string | null;
  body: string;
  resolved: boolean;
  author_name: string;
  author_email: string;
  is_mine: boolean;
  created_at: string;
  updated_at: string;
}

export const fromRemote = (r: RemoteComment): BriefComment => ({
  id: r.id,
  briefId: r.brief_id,
  parentId: r.parent_id,
  sectionId: r.section_id,
  quote: r.quote,
  quotePrefix: r.quote_prefix,
  quoteSuffix: r.quote_suffix,
  body: r.body,
  resolved: r.resolved,
  authorName: r.author_name,
  authorEmail: r.author_email,
  isMine: r.is_mine,
  createdAt: r.created_at,
  updatedAt: r.updated_at,
});

const csrfToken = (): string => {
  const match = document.cookie.match(/(?:^|;\s*)evidencelab_csrf=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : '';
};

const request = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken(),
      ...(init.headers || {}),
    },
  });
  if (!res.ok) {
    throw new Error(`Request failed (${res.status})`);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
};

export const listComments = async (briefId: string): Promise<BriefComment[]> => {
  const rows = await request<RemoteComment[]>(`/briefs/${briefId}/comments`);
  return rows.map(fromRemote);
};

export const createComment = async (
  briefId: string,
  comment: NewComment,
): Promise<BriefComment> => {
  const row = await request<RemoteComment>(`/briefs/${briefId}/comments`, {
    method: 'POST',
    body: JSON.stringify({
      body: comment.body,
      section_id: comment.sectionId ?? null,
      quote: comment.quote ?? null,
      quote_prefix: comment.quotePrefix ?? null,
      quote_suffix: comment.quoteSuffix ?? null,
      parent_id: comment.parentId ?? null,
    }),
  });
  return fromRemote(row);
};

export const updateComment = async (
  briefId: string,
  commentId: string,
  patch: { body?: string; resolved?: boolean },
): Promise<BriefComment> => {
  const row = await request<RemoteComment>(`/briefs/${briefId}/comments/${commentId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
  return fromRemote(row);
};

export const deleteComment = async (briefId: string, commentId: string): Promise<void> => {
  await request<void>(`/briefs/${briefId}/comments/${commentId}`, { method: 'DELETE' });
};
