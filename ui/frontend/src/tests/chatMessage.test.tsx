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
  },
  {
    chunkId: 'c2',
    docId: 'd2',
    title: 'Nutrition Analysis',
    text: 'Malnutrition rates have decreased...',
    score: 0.85,
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

    test('does not show sources for user messages', () => {
      const msg = makeUserMessage({ sources: makeSources() });
      const { container } = render(<ChatMessageComponent message={msg} />);
      expect(container.querySelector('.chat-message-sources')).not.toBeInTheDocument();
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
      expect(container.querySelector('.chat-bubble-assistant')).toBeInTheDocument();
    });

    test('shows sources when available', () => {
      const msg = makeAssistantMessage({ sources: makeSources() });
      const { container } = render(<ChatMessageComponent message={msg} />);
      expect(container.querySelector('.chat-message-sources')).toBeInTheDocument();
      expect(container.querySelector('.chat-sources-label')).toHaveTextContent('Sources');
    });

    test('renders correct number of source chips', () => {
      const msg = makeAssistantMessage({ sources: makeSources() });
      const { container } = render(<ChatMessageComponent message={msg} />);
      const chips = container.querySelectorAll('.source-chip');
      expect(chips).toHaveLength(2);
    });

    test('does not show sources section when no sources', () => {
      const msg = makeAssistantMessage({ sources: [] });
      const { container } = render(<ChatMessageComponent message={msg} />);
      expect(container.querySelector('.chat-message-sources')).not.toBeInTheDocument();
    });

    test('does not show sources section when sources undefined', () => {
      const msg = makeAssistantMessage();
      const { container } = render(<ChatMessageComponent message={msg} />);
      expect(container.querySelector('.chat-message-sources')).not.toBeInTheDocument();
    });
  });

  describe('Source chips', () => {
    test('displays source title in chip', () => {
      const msg = makeAssistantMessage({ sources: makeSources() });
      render(<ChatMessageComponent message={msg} />);
      expect(screen.getByText(/Global Food Security Report/)).toBeInTheDocument();
    });

    test('truncates long source titles', () => {
      const sources: SourceReference[] = [
        {
          chunkId: 'c1',
          docId: 'd1',
          title: 'A Very Long Document Title That Exceeds Forty Characters Easily',
          text: 'Content',
          score: 0.9,
        },
      ];
      const msg = makeAssistantMessage({ sources });
      const { container } = render(<ChatMessageComponent message={msg} />);
      const chip = container.querySelector('.source-chip');
      expect(chip?.textContent).toContain('...');
    });

    test('expands source preview on click', () => {
      const msg = makeAssistantMessage({ sources: makeSources() });
      const { container } = render(<ChatMessageComponent message={msg} />);

      // Click the first source chip
      const chip = container.querySelector('.source-chip');
      expect(chip).toBeInTheDocument();
      fireEvent.click(chip!);

      // Preview should now be visible
      expect(container.querySelector('.source-preview')).toBeInTheDocument();
      expect(container.querySelector('.source-preview-title')).toHaveTextContent(
        'Global Food Security Report 2024'
      );
    });

    test('shows page number in preview when available', () => {
      const msg = makeAssistantMessage({ sources: makeSources() });
      const { container } = render(<ChatMessageComponent message={msg} />);

      const chip = container.querySelector('.source-chip');
      fireEvent.click(chip!);

      expect(container.querySelector('.source-preview-page')).toHaveTextContent('Page 15');
    });

    test('shows relevance score in preview', () => {
      const msg = makeAssistantMessage({ sources: makeSources() });
      const { container } = render(<ChatMessageComponent message={msg} />);

      const chip = container.querySelector('.source-chip');
      fireEvent.click(chip!);

      expect(container.querySelector('.source-preview-score')).toHaveTextContent('92%');
    });

    test('calls onSourceClick when chip is clicked', () => {
      const onSourceClick = jest.fn();
      const msg = makeAssistantMessage({ sources: makeSources() });
      const { container } = render(
        <ChatMessageComponent message={msg} onSourceClick={onSourceClick} />
      );

      const chip = container.querySelector('.source-chip');
      fireEvent.click(chip!);

      expect(onSourceClick).toHaveBeenCalledWith(
        expect.objectContaining({ docId: 'd1' })
      );
    });
  });
});
