import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

jest.mock('react-markdown', () => {
  const React = jest.requireActual('react');
  return {
    __esModule: true,
    default: ({ children }: { children: React.ReactNode }) =>
      React.createElement('div', { 'data-testid': 'markdown' }, children),
  };
});
jest.mock('remark-gfm', () => ({
  __esModule: true,
  default: () => {},
}));
jest.mock('../components/ratings/StarRating', () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock('../components/assistant/ToolCallPanel', () => ({
  __esModule: true,
  ToolCallPanel: () => null,
}));

import { ChatMessageComponent } from '../components/assistant/ChatMessage';
import { ChatMessage, SourceReference } from '../types/api';

const makeUserMessage = (overrides?: Partial<ChatMessage>): ChatMessage => ({
  id: 'msg-1',
  role: 'user',
  content: 'What is food security?',
  createdAt: new Date().toISOString(),
  ...overrides,
});

const makeAssistantMessage = (overrides?: Partial<ChatMessage>): ChatMessage => ({
  id: 'msg-2',
  role: 'assistant',
  content: 'Food security refers to...',
  createdAt: new Date().toISOString(),
  ...overrides,
});

const makeSources = (): SourceReference[] => [
  {
    chunkId: 'c1',
    docId: 'd1',
    title: 'Global Food Security Report 2024',
    text: 'Evidence shows that food security has improved...',
    score: 0.92,
    page: 15,
    index: 1,
  },
  {
    chunkId: 'c2',
    docId: 'd2',
    title: 'Nutrition Analysis',
    text: 'Malnutrition rates have decreased...',
    score: 0.85,
    index: 2,
  },
];

const makeSourcesWithoutIndex = (): SourceReference[] => [
  {
    chunkId: 'c1',
    docId: 'd1',
    title: 'Global Food Security Report 2024',
    text: 'Evidence shows that food security has improved...',
    score: 0.92,
    page: 15,
  },
];

describe('ChatMessageComponent', () => {
  describe('User messages', () => {
    test('renders user message content', () => {
      render(<ChatMessageComponent message={makeUserMessage()} />);
      expect(screen.getByText('What is food security?')).toBeInTheDocument();
    });

    test('applies user message styling class', () => {
      const { container } = render(<ChatMessageComponent message={makeUserMessage()} />);
      expect(container.querySelector('.chat-message-user')).toBeInTheDocument();
      expect(container.querySelector('.chat-bubble-user')).toBeInTheDocument();
    });

    test('does not render markdown for user messages', () => {
      render(<ChatMessageComponent message={makeUserMessage()} />);
      expect(screen.queryByTestId('markdown')).not.toBeInTheDocument();
    });

    test('does not show references for user messages', () => {
      const msg = makeUserMessage({ sources: makeSources() });
      const { container } = render(<ChatMessageComponent message={msg} />);
      expect(container.querySelector('.ai-summary-references')).not.toBeInTheDocument();
    });
  });

  describe('Assistant messages', () => {
    test('renders assistant message with markdown', () => {
      render(<ChatMessageComponent message={makeAssistantMessage()} />);
      expect(screen.getByTestId('markdown')).toBeInTheDocument();
    });

    test('applies assistant message styling class', () => {
      const { container } = render(<ChatMessageComponent message={makeAssistantMessage()} />);
      expect(container.querySelector('.chat-message-assistant')).toBeInTheDocument();
      expect(container.querySelector('.assistant-response')).toBeInTheDocument();
    });

    test('does not show references section when no sources', () => {
      const msg = makeAssistantMessage({ sources: [] });
      const { container } = render(<ChatMessageComponent message={msg} />);
      expect(container.querySelector('.ai-summary-references')).not.toBeInTheDocument();
    });

    test('does not show references section when sources undefined', () => {
      const msg = makeAssistantMessage();
      const { container } = render(<ChatMessageComponent message={msg} />);
      expect(container.querySelector('.ai-summary-references')).not.toBeInTheDocument();
    });

    test('does not show references section when sources have no index', () => {
      const msg = makeAssistantMessage({ sources: makeSourcesWithoutIndex() });
      const { container } = render(<ChatMessageComponent message={msg} />);
      expect(container.querySelector('.ai-summary-references')).not.toBeInTheDocument();
    });
  });

  describe('Inline citations and references', () => {
    test('renders references toggle when content has citation markers and sources have indices', () => {
      const msg = makeAssistantMessage({
        content: 'Food security is important [1]. Nutrition too [2].',
        sources: makeSources(),
      });
      const { container } = render(<ChatMessageComponent message={msg} />);
      expect(container.querySelector('.assistant-refs-toggle')).toBeInTheDocument();
    });

    test('references toggle shows document count', () => {
      const msg = makeAssistantMessage({
        content: 'Food security is important [1]. Nutrition too [2].',
        sources: makeSources(),
      });
      const { container } = render(<ChatMessageComponent message={msg} />);
      const toggle = container.querySelector('.assistant-refs-toggle');
      expect(toggle?.textContent).toContain('2 documents');
    });

    test('expands references list on toggle click', () => {
      const msg = makeAssistantMessage({
        content: 'Food security is important [1]. Nutrition too [2].',
        sources: makeSources(),
      });
      const { container } = render(<ChatMessageComponent message={msg} />);

      const toggle = container.querySelector('.assistant-refs-toggle');
      expect(toggle).toBeInTheDocument();
      fireEvent.click(toggle!);

      expect(container.querySelector('.assistant-refs-list')).toBeInTheDocument();
    });

    test('shows source titles in expanded references', () => {
      const msg = makeAssistantMessage({
        content: 'Food security is important [1]. Nutrition too [2].',
        sources: makeSources(),
      });
      const { container } = render(<ChatMessageComponent message={msg} />);

      const toggle = container.querySelector('.assistant-refs-toggle');
      fireEvent.click(toggle!);

      const refGroups = container.querySelectorAll('.ai-summary-ref-group');
      expect(refGroups).toHaveLength(2);
      expect(refGroups[0].textContent).toContain('Global Food Security Report 2024');
      expect(refGroups[1].textContent).toContain('Nutrition Analysis');
    });

    test('shows page number in expanded reference when available', () => {
      const msg = makeAssistantMessage({
        content: 'Food security is important [1].',
        sources: makeSources(),
      });
      const { container } = render(<ChatMessageComponent message={msg} />);

      const toggle = container.querySelector('.assistant-refs-toggle');
      fireEvent.click(toggle!);

      const refLinks = container.querySelectorAll('.ai-summary-ref-link');
      expect(refLinks[0].textContent).toContain('p.15');
    });

    test('calls onSourceClick when reference link is clicked', () => {
      const onSourceClick = jest.fn();
      const msg = makeAssistantMessage({
        content: 'Food security is important [1].',
        sources: makeSources(),
      });
      const { container } = render(
        <ChatMessageComponent message={msg} onSourceClick={onSourceClick} />
      );

      // Expand references
      const toggle = container.querySelector('.assistant-refs-toggle');
      fireEvent.click(toggle!);

      const refLink = container.querySelector('.ai-summary-ref-link');
      expect(refLink).toBeInTheDocument();
      fireEvent.click(refLink!);

      expect(onSourceClick).toHaveBeenCalledWith(
        expect.objectContaining({ docId: 'd1' })
      );
    });
  });
});
