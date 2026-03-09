import React, { useState, useCallback, useRef, useEffect } from 'react';
import API_BASE_URL, { USER_MODULE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import { ChatMessage, SourceReference, SummaryModelConfig, ThreadListItem } from '../../types/api';
import { streamAssistantChat, AssistantStreamHandlers } from '../../utils/assistantStream';
import { ChatMessageList } from './ChatMessageList';
import { ChatInput } from './ChatInput';
import { ThreadSidebar } from './ThreadSidebar';

interface AssistantTabProps {
  dataSource: string;
  assistantModelConfig?: SummaryModelConfig | null;
}

let messageIdCounter = 0;
const nextMessageId = () => `local-${++messageIdCounter}`;

export const AssistantTab: React.FC<AssistantTabProps> = ({
  dataSource,
  assistantModelConfig,
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
        setActiveThreadId(threadId);
        setMessages(
          data.messages.map((m: any) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            sources: m.sources?.citations || [],
            createdAt: m.created_at,
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
  }, []);

  const handleSubmit = useCallback(async () => {
    const query = inputValue.trim();
    if (!query || isStreaming) return;

    // Add user message
    const userMsg: ChatMessage = {
      id: nextMessageId(),
      role: 'user',
      content: query,
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');
    setIsStreaming(true);
    setStreamingPhase('');
    setStreamingContent('');
    setStreamingSources([]);
    setSearchQueries([]);

    // Setup abort controller
    const controller = new AbortController();
    abortRef.current = controller;

    const handlers: AssistantStreamHandlers = {
      onPhase: (phase) => setStreamingPhase(phase),
      onPlan: (queries) => setSearchQueries(queries),
      onSearchStatus: () => {},
      onToken: (fullText) => {
        setStreamingContent(fullText);
        setStreamingPhase('');
      },
      onSources: (sources) => setStreamingSources(sources),
      onDone: (data) => {
        // Finalize the assistant message
        setMessages((prev) => [
          ...prev,
          {
            id: data.messageId || nextMessageId(),
            role: 'assistant',
            content: '',  // Will be replaced below
            sources: [],
            createdAt: new Date().toISOString(),
          },
        ]);

        // Replace the placeholder with final content
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last.role === 'assistant') {
            return [
              ...prev.slice(0, -1),
              {
                ...last,
                content: '',  // Will be set from streamingContent
              },
            ];
          }
          return prev;
        });

        if (data.threadId) {
          setActiveThreadId(data.threadId);
          if (isAuthenticated) loadThreads();
        }

        setIsStreaming(false);
        setStreamingPhase('');
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
      query,
      dataSource,
      threadId: activeThreadId,
      assistantModelConfig: assistantModelConfig,
      handlers,
      signal: controller.signal,
    });

    // After stream completes, move streaming content to messages
    setMessages((prev) => {
      const lastMsg = prev[prev.length - 1];
      // If the last message is the assistant placeholder, update it
      if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.content) {
        return prev.slice(0, -1);  // Remove placeholder, streaming content is already shown
      }
      return prev;
    });

    // Finalize: convert streaming state into a proper message
    setStreamingContent((content) => {
      if (content) {
        setMessages((prev) => [
          ...prev,
          {
            id: nextMessageId(),
            role: 'assistant',
            content,
            sources: [],
            createdAt: new Date().toISOString(),
          },
        ]);
      }
      return '';
    });

    setStreamingSources((sources) => {
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === 'assistant' && sources.length > 0) {
          return [
            ...prev.slice(0, -1),
            { ...last, sources },
          ];
        }
        return prev;
      });
      return [];
    });

    setIsStreaming(false);
    abortRef.current = null;
  }, [inputValue, isStreaming, dataSource, activeThreadId, assistantModelConfig, isAuthenticated, loadThreads]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setStreamingPhase('');
  }, []);

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
            <div className="assistant-welcome-icon">&#128218;</div>
            <h2>Research Assistant</h2>
            <p>
              Ask questions about the documents in this collection.
              The assistant will search, analyze, and synthesize findings
              with citations.
            </p>
            <div className="assistant-welcome-examples">
              <button
                className="assistant-example-btn"
                onClick={() => setInputValue('What are the key findings on food security?')}
              >
                What are the key findings on food security?
              </button>
              <button
                className="assistant-example-btn"
                onClick={() => setInputValue('Summarize the main recommendations across all documents')}
              >
                Summarize the main recommendations
              </button>
              <button
                className="assistant-example-btn"
                onClick={() => setInputValue('What evidence exists on gender equality outcomes?')}
              >
                What evidence exists on gender equality?
              </button>
            </div>
          </div>
        ) : (
          <ChatMessageList
            messages={messages}
            streamingContent={streamingContent}
            streamingPhase={streamingPhase}
            searchQueries={searchQueries}
            streamingSources={streamingSources}
            isStreaming={isStreaming}
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
