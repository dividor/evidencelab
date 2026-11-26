import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

// html2canvas relies on browser APIs (canvas, document.fonts) that jsdom only
// partially implements. Replace it with a deterministic stub.
jest.mock('html2canvas', () => ({
  __esModule: true,
  default: jest.fn(() =>
    Promise.resolve({
      toDataURL: () => 'data:image/jpeg;base64,STUB',
    }),
  ),
}));

// Stub axios so the modal's submit doesn't try to hit the network.
const mockAxiosPost = jest.fn(() => Promise.resolve({ data: {} }));
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    post: (...args: unknown[]) => mockAxiosPost(...args),
    isAxiosError: jest.fn(() => false),
  },
}));

import FeedbackButton from '../components/feedback/FeedbackButton';

describe('FeedbackButton', () => {
  beforeEach(() => {
    mockAxiosPost.mockClear();
  });

  test('renders a labelled Feedback tab that opens a dialog', () => {
    render(<FeedbackButton />);
    const trigger = screen.getByRole('button', { name: 'Feedback' });
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveAttribute('title', 'Send feedback about this page');
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');
  });

  test('opening the modal does not show URL or screenshot', async () => {
    render(<FeedbackButton />);
    fireEvent.click(screen.getByRole('button', { name: 'Feedback' }));
    await screen.findByRole('heading', { name: /send feedback/i });
    expect(screen.queryByText(/Page:/)).not.toBeInTheDocument();
    expect(screen.queryByAltText(/screenshot/i)).not.toBeInTheDocument();
  });

  test('submit is disabled until both a star rating and a comment are provided', async () => {
    render(<FeedbackButton />);
    fireEvent.click(screen.getByRole('button', { name: 'Feedback' }));
    await screen.findByRole('heading', { name: /send feedback/i });
    const submit = screen.getByRole('button', { name: /^submit$/i });
    expect(submit).toBeDisabled();

    // Comment alone is not enough.
    fireEvent.change(screen.getByPlaceholderText(/Tell us what went well/i), {
      target: { value: 'Looks great' },
    });
    expect(submit).toBeDisabled();

    // Pick 4 stars.
    const stars = document.querySelectorAll('.star-rating-star');
    fireEvent.click(stars[3]);
    expect(submit).not.toBeDisabled();
  });

  test('submit posts rating_type, score, comment, and url', async () => {
    render(<FeedbackButton />);
    fireEvent.click(screen.getByRole('button', { name: 'Feedback' }));
    await screen.findByRole('heading', { name: /send feedback/i });

    fireEvent.change(screen.getByPlaceholderText(/Tell us what went well/i), {
      target: { value: 'Worked well' },
    });
    const stars = document.querySelectorAll('.star-rating-star');
    fireEvent.click(stars[4]); // 5 stars
    fireEvent.click(screen.getByRole('button', { name: /^submit$/i }));

    await screen.findByText(/your feedback was submitted/i);

    expect(mockAxiosPost).toHaveBeenCalledTimes(1);
    const [, body] = mockAxiosPost.mock.calls[0] as [string, Record<string, unknown>];
    expect(body.rating_type).toBe('page_feedback');
    expect(body.score).toBe(5);
    expect(body.comment).toBe('Worked well');
    expect(typeof body.url).toBe('string');
  });
});
