import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { SearchBox } from '../components/SearchBox';

// The search query box grows with long questions (AutoGrowTextarea) and still
// runs the search on Enter, with Shift+Enter reserved for a line break.

const baseProps = {
  isActive: true,
  hasSearched: false,
  query: 'How often have these effects been sustainable?',
  loading: false,
  searchError: null,
  onQueryChange: jest.fn(),
  onSubmit: jest.fn((e: React.FormEvent) => e.preventDefault()),
};

const queryBox = () => screen.getByLabelText('Search query') as HTMLTextAreaElement;

describe.each([
  ['landing page', false],
  ['results page', true],
])('SearchBox query box on the %s', (_label, hasSearched) => {
  beforeEach(() => {
    baseProps.onQueryChange.mockClear();
    baseProps.onSubmit.mockClear();
  });

  test('renders the query as a single-row textarea', () => {
    render(<SearchBox {...baseProps} hasSearched={hasSearched} />);
    const box = queryBox();
    expect(box.tagName).toBe('TEXTAREA');
    expect(box.rows).toBe(1);
    expect(box.className).toBe('search-input');
    expect(box.value).toBe(baseProps.query);
  });

  test('reports edits through onQueryChange', () => {
    render(<SearchBox {...baseProps} hasSearched={hasSearched} />);
    fireEvent.change(queryBox(), { target: { value: 'line one\nline two' } });
    expect(baseProps.onQueryChange).toHaveBeenCalledWith('line one\nline two');
  });

  test('Enter runs the search', () => {
    render(<SearchBox {...baseProps} hasSearched={hasSearched} />);
    fireEvent.keyDown(queryBox(), { key: 'Enter' });
    expect(baseProps.onSubmit).toHaveBeenCalledTimes(1);
  });

  test('Shift+Enter does not run the search', () => {
    render(<SearchBox {...baseProps} hasSearched={hasSearched} />);
    fireEvent.keyDown(queryBox(), { key: 'Enter', shiftKey: true });
    expect(baseProps.onSubmit).not.toHaveBeenCalled();
  });
});
