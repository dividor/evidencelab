/**
 * Rating stars on chat answers were shown only to signed-in users. With
 * `features.anonymous_ratings` on, a visitor who is not signed in sees them
 * too; with it off, or with the user module off, they stay hidden.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';

const mockFlags = { USER_MODULE: true, ANONYMOUS_RATINGS: true };

jest.mock('../config', () => {
  const actual = jest.requireActual('../config');
  return {
    __esModule: true,
    ...actual,
    get USER_MODULE() {
      return mockFlags.USER_MODULE;
    },
    get ANONYMOUS_RATINGS() {
      return mockFlags.ANONYMOUS_RATINGS;
    },
  };
});
jest.mock('react-markdown', () => {
  const React = jest.requireActual('react');
  return {
    __esModule: true,
    default: ({ children }: { children: React.ReactNode }) =>
      React.createElement('div', null, children),
  };
});
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => {} }));
jest.mock('../components/ratings/StarRating', () => {
  const React = jest.requireActual('react');
  return {
    __esModule: true,
    default: () => React.createElement('span', { 'data-testid': 'rating-stars' }),
  };
});
jest.mock('../components/assistant/ToolCallPanel', () => ({
  __esModule: true,
  ToolCallPanel: () => null,
}));

import { ChatMessageComponent } from '../components/assistant/ChatMessage';
import { ChatMessage } from '../types/api';

const answer: ChatMessage = {
  id: 'msg-2',
  role: 'assistant',
  content: 'Food security refers to...',
  createdAt: new Date().toISOString(),
};

const renderAnswer = (isAuthenticated: boolean) =>
  render(
    <ChatMessageComponent
      message={answer}
      isAuthenticated={isAuthenticated}
      onRequestRatingModal={() => {}}
    />
  );

describe('rating stars on a chat answer', () => {
  beforeEach(() => {
    mockFlags.USER_MODULE = true;
    mockFlags.ANONYMOUS_RATINGS = true;
  });

  test('show for an anonymous visitor when anonymous ratings are on', () => {
    renderAnswer(false);
    expect(screen.getByTestId('rating-stars')).toBeInTheDocument();
  });

  test('stay hidden from an anonymous visitor when anonymous ratings are off', () => {
    mockFlags.ANONYMOUS_RATINGS = false;
    renderAnswer(false);
    expect(screen.queryByTestId('rating-stars')).not.toBeInTheDocument();
  });

  test('show for a signed-in user when anonymous ratings are off', () => {
    mockFlags.ANONYMOUS_RATINGS = false;
    renderAnswer(true);
    expect(screen.getByTestId('rating-stars')).toBeInTheDocument();
  });

  test('stay hidden when the user module is off', () => {
    mockFlags.USER_MODULE = false;
    renderAnswer(false);
    expect(screen.queryByTestId('rating-stars')).not.toBeInTheDocument();
  });
});
