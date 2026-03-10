import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import API_BASE_URL, { USER_MODULE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import { useRatings, Rating } from '../../hooks/useRatings';
import { ChatMessage, SearchResult, SearchToolCall, SourceReference, SummaryModelConfig, ThreadListItem } from '../../types/api';
import { SearchSettings } from '../../types/auth';
import { streamAssistantChat, AssistantStreamHandlers } from '../../utils/assistantStream';
import RatingModal from '../ratings/RatingModal';
import { ChatMessageList } from './ChatMessageList';
import { ChatInput } from './ChatInput';
import { ThreadSidebar } from './ThreadSidebar';

interface AssistantTabProps {
  dataSource: string;
  assistantModelConfig?: SummaryModelConfig | null;
  rerankerModel?: string | null;
  searchSettings?: Partial<SearchSettings> | null;
  exampleQueries?: string[];
  onResultClick?: (result: SearchResult) => void;
}

let messageIdCounter = 0;
const nextMessageId = () => `local-${++messageIdCounter}`;

export const AssistantTab: React.FC<AssistantTabProps> = ({
  dataSource,
  assistantModelConfig,
  rerankerModel,
  searchSettings,
  exampleQueries,
  onResultClick,
}) => {
  const auth = useAuth();
  const user = USER_MODULE ? auth.user : null;
  const isAuthenticated = !!user;

  // Chat state
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingPhase, setStreamingPhase] = useState<string>('');
  const [streamingContent, setStreamingContent] = useState('');
  const [streamingSources, setStreamingSources] = useState<SourceReference[]>([]);
  const [searchQueries, setSearchQueries] = useState<string[]>([]);
  const [toolCalls, setToolCalls] = useState<SearchToolCall[]>([]);

  // Thread state
  const [threads, setThreads] = useState<ThreadListItem[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Abort controller for cancelling stream
  const abortRef = useRef<AbortController | null>(null);

  // Refs to track latest streaming values for safe finalization
  const contentRef = useRef('');
  const sourcesRef = useRef<SourceReference[]>([]);
  const toolCallsRef = useRef<SearchToolCall[]>([]);

  // ----- Ratings -----
  const {
    ratings: chatRatings,
    submitRating: submitChatRating,
    deleteRating: deleteChatRating,
    refresh: refreshRatings,
  } = useRatings({
    ratingType: 'chat',
    referenceId: activeThreadId || '',
    enabled: isAuthenticated && !!activeThreadId,
  });

  const [ratingModalOpen, setRatingModalOpen] = useState(false);
  const [ratingModalMessageId, setRatingModalMessageId] = useState('');
  const [ratingModalInitialScore, setRatingModalInitialScore] = useState(0);

  // Build a map of message_id → score for quick lookup
  const ratingsMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const [itemId, rating] of chatRatings) {
      if (itemId) map.set(itemId, rating.score);
    }
    return map;
  }, [chatRatings]);

  const handleRequestRatingModal = useCallback((messageId: string, selectedScore: number) => {
    const existing = chatRatings.get(messageId);
    setRatingModalMessageId(messageId);
    setRatingModalInitialScore(existing?.score || selectedScore);
    setRatingModalOpen(true);
  }, [chatRatings]);

  // Load threads for authenticated users
  useEffect(() => {
    if (isAuthenticated) {
      loadThreads();
    }
  }, [isAuthenticated]);

  const loadThreads = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/assistant/threads`, {
        credentials: 'include',
      });
      if (response.ok) {
        const data = await response.json();
        setThreads(data);
      }
    } catch (err) {
      console.error('Failed to load threads:', err);
    }
  }, []);

  const loadThread = useCallback(async (threadId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/assistant/threads/${threadId}`, {
        credentials: 'include',
      });
      if (response.ok) {
        const data = await response.json();
        // Clear streaming state before loading thread
        setStreamingContent('');
        setStreamingPhase('');
        setStreamingSources([]);
        setSearchQueries([]);
        setToolCalls([]);
        setActiveThreadId(threadId);
        setMessages(
          data.messages.map((m: any) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            sources: m.sources?.citations || [],
            createdAt: m.createdAt || m.created_at,
          }))
        );
      }
    } catch (err) {
      console.error('Failed to load thread:', err);
    }
  }, []);

  const deleteThread = useCallback(async (threadId: string) => {
    try {
      const csrfMatch = document.cookie.match(/(?:^|;\s*)evidencelab_csrf=([^;]*)/);
      const headers: Record<string, string> = {};
      if (csrfMatch) {
        headers['X-CSRF-Token'] = decodeURIComponent(csrfMatch[1]);
      }
      const response = await fetch(`${API_BASE_URL}/assistant/threads/${threadId}`, {
        method: 'DELETE',
        credentials: 'include',
        headers,
      });
      if (response.ok) {
        setThreads((prev) => prev.filter((t) => t.id !== threadId));
        if (activeThreadId === threadId) {
          setActiveThreadId(null);
          setMessages([]);
        }
      }
    } catch (err) {
      console.error('Failed to delete thread:', err);
    }
  }, [activeThreadId]);

  const renameThread = useCallback(async (threadId: string, newTitle: string) => {
    try {
      const csrfMatch = document.cookie.match(/(?:^|;\s*)evidencelab_csrf=([^;]*)/);
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (csrfMatch) {
        headers['X-CSRF-Token'] = decodeURIComponent(csrfMatch[1]);
      }
      const response = await fetch(`${API_BASE_URL}/assistant/threads/${threadId}`, {
        method: 'PATCH',
        credentials: 'include',
        headers,
        body: JSON.stringify({ title: newTitle }),
      });
      if (response.ok) {
        setThreads((prev) =>
          prev.map((t) => (t.id === threadId ? { ...t, title: newTitle } : t))
        );
      }
    } catch (err) {
      console.error('Failed to rename thread:', err);
    }
  }, []);

  const handleNewChat = useCallback(() => {
    // Stop any in-progress stream
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    setActiveThreadId(null);
    setMessages([]);
    setStreamingContent('');
    setStreamingPhase('');
    setStreamingSources([]);
    setSearchQueries([]);
    setToolCalls([]);
  }, []);

  const handleSourceClick = useCallback((source: SourceReference) => {
    if (!onResultClick) return;
    onResultClick({
      chunk_id: source.chunkId,
      doc_id: source.docId,
      title: source.title,
      text: source.text,
      page_num: source.page || 1,
      score: source.score,
      headings: [],
      metadata: {},
    });
  }, [onResultClick]);

  const submitQuery = useCallback(async (query: string) => {
    if (!query.trim() || isStreaming) return;

    // Add user message
    const userMsg: ChatMessage = {
      id: nextMessageId(),
      role: 'user',
      content: query.trim(),
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');
    setIsStreaming(true);
    setStreamingPhase('');
    setStreamingContent('');
    setStreamingSources([]);
    setSearchQueries([]);
    setToolCalls([]);
    contentRef.current = '';
    sourcesRef.current = [];
    toolCallsRef.current = [];

    // Setup abort controller
    const controller = new AbortController();
    abortRef.current = controller;

    const handlers: AssistantStreamHandlers = {
      onPhase: (phase) => setStreamingPhase(phase),
      onPlan: (queries) => setSearchQueries(queries),
      onSearchStatus: (calls) => {
        toolCallsRef.current = [...toolCallsRef.current, ...calls];
        setToolCalls(toolCallsRef.current);
      },
      onToken: (fullText) => {
        contentRef.current = fullText;
        setStreamingContent(fullText);
        setStreamingPhase('');
      },
      onSources: (sources) => {
        sourcesRef.current = sources;
        setStreamingSources(sources);
      },
      onDone: (data) => {
        if (data.threadId) {
          setActiveThreadId(data.threadId);
          if (isAuthenticated) loadThreads();
        }
      },
      onError: (message) => {
        setMessages((prev) => [
          ...prev,
          {
            id: nextMessageId(),
            role: 'assistant',
            content: `Error: ${message}`,
            createdAt: new Date().toISOString(),
          },
        ]);
        setIsStreaming(false);
        setStreamingPhase('');
        setStreamingContent('');
      },
    };

    await streamAssistantChat({
      apiBaseUrl: API_BASE_URL,
      query: query.trim(),
      dataSource,
      threadId: activeThreadId,
      assistantModelConfig: assistantModelConfig,
      rerankerModel: rerankerModel,
      searchSettings: searchSettings,
      handlers,
      signal: controller.signal,
    });

    // Finalize: convert streaming state into a proper message using refs
    const finalContent = contentRef.current;
    const finalSources = sourcesRef.current;
    const finalToolCalls = toolCallsRef.current;

    if (finalContent) {
      setMessages((prev) => [
        ...prev,
        {
          id: nextMessageId(),
          role: 'assistant',
          content: finalContent,
          sources: finalSources.length > 0 ? finalSources : [],
          toolCalls: finalToolCalls.length > 0 ? finalToolCalls : undefined,
          createdAt: new Date().toISOString(),
        },
      ]);
    }

    // Clear streaming state
    contentRef.current = '';
    sourcesRef.current = [];
    toolCallsRef.current = [];
    setStreamingContent('');
    setStreamingSources([]);
    setToolCalls([]);
    setIsStreaming(false);
    setStreamingPhase('');
    abortRef.current = null;
  }, [isStreaming, dataSource, activeThreadId, assistantModelConfig, rerankerModel, searchSettings, isAuthenticated, loadThreads]);

  const handleSubmit = useCallback(() => {
    submitQuery(inputValue);
  }, [inputValue, submitQuery]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setStreamingPhase('');
  }, []);

  const hasExamples = exampleQueries && exampleQueries.length > 0;
  const hasMessages = messages.length > 0 || isStreaming;

  const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

  const chatFooterLinks = isAuthenticated ? (
    <span className="chat-footer-links">
      <button
        className="chat-history-toggle"
        onClick={() => setSidebarOpen(!sidebarOpen)}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
        Chat history
      </button>
      {hasMessages && (
        <button className="chat-history-toggle" onClick={handleNewChat}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New chat
        </button>
      )}
    </span>
  ) : undefined;

  return (
    <div className="assistant-container">
      {/* Thread history modal */}
      {isAuthenticated && sidebarOpen && (
        <div className="thread-modal-backdrop" onClick={() => setSidebarOpen(false)}>
          <div className="thread-modal" onClick={(e) => e.stopPropagation()}>
            <ThreadSidebar
              threads={threads}
              activeThreadId={activeThreadId}
              onSelectThread={(id) => { loadThread(id); setSidebarOpen(false); }}
              onNewChat={() => { handleNewChat(); setSidebarOpen(false); }}
              onDeleteThread={deleteThread}
              onRenameThread={renameThread}
              isOpen={true}
              onToggle={() => setSidebarOpen(false)}
            />
          </div>
        </div>
      )}

      {/* Main chat area */}
      <div className="assistant-chat-area">
        {!hasMessages ? (
          <div className="assistant-welcome">
            <div className="assistant-welcome-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--brand-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                <path d="M8 9h8M8 13h6" />
              </svg>
            </div>
            <h2>Research Assistant</h2>
            <p>
              Ask questions about the documents in this collection.
              The assistant will search, analyze, and synthesize findings with citations.
            </p>
            {hasExamples && (
              <div className="assistant-welcome-examples">
                <span className="assistant-examples-label">Try:</span>
                {exampleQueries.map((q) => (
                  <button
                    key={q}
                    className="assistant-example-btn"
                    onClick={() => submitQuery(q)}
                  >
                    {capitalize(q)}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <ChatMessageList
            messages={messages}
            streamingContent={streamingContent}
            streamingPhase={streamingPhase}
            streamingToolCalls={toolCalls}
            streamingSearchQueries={searchQueries}
            streamingSources={streamingSources}
            isStreaming={isStreaming}
            onSourceClick={handleSourceClick}
            searchSettings={searchSettings}
            rerankerModel={rerankerModel}
            ratingsMap={ratingsMap}
            onRequestRatingModal={handleRequestRatingModal}
            isAuthenticated={isAuthenticated}
          />
        )}

        <ChatInput
          value={inputValue}
          onChange={setInputValue}
          onSubmit={handleSubmit}
          onStop={handleStop}
          disabled={isStreaming}
          isStreaming={isStreaming}
          footerLeft={chatFooterLinks}
        />
      </div>

      {/* Rating modal */}
      {ratingModalOpen && (
        <RatingModal
          isOpen={ratingModalOpen}
          onClose={() => setRatingModalOpen(false)}
          title="Rate this response"
          initialScore={ratingModalInitialScore}
          initialComment={chatRatings.get(ratingModalMessageId)?.comment || ''}
          onSubmit={(score, comment) => {
            if (!activeThreadId) return;
            submitChatRating({
              ratingType: 'chat',
              referenceId: activeThreadId,
              itemId: ratingModalMessageId,
              score,
              comment,
            });
          }}
          onDelete={
            chatRatings.get(ratingModalMessageId)?.id
              ? () => deleteChatRating(chatRatings.get(ratingModalMessageId)!.id)
              : undefined
          }
        />
      )}
    </div>
  );
};
