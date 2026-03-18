import React, { useState, useMemo, useRef, useEffect } from 'react';
import { ThreadListItem } from '../../types/api';

interface ThreadSidebarProps {
  threads: ThreadListItem[];
  activeThreadId?: string | null;
  onSelectThread: (threadId: string) => void;
  onNewChat: () => void;
  onDeleteThread: (threadId: string) => void;
  onRenameThread: (threadId: string, newTitle: string) => void;
  isOpen: boolean;
  onToggle: () => void;
}

const formatDate = (dateStr: string): string => {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  if (diffDays === 0) return `Today ${time}`;
  if (diffDays === 1) return `Yesterday ${time}`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
};

/* SVG icons */
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

const PencilIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10 1.5L12.5 4L4.5 12H2V9.5L10 1.5Z" />
  </svg>
);

const CloseIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <path d="M3 3L11 11M11 3L3 11" />
  </svg>
);

export const ThreadSidebar: React.FC<ThreadSidebarProps> = ({
  threads,
  activeThreadId,
  onSelectThread,
  onNewChat,
  onDeleteThread,
  onRenameThread,
  isOpen,
  onToggle,
}) => {
  const [search, setSearch] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const editInputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    if (!search.trim()) return threads;
    const q = search.toLowerCase();
    return threads.filter((t) => t.title.toLowerCase().includes(q));
  }, [threads, search]);

  // Focus input when editing starts
  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const startEditing = (thread: ThreadListItem, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(thread.id);
    setEditValue(thread.title);
  };

  const commitRename = () => {
    if (editingId && editValue.trim()) {
      onRenameThread(editingId, editValue.trim());
    }
    setEditingId(null);
    setEditValue('');
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditValue('');
  };

  const handleEditKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitRename();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEditing();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="thread-sidebar thread-sidebar-open">
      <div className="thread-sidebar-header">
        <h3>Chat History</h3>
        <div className="thread-sidebar-header-actions">
          <button className="thread-new-btn" onClick={onNewChat} title="New conversation">
            <PlusIcon />
            <span>New</span>
          </button>
          <button className="thread-sidebar-close" onClick={onToggle} title="Close" aria-label="Close">
            <CloseIcon />
          </button>
        </div>
      </div>

      {threads.length > 3 && (
        <div className="thread-search">
          <input
            type="text"
            className="thread-search-input"
            placeholder="Search conversations..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      )}

      <div className="thread-list">
        {filtered.length === 0 && !search && (
          <div className="thread-list-empty">
            No conversations yet.
            <br />
            Start a new chat!
          </div>
        )}
        {filtered.length === 0 && search && (
          <div className="thread-list-empty">
            No matching conversations.
          </div>
        )}
        {filtered.map((thread) => (
          <div
            key={thread.id}
            className={`thread-item ${activeThreadId === thread.id ? 'thread-item-active' : ''}`}
            onClick={() => editingId !== thread.id && onSelectThread(thread.id)}
          >
            {editingId === thread.id ? (
              <input
                ref={editInputRef}
                className="thread-item-rename-input"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onKeyDown={handleEditKeyDown}
                onBlur={commitRename}
                onClick={(e) => e.stopPropagation()}
                maxLength={500}
              />
            ) : (
              <div className="thread-item-title">{thread.title}</div>
            )}
            <div className="thread-item-meta">
              <span className="thread-item-date">{formatDate(thread.updatedAt)}</span>
              <span className="thread-item-count">{thread.messageCount} msgs</span>
            </div>
            <div className="thread-item-actions">
              <button
                className="thread-item-action thread-item-rename"
                onClick={(e) => startEditing(thread, e)}
                title="Rename conversation"
                aria-label="Rename conversation"
              >
                <PencilIcon />
              </button>
              <button
                className="thread-item-action thread-item-delete"
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
          </div>
        ))}
      </div>
    </div>
  );
};
