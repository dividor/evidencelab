import React, { useState, useCallback, useRef, useEffect } from 'react';
import API_BASE_URL, { USER_MODULE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import { ChatMessage, SearchToolCall, SourceReference, SummaryModelConfig, ThreadListItem } from '../../types/api';
import { streamAssistantChat, AssistantStreamHandlers } from '../../utils/assistantStream';
import { ChatMessageList } from './ChatMessageList';
import { ChatInput } from './ChatInput';
import { ThreadSidebar } from './ThreadSidebar';

interface AssistantTabProps {
  dataSource: string;
  assistantModelConfig?: SummaryModelConfig | null;
  exampleQueries?: string[];
}

const DEFAULT_EXAMPLES = [
  'What are the key findings across all documents?',
  'Summarize the main recommendations',
  'What themes emerge from the evidence?',
];

let messageIdCounter = 0;
const nextMessageId = () => `local-${++messageIdCounter}`;

export const AssistantTab: React.FC<AssistantTabProps> = ({
  dataSource,
  assistantModelConfig,
  exampleQueries,
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
    console.log('Source clicked:', source.title, source);
  }, []);

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

    // Setup abort controller
    const controller = new AbortController();
    abortRef.current = controller;

    const handlers: AssistantStreamHandlers = {
      onPhase: (phase) => setStreamingPhase(phase),
      onPlan: (queries) => setSearchQueries(queries),
      onSearchStatus: (calls) => setToolCalls((prev) => [...prev, ...calls]),
      onToken: (fullText) => {
        setStreamingContent(fullText);
        setStreamingPhase('');
      },
      onSources: (sources) => setStreamingSources(sources),
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

    // Finalize: convert streaming state into a proper message
    setStreamingContent((content) => {
      if (content) {
        setStreamingSources((sources) => {
          setToolCalls((tc) => {
            setMessages((prev) => [
              ...prev,
              {
                id: nextMessageId(),
                role: 'assistant',
                content,
                sources: sources.length > 0 ? sources : [],
                toolCalls: tc.length > 0 ? tc : undefined,
                createdAt: new Date().toISOString(),
              },
            ]);
            return [];
          });
          return [];
        });
      }
      return '';
    });

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

  const queries = exampleQueries && exampleQueries.length > 0 ? exampleQueries : DEFAULT_EXAMPLES;
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
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--primary-500)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                <path d="M8 9h8M8 13h6" />
              </svg>
            </div>
            <h2>Research Assistant</h2>
            <p>
              Ask questions about the documents in this collection.
              The assistant will search, analyze, and synthesize findings with citations.
            </p>
            <div className="assistant-welcome-examples">
              {queries.map((q) => (
                <button
                  key={q}
                  className="assistant-example-btn"
                  onClick={() => submitQuery(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ChatMessageList
            messages={messages}
            streamingContent={streamingContent}
            streamingPhase={streamingPhase}
            searchQueries={searchQueries}
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
