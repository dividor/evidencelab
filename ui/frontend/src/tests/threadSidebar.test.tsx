import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { ThreadSidebar } from '../components/assistant/ThreadSidebar';
import { ThreadListItem } from '../types/api';

const makeThread = (overrides?: Partial<ThreadListItem>): ThreadListItem => ({
  id: 'thread-1',
  title: 'Food security research',
  dataSource: 'test-collection',
  messageCount: 5,
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  ...overrides,
});

const defaultProps = {
  threads: [] as ThreadListItem[],
  activeThreadId: null as string | null,
  onSelectThread: jest.fn(),
  onNewChat: jest.fn(),
  onDeleteThread: jest.fn(),
  onRenameThread: jest.fn(),
  isOpen: true,
  onToggle: jest.fn(),
};

describe('ThreadSidebar', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders close button when open', () => {
    render(<ThreadSidebar {...defaultProps} />);
    expect(screen.getByLabelText('Close')).toBeInTheDocument();
  });

  test('renders header with Chat History title', () => {
    render(<ThreadSidebar {...defaultProps} />);
    expect(screen.getByText('Chat History')).toBeInTheDocument();
  });

  test('renders New button', () => {
    render(<ThreadSidebar {...defaultProps} />);
    expect(screen.getByText('New')).toBeInTheDocument();
  });

  test('shows empty state when no threads', () => {
    render(<ThreadSidebar {...defaultProps} threads={[]} />);
    expect(screen.getByText(/No conversations yet/i)).toBeInTheDocument();
  });

  test('renders thread list items', () => {
    const threads = [
      makeThread({ id: 't1', title: 'Thread One' }),
      makeThread({ id: 't2', title: 'Thread Two' }),
    ];
    render(<ThreadSidebar {...defaultProps} threads={threads} />);
    expect(screen.getByText('Thread One')).toBeInTheDocument();
    expect(screen.getByText('Thread Two')).toBeInTheDocument();
  });

  test('renders long thread titles without truncation', () => {
    const longTitle = 'A'.repeat(60);
    const threads = [makeThread({ title: longTitle })];
    render(<ThreadSidebar {...defaultProps} threads={threads} />);
    // Component renders the full title without truncation
    expect(screen.getByText(longTitle)).toBeInTheDocument();
  });

  test('shows message count', () => {
    const threads = [makeThread({ messageCount: 12 })];
    render(<ThreadSidebar {...defaultProps} threads={threads} />);
    expect(screen.getByText('12 msgs')).toBeInTheDocument();
  });

  test('highlights active thread', () => {
    const threads = [
      makeThread({ id: 't1', title: 'Active Thread' }),
      makeThread({ id: 't2', title: 'Other Thread' }),
    ];
    const { container } = render(
      <ThreadSidebar {...defaultProps} threads={threads} activeThreadId="t1" />
    );
    const activeItem = container.querySelector('.thread-item-active');
    expect(activeItem).toBeInTheDocument();
    expect(activeItem?.textContent).toContain('Active Thread');
  });

  test('calls onSelectThread when thread is clicked', () => {
    const onSelectThread = jest.fn();
    const threads = [makeThread({ id: 't1', title: 'Clickable Thread' })];
    render(
      <ThreadSidebar
        {...defaultProps}
        threads={threads}
        onSelectThread={onSelectThread}
      />
    );

    fireEvent.click(screen.getByText('Clickable Thread'));
    expect(onSelectThread).toHaveBeenCalledWith('t1');
  });

  test('calls onNewChat when New button is clicked', () => {
    const onNewChat = jest.fn();
    render(<ThreadSidebar {...defaultProps} onNewChat={onNewChat} />);

    fireEvent.click(screen.getByText('New'));
    expect(onNewChat).toHaveBeenCalledTimes(1);
  });

  test('calls onDeleteThread when delete button is clicked', () => {
    const onDeleteThread = jest.fn();
    const threads = [makeThread({ id: 't1' })];
    render(
      <ThreadSidebar
        {...defaultProps}
        threads={threads}
        onDeleteThread={onDeleteThread}
      />
    );

    const deleteBtn = screen.getByLabelText('Delete conversation');
    fireEvent.click(deleteBtn);
    expect(onDeleteThread).toHaveBeenCalledWith('t1');
  });

  test('delete click does not trigger thread selection', () => {
    const onSelectThread = jest.fn();
    const onDeleteThread = jest.fn();
    const threads = [makeThread({ id: 't1' })];
    render(
      <ThreadSidebar
        {...defaultProps}
        threads={threads}
        onSelectThread={onSelectThread}
        onDeleteThread={onDeleteThread}
      />
    );

    const deleteBtn = screen.getByLabelText('Delete conversation');
    fireEvent.click(deleteBtn);

    expect(onDeleteThread).toHaveBeenCalledWith('t1');
    expect(onSelectThread).not.toHaveBeenCalled();
  });

  test('calls onToggle when close button is clicked', () => {
    const onToggle = jest.fn();
    render(<ThreadSidebar {...defaultProps} onToggle={onToggle} />);

    const closeBtn = screen.getByLabelText('Close');
    fireEvent.click(closeBtn);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  test('applies open class when sidebar is open', () => {
    const { container } = render(
      <ThreadSidebar {...defaultProps} isOpen={true} />
    );
    expect(container.querySelector('.thread-sidebar-open')).toBeInTheDocument();
  });

  test('renders nothing when sidebar is closed', () => {
    const { container } = render(
      <ThreadSidebar {...defaultProps} isOpen={false} />
    );
    expect(container.querySelector('.thread-sidebar')).not.toBeInTheDocument();
  });

  test('shows Today with time for recent threads', () => {
    const now = new Date();
    const threads = [makeThread({ updatedAt: now.toISOString() })];
    render(<ThreadSidebar {...defaultProps} threads={threads} />);
    // formatDate returns "Today HH:MM" for same-day threads
    expect(screen.getByText(/^Today /)).toBeInTheDocument();
  });
});
