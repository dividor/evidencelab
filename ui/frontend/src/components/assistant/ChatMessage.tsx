import React, { useState, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChatMessage as ChatMessageType, SourceReference } from '../../types/api';
import { SearchSettings } from '../../types/auth';
import { ToolCallPanel } from './ToolCallPanel';

interface ChatMessageProps {
  message: ChatMessageType;
  onSourceClick?: (source: SourceReference) => void;
  searchSettings?: Partial<SearchSettings> | null;
  rerankerModel?: string | null;
}

// ---------------------------------------------------------------------------
// Citation parsing helpers (mirrors AiSummaryWithCitations patterns)
// ---------------------------------------------------------------------------

const CITATION_REGEX = /\[(\d+(?:,\s*\d+)*)\]/g;

const parseCitationNumbers = (raw: string): number[] =>
  raw.split(',').map((s) => parseInt(s.trim(), 10)).filter((n) => !isNaN(n));

/** Extract all unique cited numbers from the response text. */
const extractCitedNumbers = (text: string): number[] => {
  const cited = new Set<number>();
  let m: RegExpExecArray | null;
  const re = new RegExp(CITATION_REGEX.source, 'g');
  while ((m = re.exec(text)) !== null) {
    parseCitationNumbers(m[1]).forEach((n) => cited.add(n));
  }
  return Array.from(cited).sort((a, b) => a - b);
};

// ---------------------------------------------------------------------------
// Inline citation component
// ---------------------------------------------------------------------------

const InlineCitation: React.FC<{
  num: number;
  source?: SourceReference;
  onClick?: (source: SourceReference) => void;
}> = ({ num, source, onClick }) => {
  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    if (source && onClick) onClick(source);
  };
  return (
    <a
      href="#"
      className="ai-summary-citation"
      onClick={handleClick}
      title={source?.title || `Source ${num}`}
    >
      {num}
    </a>
  );
};

// ---------------------------------------------------------------------------
// Markdown renderer that converts [N] patterns into clickable citations
// ---------------------------------------------------------------------------

const CitedMarkdown: React.FC<{
  content: string;
  sources: SourceReference[];
  onSourceClick?: (source: SourceReference) => void;
}> = ({ content, sources, onSourceClick }) => {
  // Build a lookup: global_index -> source
  const sourceByIndex = useMemo(() => {
    const map = new Map<number, SourceReference>();
    sources.forEach((s) => {
      if (s.index != null) map.set(s.index, s);
    });
    return map;
  }, [sources]);

  const components = useMemo(() => ({
    p: ({ children, ...props }: any) => (
      <p {...props}>{transformChildren(children, sourceByIndex, onSourceClick)}</p>
    ),
    li: ({ children, ...props }: any) => (
      <li {...props}>{transformChildren(children, sourceByIndex, onSourceClick)}</li>
    ),
    strong: ({ children, ...props }: any) => (
      <strong {...props}>{transformChildren(children, sourceByIndex, onSourceClick)}</strong>
    ),
    em: ({ children, ...props }: any) => (
      <em {...props}>{transformChildren(children, sourceByIndex, onSourceClick)}</em>
    ),
  }), [sourceByIndex, onSourceClick]);

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  );
};

/** Recursively walk React children and replace citation text patterns. */
function transformChildren(
  children: React.ReactNode,
  sourceByIndex: Map<number, SourceReference>,
  onSourceClick?: (source: SourceReference) => void,
): React.ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child !== 'string') return child;
    return replaceCitations(child, sourceByIndex, onSourceClick);
  });
}

