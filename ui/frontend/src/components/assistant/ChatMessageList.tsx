import React, { useRef, useEffect } from 'react';
import { ChatMessage, SourceReference } from '../../types/api';
import { ChatMessageComponent } from './ChatMessage';
import { AgentStatus } from './AgentStatus';

interface ChatMessageListProps {
  messages: ChatMessage[];
  streamingContent?: string;
  streamingPhase?: string;
  searchQueries?: string[];
  streamingSources?: SourceReference[];
  isStreaming?: boolean;
  onSourceClick?: (source: SourceReference) => void;
}

export const ChatMessageList: React.FC<ChatMessageListProps> = ({
  messages,
  streamingContent,
  streamingPhase,
  searchQueries,
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

      {/* Streaming content */}
      {isStreaming && streamingPhase && !streamingContent && (
        <div className="chat-message chat-message-assistant">
          <div className="chat-bubble-assistant">
            <AgentStatus phase={streamingPhase} searchQueries={searchQueries} />
          </div>
        </div>
      )}

      {isStreaming && streamingContent && (
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
      )}

      <div ref={bottomRef} />
    </div>
  );
};
