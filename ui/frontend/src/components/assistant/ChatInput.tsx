import React, { useRef, useEffect, useCallback } from 'react';

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  disabled?: boolean;
  isStreaming?: boolean;
  placeholder?: string;
  footerLeft?: React.ReactNode;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  value,
  onChange,
  onSubmit,
  onStop,
  disabled = false,
  isStreaming = false,
  placeholder = 'Ask a research question...',
  footerLeft,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea (also triggers when becoming visible after display:none)
  const resizeTextarea = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, []);

  useEffect(() => {
    resizeTextarea();
  }, [value, resizeTextarea]);

  // Re-measure when the component becomes visible (e.g. tab switch from display:none)
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const observer = new ResizeObserver(() => {
      // Defer to next frame to avoid ResizeObserver loop errors
      requestAnimationFrame(resizeTextarea);
    });
    observer.observe(textarea);
    return () => observer.disconnect();
  }, [resizeTextarea]);

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
          rows={3}
        />
        <div className="chat-input-actions">
          {isStreaming ? (
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
          ) : (
            <button
              className="chat-input-send-btn"
              onClick={onSubmit}
              disabled={!value.trim()}
              title="Send message"
              aria-label="Send message"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                <path d="M2.5 1.5L14 8L2.5 14.5V9.5L10 8L2.5 6.5V1.5Z" />
              </svg>
            </button>
          )}
        </div>
      </div>
      <div className="chat-input-below">
        {footerLeft || <span />}
        <span className="chat-input-hint">
          AI can, and will, gleefully make mistakes. Check all responses
        </span>
      </div>
    </div>
  );
};
