import React, { useRef, useEffect, useCallback } from 'react';

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  disabled?: boolean;
  isStreaming?: boolean;
  placeholder?: string;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  value,
  onChange,
  onSubmit,
  onStop,
  disabled = false,
  isStreaming = false,
  placeholder = 'Ask a research question...',
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [value]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!disabled && value.trim()) {
          onSubmit();
        }
      }
    },
    [disabled, value, onSubmit]
  );

  return (
    <div className="chat-input-container">
      <div className="chat-input-wrapper">
        <textarea
          ref={textareaRef}
          className="chat-input-textarea"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
        />
        <div className="chat-input-actions">
          {isStreaming && (
            <button
              className="chat-input-stop-btn"
              onClick={onStop}
              title="Stop generating"
              aria-label="Stop generating"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                <rect x="3" y="3" width="10" height="10" rx="1" />
              </svg>
            </button>
          )}
          <button
            className="chat-input-send-btn"
            onClick={onSubmit}
            disabled={disabled || !value.trim()}
            title="Send message"
            aria-label="Send message"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <path d="M2.5 1.5L14 8L2.5 14.5V9.5L10 8L2.5 6.5V1.5Z" />
            </svg>
          </button>
        </div>
      </div>
      <div className="chat-input-hint">
        Press Enter to send, Shift+Enter for new line
      </div>
    </div>
  );
};
