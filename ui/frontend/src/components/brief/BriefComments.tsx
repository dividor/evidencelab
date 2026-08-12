// The comment rail beside a brief: one card per thread, with replies, edit,
// resolve and delete. Anyone who can see the brief can comment; a comment can
// be edited only by its author, and resolved by its author or the brief owner.

import React, { useState } from 'react';
import { BriefComment } from './briefCommentsApi';
import { CommentThread, UseBriefCommentsReturn } from './useBriefComments';

const when = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString();
};

const initialsOf = (name: string): string =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .filter(Boolean)
    .join('')
    .slice(0, 2)
    .toUpperCase();

/** One comment: header, body (or edit box) and its actions. */
const CommentBody: React.FC<{
  comment: BriefComment;
  canResolve: boolean;
  onEdit: (body: string) => void;
  onDelete: () => void;
}> = ({ comment, canResolve, onEdit, onDelete }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(comment.body);

  const save = (): void => {
    const body = draft.trim();
    if (body && body !== comment.body) onEdit(body);
    setEditing(false);
  };

  return (
    <div className="brief-comment">
      <div className="brief-comment-head">
        <span className="brief-comment-avatar">{initialsOf(comment.authorName)}</span>
        <span className="brief-comment-author">{comment.authorName}</span>
        <span className="brief-comment-when">{when(comment.createdAt)}</span>
      </div>
      {editing ? (
        <div className="brief-comment-edit">
          <textarea
            className="brief-comment-input"
            value={draft}
            rows={3}
            onChange={(e) => setDraft(e.target.value)}
            aria-label="Edit comment"
          />
          <div className="brief-comment-actions">
            <button className="brief-comment-btn-primary" onClick={save}>
              Save
            </button>
            <button
              className="brief-comment-btn"
              onClick={() => {
                setDraft(comment.body);
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="brief-comment-text">{comment.body}</div>
          {(comment.isMine || canResolve) && (
            <div className="brief-comment-actions">
              {comment.isMine && (
                <button className="brief-comment-btn" onClick={() => setEditing(true)}>
                  Edit
                </button>
              )}
              <button className="brief-comment-btn brief-comment-btn-danger" onClick={onDelete}>
                Delete
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};

/** A thread: the opening comment, its replies, and a reply box. */
const ThreadCard: React.FC<{
  thread: CommentThread;
  comments: UseBriefCommentsReturn;
  canResolve: boolean;
  active: boolean;
  onSelect: () => void;
}> = ({ thread, comments, canResolve, active, onSelect }) => {
  const [reply, setReply] = useState('');
  const { root, replies } = thread;

  const sendReply = (): void => {
    const body = reply.trim();
    if (!body) return;
    void comments.add({ body, parentId: root.id, sectionId: root.sectionId });
    setReply('');
  };

  return (
    <div
      className={`brief-comment-thread${root.resolved ? ' brief-comment-resolved' : ''}${
        active ? ' brief-comment-thread-active' : ''
      }`}
      onClick={onSelect}
      role="presentation"
    >
      {root.quote && <div className="brief-comment-quote">“{root.quote}”</div>}
      <CommentBody
        comment={root}
        canResolve={canResolve}
        onEdit={(body) => void comments.edit(root.id, body)}
        onDelete={() => void comments.remove(root.id)}
      />
      {replies.map((r) => (
        <div className="brief-comment-reply" key={r.id}>
          <CommentBody
            comment={r}
            canResolve={canResolve}
            onEdit={(body) => void comments.edit(r.id, body)}
            onDelete={() => void comments.remove(r.id)}
          />
        </div>
      ))}
      <div className="brief-comment-foot">
        <textarea
          className="brief-comment-input"
          value={reply}
          rows={2}
          placeholder="Reply…"
          aria-label="Reply to comment"
          onChange={(e) => setReply(e.target.value)}
        />
        <div className="brief-comment-actions">
          <button
            className="brief-comment-btn-primary"
            onClick={sendReply}
            disabled={!reply.trim()}
          >
            Reply
          </button>
          {(root.isMine || canResolve) && (
            <button
              className="brief-comment-btn"
              onClick={() => void comments.setResolved(root.id, !root.resolved)}
            >
              {root.resolved ? 'Reopen' : 'Resolve'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export const BriefComments: React.FC<{
  comments: UseBriefCommentsReturn;
  canResolve: boolean;
  activeThreadId: string | null;
  onSelectThread: (id: string | null) => void;
}> = ({ comments, canResolve, activeThreadId, onSelectThread }) => {
  const [showResolved, setShowResolved] = useState(false);
  const visible = showResolved
    ? comments.threads
    : comments.threads.filter((t) => !t.root.resolved);
  const resolvedCount = comments.threads.length - comments.threads.filter((t) => !t.root.resolved).length;

  return (
    <aside className="brief-comments-rail" aria-label="Comments">
      <div className="brief-comments-head">
        <span className="brief-comments-title">
          Comments{comments.openCount ? ` (${comments.openCount})` : ''}
        </span>
        {resolvedCount > 0 && (
          <label className="brief-comments-toggle">
            <input
              type="checkbox"
              checked={showResolved}
              onChange={(e) => setShowResolved(e.target.checked)}
            />
            Show resolved
          </label>
        )}
      </div>
      {comments.error && <div className="brief-error">{comments.error}</div>}
      {visible.length === 0 ? (
        <div className="brief-comments-empty">
          Select text in the brief and choose “Comment” to start a thread.
        </div>
      ) : (
        visible.map((thread) => (
          <ThreadCard
            key={thread.root.id}
            thread={thread}
            comments={comments}
            canResolve={canResolve}
            active={activeThreadId === thread.root.id}
            onSelect={() => onSelectThread(thread.root.id)}
          />
        ))
      )}
    </aside>
  );
};


/**
 * Modal for a new comment on a selected passage. Shown after the reader
 * highlights text in the brief and confirms they want to comment on it.
 */
export const BriefCommentComposer: React.FC<{
  quote: string;
  onSubmit: (body: string) => void;
  onCancel: () => void;
}> = ({ quote, onSubmit, onCancel }) => {
  const [body, setBody] = useState('');
  return (
    <div className="brief-modal-overlay" onClick={onCancel} role="presentation">
      <div
        className="brief-modal bc-modal brief-comment-modal"
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <div className="brief-modal-head">
          <div>
            <div className="brief-modal-title">Add a comment</div>
            <div className="brief-modal-sub">
              Anyone the brief is shared with can see and reply to it.
            </div>
          </div>
          <button className="brief-modal-close" onClick={onCancel} aria-label="Close">
            ×
          </button>
        </div>
        <div className="bc-modal-body">
          <div className="brief-comment-quote">“{quote}”</div>
          <textarea
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
            className="brief-comment-input"
            rows={4}
            value={body}
            placeholder="What should change, or what needs checking?"
            aria-label="Comment"
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="bc-modal-actions">
            <button
              className="brief-btn brief-btn-primary"
              disabled={!body.trim()}
              onClick={() => onSubmit(body.trim())}
            >
              Comment
            </button>
            <button className="brief-btn brief-btn-secondary" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
