import React, { useRef, useEffect } from 'react';
import { ChatMessage, SearchToolCall, SourceReference } from '../../types/api';
import { ChatMessageComponent } from './ChatMessage';
import { AgentStatus } from './AgentStatus';
import { ToolCallPanel } from './ToolCallPanel';

interface ChatMessageListProps {
  messages: ChatMessage[];
  streamingContent?: string;
  streamingPhase?: string;
  searchQueries?: string[];
  streamingToolCalls?: SearchToolCall[];
  streamingSources?: SourceReference[];
  isStreaming?: boolean;
  onSourceClick?: (source: SourceReference) => void;
}

export const ChatMessageList: React.FC<ChatMessageListProps> = ({
  messages,
  streamingContent,
  streamingPhase,
  searchQueries,
  streamingToolCalls,
  streamingSources,
  isStreaming = false,
  onSourceClick,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent, streamingPhase]);

  return (
    <div className="chat-message-list">
      {messages.map((msg) => (
        <ChatMessageComponent
          key={msg.id}
          message={msg}
          onSourceClick={onSourceClick}
        />
      ))}

      {/* Streaming status (searching / planning phases) */}
      {isStreaming && streamingPhase && !streamingContent && (
        <div className="chat-message chat-message-assistant">
          <div className="assistant-status-container">
            <AgentStatus phase={streamingPhase} searchQueries={searchQueries} />
            {streamingToolCalls && streamingToolCalls.length > 0 && (
              <ToolCallPanel toolCalls={streamingToolCalls} defaultExpanded />
            )}
          </div>
        </div>
      )}

      {isStreaming && streamingContent && (
        <>
          {streamingToolCalls && streamingToolCalls.length > 0 && (
            <div className="chat-message chat-message-assistant">
              <ToolCallPanel toolCalls={streamingToolCalls} />
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
