import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChatMessage as ChatMessageType, SourceReference } from '../../types/api';

interface ChatMessageProps {
  message: ChatMessageType;
  onSourceClick?: (source: SourceReference) => void;
}

const SourceChip: React.FC<{
  source: SourceReference;
  index: number;
  onClick?: (source: SourceReference) => void;
}> = ({ source, index, onClick }) => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="source-chip-container">
      <button
        className="source-chip"
        onClick={() => {
          if (onClick) onClick(source);
          setExpanded(!expanded);
        }}
        title={source.title}
      >
        [{index + 1}] {source.title.length > 40 ? `${source.title.slice(0, 40)}...` : source.title}
      </button>
      {expanded && (
        <div className="source-preview">
          <div className="source-preview-title">{source.title}</div>
          <div className="source-preview-text">{source.text}</div>
          {source.page && (
            <div className="source-preview-page">Page {source.page}</div>
          )}
          <div className="source-preview-score">
            Relevance: {(source.score * 100).toFixed(0)}%
          </div>
        </div>
      )}
    </div>
  );
};

export const ChatMessageComponent: React.FC<ChatMessageProps> = ({ message, onSourceClick }) => {
  const isUser = message.role === 'user';

  return (
    <div className={`chat-message ${isUser ? 'chat-message-user' : 'chat-message-assistant'}`}>
      <div className={`chat-message-bubble ${isUser ? 'chat-bubble-user' : 'chat-bubble-assistant'}`}>
        {isUser ? (
          <div className="chat-message-text">{message.content}</div>
        ) : (
          <div className="chat-message-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
      </div>
      {!isUser && message.sources && message.sources.length > 0 && (
        <div className="chat-message-sources">
          <div className="chat-sources-label">Sources</div>
          <div className="chat-sources-list">
            {message.sources.map((source, i) => (
              <SourceChip
                key={source.chunkId || i}
                source={source}
                index={i}
                onClick={onSourceClick}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
