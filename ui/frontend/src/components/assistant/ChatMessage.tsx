import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChatMessage as ChatMessageType, SourceReference } from '../../types/api';
import { SearchSettings } from '../../types/auth';
import { CitedMarkdown, CitedReferences } from '../citations/CitedContent';
import StarRating from '../ratings/StarRating';
import { ToolCallPanel } from './ToolCallPanel';

interface ChatMessageProps {
  message: ChatMessageType;
  onSourceClick?: (source: SourceReference) => void;
  searchSettings?: Partial<SearchSettings> | null;
  rerankerModel?: string | null;
  /** Current star score for this message (0 = unrated) */
  ratingScore?: number;
  /** Called when user clicks a star to open the rating modal */
  onRequestRatingModal?: (messageId: string, selectedScore: number) => void;
  /** Whether user is authenticated (ratings require auth) */
  isAuthenticated?: boolean;
}

export const ChatMessageComponent: React.FC<ChatMessageProps> = ({
  message,
  onSourceClick,
  searchSettings,
  rerankerModel,
  ratingScore = 0,
  onRequestRatingModal,
  isAuthenticated = false,
}) => {
  const isUser = message.role === 'user';
  const hasSources = !isUser && message.sources && message.sources.length > 0;
  const hasIndexedSources = hasSources && message.sources!.some((s) => s.index != null);
  const showRating = !isUser && isAuthenticated && onRequestRatingModal && message.content;

  return (
    <div className={`chat-message ${isUser ? 'chat-message-user' : 'chat-message-assistant'}`}>
      {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
        <ToolCallPanel
          toolCalls={message.toolCalls}
          searchSettings={searchSettings}
          rerankerModel={rerankerModel}
        />
      )}

      {isUser ? (
        <div className="chat-bubble-user">
          <div className="chat-message-text">{message.content}</div>
        </div>
      ) : (
        <div className="assistant-response">
          {hasIndexedSources ? (
            <CitedMarkdown
              content={message.content}
              sources={message.sources!}
              onSourceClick={onSourceClick}
            />
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          )}
        </div>
      )}

      {/* References + rating row */}
      {(hasIndexedSources || showRating) && (
        <div className="chat-message-footer">
          {hasIndexedSources ? (
            <CitedReferences
              content={message.content}
              sources={message.sources!}
              onSourceClick={onSourceClick}
            />
          ) : (
            <span />
          )}
          {showRating && (
            <StarRating
              score={ratingScore}
              onRequestModal={(score) => onRequestRatingModal!(message.id, score)}
              size={13}
            />
          )}
        </div>
      )}
    </div>
  );
};
