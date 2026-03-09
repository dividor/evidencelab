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

/* SVG icons */
const ChevronLeftIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10 12L6 8L10 4" />
  </svg>
);

const ChevronRightIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 4L10 8L6 12" />
  </svg>
);

const PlusIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <path d="M7 1V13M1 7H13" />
  </svg>
);

const TrashIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M1.5 3.5H12.5M5 3.5V2C5 1.45 5.45 1 6 1H8C8.55 1 9 1.45 9 2V3.5M3 3.5L3.5 12C3.5 12.55 3.95 13 4.5 13H9.5C10.05 13 10.5 12.55 10.5 12L11 3.5" />
  </svg>
);

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
    <div className="thread-sidebar-wrapper">
      <button
        className="thread-sidebar-toggle"
        onClick={onToggle}
        title={isOpen ? 'Close sidebar' : 'Open sidebar'}
        aria-label={isOpen ? 'Close sidebar' : 'Open sidebar'}
      >
        {isOpen ? <ChevronLeftIcon /> : <ChevronRightIcon />}
      </button>

      <div className={`thread-sidebar ${isOpen ? 'thread-sidebar-open' : ''}`}>
        <div className="thread-sidebar-header">
          <h3>Conversations</h3>
          <button className="thread-new-btn" onClick={onNewChat} title="New conversation">
            <PlusIcon />
            <span>New</span>
          </button>
        </div>

        <div className="thread-list">
          {threads.length === 0 && (
            <div className="thread-list-empty">
              No conversations yet.
              <br />
              Start a new chat!
            </div>
          )}
          {threads.map((thread) => (
            <div
              key={thread.id}
              className={`thread-item ${activeThreadId === thread.id ? 'thread-item-active' : ''}`}
              onClick={() => onSelectThread(thread.id)}
            >
              <div className="thread-item-title">{thread.title}</div>
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
                <TrashIcon />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
