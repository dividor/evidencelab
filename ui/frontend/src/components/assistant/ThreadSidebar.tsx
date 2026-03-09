import React from 'react';
import { ThreadListItem } from '../../types/api';

interface ThreadSidebarProps {
  threads: ThreadListItem[];
  activeThreadId?: string | null;
  onSelectThread: (threadId: string) => void;
  onNewChat: () => void;
  onDeleteThread: (threadId: string) => void;
  isOpen: boolean;
  onToggle: () => void;
}

const formatDate = (dateStr: string): string => {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;
  return date.toLocaleDateString();
};

export const ThreadSidebar: React.FC<ThreadSidebarProps> = ({
  threads,
  activeThreadId,
  onSelectThread,
  onNewChat,
  onDeleteThread,
  isOpen,
  onToggle,
}) => {
  return (
    <>
      <button
        className="thread-sidebar-toggle"
        onClick={onToggle}
        title={isOpen ? 'Close sidebar' : 'Open sidebar'}
        aria-label={isOpen ? 'Close sidebar' : 'Open sidebar'}
      >
        {isOpen ? '\u2190' : '\u2192'}
      </button>

      <div className={`thread-sidebar ${isOpen ? 'thread-sidebar-open' : ''}`}>
        <div className="thread-sidebar-header">
          <h3>Conversations</h3>
          <button className="thread-new-btn" onClick={onNewChat} title="New conversation">
            + New
          </button>
        </div>

        <div className="thread-list">
          {threads.length === 0 && (
            <div className="thread-list-empty">
              No conversations yet. Start a new chat!
            </div>
          )}
          {threads.map((thread) => (
            <div
              key={thread.id}
              className={`thread-item ${activeThreadId === thread.id ? 'thread-item-active' : ''}`}
              onClick={() => onSelectThread(thread.id)}
            >
              <div className="thread-item-title">
                {thread.title.length > 50
                  ? `${thread.title.slice(0, 50)}...`
                  : thread.title}
              </div>
              <div className="thread-item-meta">
                <span className="thread-item-date">{formatDate(thread.updatedAt)}</span>
                <span className="thread-item-count">{thread.messageCount} msgs</span>
              </div>
              <button
                className="thread-item-delete"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteThread(thread.id);
                }}
                title="Delete conversation"
                aria-label="Delete conversation"
              >
                &times;
              </button>
            </div>
          ))}
        </div>
      </div>
    </>
  );
};