/** Split a text string on citation patterns and return mixed text + buttons. */
function replaceCitations(
  text: string,
  sourceByIndex: Map<number, SourceReference>,
  onSourceClick?: (source: SourceReference) => void,
): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const re = new RegExp(CITATION_REGEX.source, 'g');
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const nums = parseCitationNumbers(match[1]);
    // Group consecutive citations by document (same as AiSummaryWithCitations)
    const groups: number[][] = [];
    for (const n of nums) {
      const docId = sourceByIndex.get(n)?.docId;
      const prev = groups.length > 0 ? groups[groups.length - 1] : null;
      const prevDocId = prev && sourceByIndex.get(prev[0])?.docId;
      if (prev && docId && docId === prevDocId) {
        prev.push(n);
      } else {
        groups.push([n]);
      }
    }
    parts.push(
      <span key={`cite-${match.index}`} className="citation-group">
        {groups.map((group, gi) => (
          <React.Fragment key={`g-${gi}`}>
            {gi > 0 && ' '}
            <span className="citation-doc-group">
              {group.map((n, i) => (
                <React.Fragment key={n}>
                  {i > 0 && <span>, </span>}
                  <InlineCitation num={n} source={sourceByIndex.get(n)} onClick={onSourceClick} />
                </React.Fragment>
              ))}
            </span>
          </React.Fragment>
        ))}
      </span>
    );
    lastIndex = re.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length === 1 ? parts[0] : <>{parts}</>;
}

// ---------------------------------------------------------------------------
// Collapsible references section (grouped by document)
// ---------------------------------------------------------------------------

interface DocGroup {
  title: string;
  docId: string;
  indices: number[];
  page?: number;
}

const AssistantReferences: React.FC<{
  content: string;
  sources: SourceReference[];
  onSourceClick?: (source: SourceReference) => void;
}> = ({ content, sources, onSourceClick }) => {
  const [expanded, setExpanded] = useState(false);

  const groups = useMemo(() => {
    const cited = extractCitedNumbers(content);
    const sourceByIndex = new Map<number, SourceReference>();
    sources.forEach((s) => {
      if (s.index != null) sourceByIndex.set(s.index, s);
    });

    const groupMap = new Map<string, DocGroup>();
    const order: string[] = [];

    cited.forEach((num) => {
      const src = sourceByIndex.get(num);
      if (!src) return;
      const key = src.docId || src.title;
      if (!groupMap.has(key)) {
        groupMap.set(key, {
          title: src.title,
          docId: src.docId,
          indices: [],
          page: src.page,
        });
        order.push(key);
      }
      groupMap.get(key)!.indices.push(num);
    });

    return order.map((k) => groupMap.get(k)!);
  }, [content, sources]);

  if (groups.length === 0) return null;

  return (
    <div className="ai-summary-references">
      <button
        className="assistant-refs-toggle"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="assistant-refs-toggle-icon">{expanded ? '\u25BE' : '\u25B8'}</span>
        References ({groups.length} documents)
      </button>
      {expanded && (
        <div className="assistant-refs-list">
          {groups.map((group) => (
            <div key={group.docId || group.title} className="ai-summary-ref-group">
              {group.title}
              {' | '}
              {group.indices.map((idx, i) => (
                <React.Fragment key={idx}>
                  {i > 0 && ' '}
                  <a
                    href="#"
                    className="ai-summary-ref-link"
                    onClick={(e) => {
                      e.preventDefault();
                      const src = sources.find((s) => s.index === idx);
                      if (src && onSourceClick) onSourceClick(src);
                    }}
                  >
                    <span className="citation-doc-group">
                      <span className="ai-summary-citation">{idx}</span>
                    </span>
                    {group.page ? ` p.${group.page}` : ''}
                  </a>
                </React.Fragment>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const ChatMessageComponent: React.FC<ChatMessageProps> = ({
  message,
  onSourceClick,
  searchSettings,
  rerankerModel,
}) => {
  const isUser = message.role === 'user';
  const hasSources = !isUser && message.sources && message.sources.length > 0;
  const hasIndexedSources = hasSources && message.sources!.some((s) => s.index != null);

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
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          )}
        </div>
      )}

      {/* Collapsible references section */}
      {hasIndexedSources && (
        <AssistantReferences
          content={message.content}
          sources={message.sources!}
          onSourceClick={onSourceClick}
        />
      )}
    </div>
  );
};
