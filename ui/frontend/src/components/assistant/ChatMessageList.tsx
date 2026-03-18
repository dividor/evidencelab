import React, { useRef, useEffect, useState, useCallback } from 'react';
import { ChatMessage, SearchToolCall, SourceReference } from '../../types/api';
import { SearchSettings } from '../../types/auth';
import { ChatMessageComponent } from './ChatMessage';
import { AgentStatus } from './AgentStatus';
import { ToolCallPanel } from './ToolCallPanel';

interface ChatMessageListProps {
  messages: ChatMessage[];
  streamingContent?: string;
  streamingPhase?: string;
  streamingToolCalls?: SearchToolCall[];
  streamingSearchQueries?: string[];
  streamingSources?: SourceReference[];
  isStreaming?: boolean;
  onSourceClick?: (source: SourceReference) => void;
  searchSettings?: Partial<SearchSettings> | null;
  rerankerModel?: string | null;
  /** Map of message_id → star score (0 = unrated) */
  ratingsMap?: Map<string, number>;
  /** Called when user clicks a star to open the rating modal */
  onRequestRatingModal?: (messageId: string, selectedScore: number) => void;
  /** Whether user is authenticated (ratings require auth) */
  isAuthenticated?: boolean;
}

export const ChatMessageList: React.FC<ChatMessageListProps> = ({
  messages,
  streamingContent,
  streamingPhase,
  streamingToolCalls,
  streamingSearchQueries,
  streamingSources,
  isStreaming = false,
  onSourceClick,
  searchSettings,
  rerankerModel,
  ratingsMap,
  onRequestRatingModal,
  isAuthenticated = false,
}) => {
  const listRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [userScrolled, setUserScrolled] = useState(false);
  const prevMessageCount = useRef(messages.length);

  // Detect user scroll: if they scroll up, stop auto-scrolling
  const handleScroll = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setUserScrolled(!atBottom);
  }, []);

  // When a new user message is added, always scroll to show it
  useEffect(() => {
    if (messages.length > prevMessageCount.current) {
      const lastMsg = messages[messages.length - 1];
      if (lastMsg?.role === 'user') {
        setUserScrolled(false);
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
      }
    }
    prevMessageCount.current = messages.length;
  }, [messages]);

  // Auto-scroll only if the user hasn't scrolled away
  useEffect(() => {
    if (!userScrolled) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [streamingContent, streamingPhase, userScrolled]);

  return (
    <div className="chat-message-list" ref={listRef} onScroll={handleScroll}>
      {messages.map((msg) => (
        <ChatMessageComponent
          key={msg.id}
          message={msg}
          onSourceClick={onSourceClick}
          searchSettings={searchSettings}
          rerankerModel={rerankerModel}
          ratingScore={ratingsMap?.get(msg.id) ?? 0}
          onRequestRatingModal={onRequestRatingModal}
          isAuthenticated={isAuthenticated}
        />
      ))}

      {/* Streaming status — shows queries as they complete, then synthesizing below */}
      {isStreaming && streamingPhase && !streamingContent && (
        <div className="chat-message chat-message-assistant">
          <div className="assistant-status-container">
            <AgentStatus phase={streamingPhase} searchQueries={streamingSearchQueries} toolCalls={streamingToolCalls} />
          </div>
        </div>
      )}

      {isStreaming && streamingContent && (
        <>
          {streamingToolCalls && streamingToolCalls.length > 0 && (
            <div className="chat-message chat-message-assistant">
              <ToolCallPanel
                toolCalls={streamingToolCalls}
                searchSettings={searchSettings}
                rerankerModel={rerankerModel}
              />
            </div>
          )}
          <ChatMessageComponent
            message={{
              id: 'streaming',
              role: 'assistant',
              content: streamingContent,
              sources: streamingSources,
              createdAt: new Date().toISOString(),
            }}
            onSourceClick={onSourceClick}
          />
        </>
      )}

      <div ref={bottomRef} />
    </div>
  );
};
