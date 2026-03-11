import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';

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

// Mock the stream utility so it doesn't try to fetch
jest.mock('../utils/assistantStream', () => ({
  streamAssistantChat: jest.fn(),
}));

// Mock useAuth hook
jest.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ user: null, loading: false }),
}));

import { AssistantTab } from '../components/assistant/AssistantTab';

// JSDOM doesn't implement scrollIntoView
beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
});

describe('AssistantTab', () => {
  test('renders welcome screen when no messages', () => {
    render(<AssistantTab dataSource="test-collection" />);
    expect(screen.getByText('Research Assistant')).toBeInTheDocument();
    expect(screen.getByText(/Ask questions about the documents/)).toBeInTheDocument();
  });

  test('renders example query buttons', () => {
    const examples = [
      'what are the key findings on food security?',
      'summarize the main recommendations',
      'what progress has been made on gender equality?',
    ];
    render(<AssistantTab dataSource="test-collection" exampleQueries={examples} />);
    expect(screen.getByText(/key findings on food security/i)).toBeInTheDocument();
    expect(screen.getByText(/Summarize the main recommendations/i)).toBeInTheDocument();
    expect(screen.getByText(/gender equality/i)).toBeInTheDocument();
  });

  test('clicking example button sets input value', () => {
    const examples = [
      'what are the key findings on food security?',
      'summarize the main recommendations',
      'what progress has been made on gender equality?',
    ];
    const { container } = render(<AssistantTab dataSource="test-collection" exampleQueries={examples} />);

    const exampleBtn = screen.getByText(/key findings on food security/i);
    fireEvent.click(exampleBtn);

    // submitQuery is called directly on click, which adds the query as a user message
    // and clears the input. Verify the user message appears instead.
    expect(screen.getByText('what are the key findings on food security?')).toBeInTheDocument();
  });

  test('renders chat input', () => {
    const { container } = render(<AssistantTab dataSource="test-collection" />);
    expect(container.querySelector('.chat-input-textarea')).toBeInTheDocument();
  });

  test('renders send button', () => {
    render(<AssistantTab dataSource="test-collection" />);
    expect(screen.getByLabelText('Send message')).toBeInTheDocument();
  });

  test('send button is disabled when input is empty', () => {
    render(<AssistantTab dataSource="test-collection" />);
    const sendBtn = screen.getByLabelText('Send message');
    expect(sendBtn).toBeDisabled();
  });

  test('send button enables when input has text', () => {
    const { container } = render(<AssistantTab dataSource="test-collection" />);

    const textarea = container.querySelector('.chat-input-textarea') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'My question' } });

    const sendBtn = screen.getByLabelText('Send message');
    expect(sendBtn).not.toBeDisabled();
  });

  test('does not show sidebar when user is not authenticated', () => {
    const { container } = render(<AssistantTab dataSource="test-collection" />);
    expect(container.querySelector('.thread-sidebar')).not.toBeInTheDocument();
  });

  test('renders assistant container', () => {
    const { container } = render(<AssistantTab dataSource="test-collection" />);
    expect(container.querySelector('.assistant-container')).toBeInTheDocument();
  });

  test('renders chat area', () => {
    const { container } = render(<AssistantTab dataSource="test-collection" />);
    expect(container.querySelector('.assistant-chat-area')).toBeInTheDocument();
  });
});
