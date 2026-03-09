import React, { useState, useCallback, useRef, useEffect } from 'react';
import API_BASE_URL, { USER_MODULE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import { ChatMessage, SearchResult, SearchToolCall, SourceReference, SummaryModelConfig, ThreadListItem } from '../../types/api';
import { streamAssistantChat, AssistantStreamHandlers } from '../../utils/assistantStream';
import { ChatMessageList } from './ChatMessageList';
import { ChatInput } from './ChatInput';
import { ThreadSidebar } from './ThreadSidebar';

interface AssistantTabProps {
  dataSource: string;
  assistantModelConfig?: SummaryModelConfig | null;
  exampleQueries?: string[];
  onResultClick?: (result: SearchResult) => void;
}

let messageIdCounter = 0;
const nextMessageId = () => `local-${++messageIdCounter}`;

export const AssistantTab: React.FC<AssistantTabProps> = ({
  dataSource,
  assistantModelConfig,
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

  const handleNewChat = useCallback(() => {
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
  }, [isStreaming, dataSource, activeThreadId, assistantModelConfig, isAuthenticated, loadThreads]);

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

  return (
    <div className="assistant-container">
      {/* Sidebar for authenticated users */}
      {isAuthenticated && (
        <ThreadSidebar
          threads={threads}
          activeThreadId={activeThreadId}
          onSelectThread={loadThread}
          onNewChat={handleNewChat}
          onDeleteThread={deleteThread}
          isOpen={sidebarOpen}
          onToggle={() => setSidebarOpen(!sidebarOpen)}
        />
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
                {exampleQueries.map((q) => (
                  <button
                    key={q}
                    className="assistant-example-btn"
                    onClick={() => submitQuery(q)}
                  >
                    {q}
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
            streamingSources={streamingSources}
            isStreaming={isStreaming}
            onSourceClick={handleSourceClick}
          />
        )}

        <ChatInput
          value={inputValue}
          onChange={setInputValue}
          onSubmit={handleSubmit}
          onStop={handleStop}
          disabled={isStreaming}
          isStreaming={isStreaming}
        />
      </div>
    </div>
  );
};
