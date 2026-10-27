import React from 'react';
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import axios from 'axios';

import { Documents } from '../components/Documents';
import { useDebouncedFilterText } from '../components/documents/documentsUtils';

jest.mock('react-markdown', () => {
  const React = jest.requireActual('react');
  return {
    __esModule: true,
    default: ({ children }: { children: React.ReactNode }) =>
      React.createElement('div', null, children),
  };
});
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

const DOCUMENTS = '/documents?';
const ONLY_REPORT = 'Only report';
const DEBOUNCE_MS = 500;

const stats = {
  total_documents: 1,
  indexed_documents: 1,
  total_agencies: 1,
  status_breakdown: {},
  agency_breakdown: {},
  agency_indexed: {},
  type_breakdown: {},
  type_indexed: {},
  year_breakdown: {},
  year_indexed: {},
  language_breakdown: {},
  language_indexed: {},
  format_breakdown: {},
  format_indexed: {},
};

const mockApi = () => {
  mockedAxios.get.mockImplementation((url: string) => {
    if (url.includes('/stats')) return Promise.resolve({ data: stats });
    if (url.includes('/facets')) return Promise.resolve({ data: { facets: { title: [] } } });
    if (url.includes(DOCUMENTS)) {
      return Promise.resolve({
        data: {
          documents: [
            {
              id: 'a',
              title: ONLY_REPORT,
              organization: 'UN',
              status: 'indexed',
              document_type: 't',
              published_year: 2024,
              language: 'en',
              file_format: 'pdf',
              page_count: 1,
              file_size_mb: 1,
            },
          ],
          pagination: { total_pages: 1, total_count: 1 },
        },
      });
    }
    return Promise.resolve({ data: {} });
  });
};

const count = (needle: string) =>
  mockedAxios.get.mock.calls.filter((call) => String(call[0]).includes(needle)).length;

/** Let pending promises settle and the debounce window pass. */
const settle = async () => {
  await act(async () => {
    await Promise.resolve();
  });
  await act(async () => {
    jest.advanceTimersByTime(DEBOUNCE_MS + 100);
    await Promise.resolve();
  });
  await act(async () => {
    jest.advanceTimersByTime(DEBOUNCE_MS + 100);
    await Promise.resolve();
  });
};

describe('Documents page requests on mount', () => {
  beforeEach(() => {
    mockedAxios.get.mockReset();
    mockApi();
    jest.useFakeTimers();
  });
  afterEach(() => jest.useRealTimers());

  test('loads the list, facets and stats exactly once', async () => {
    render(<Documents dataSource="uneg" />);
    await settle();
    expect(await screen.findByText(ONLY_REPORT)).toBeInTheDocument();
    expect(count(DOCUMENTS)).toBe(1);
    expect(count('/facets')).toBe(1);
    expect(count('/stats')).toBe(1);
  });

  test('typing in the title search issues one more request, with the search term, after the pause', async () => {
    render(<Documents dataSource="uneg" />);
    await settle();
    expect(count(DOCUMENTS)).toBe(1);

    fireEvent.change(screen.getByPlaceholderText('Search by title'), { target: { value: 'climate' } });
    await act(async () => {
      jest.advanceTimersByTime(DEBOUNCE_MS - 50);
    });
    expect(count(DOCUMENTS)).toBe(1); // still inside the pause

    await settle();
    expect(count(DOCUMENTS)).toBe(2);
    const last = String(mockedAxios.get.mock.calls.filter((c) => String(c[0]).includes(DOCUMENTS)).slice(-1)[0][0]);
    expect(new URLSearchParams(last.split('?')[1]).get('search')).toBe('climate');
  });
});

describe('useDebouncedFilterText', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  test('does not fire on mount', () => {
    const onChange = jest.fn();
    renderHook(() => useDebouncedFilterText('', false, onChange));
    act(() => {
      jest.advanceTimersByTime(DEBOUNCE_MS * 2);
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  test('does not fire when only loading toggles', () => {
    const onChange = jest.fn();
    const { rerender } = renderHook(
      ({ loading }: { loading: boolean }) => useDebouncedFilterText('', loading, onChange),
      { initialProps: { loading: true } },
    );
    rerender({ loading: false });
    rerender({ loading: true });
    rerender({ loading: false });
    act(() => {
      jest.advanceTimersByTime(DEBOUNCE_MS * 2);
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  test('fires once after the pause when the text changes', () => {
    const onChange = jest.fn();
    const { rerender } = renderHook(
      ({ text }: { text: string }) => useDebouncedFilterText(text, false, onChange),
      { initialProps: { text: '' } },
    );
    rerender({ text: 'c' });
    rerender({ text: 'cl' });
    rerender({ text: 'cli' });
    act(() => {
      jest.advanceTimersByTime(DEBOUNCE_MS - 1);
    });
    expect(onChange).not.toHaveBeenCalled();
    act(() => {
      jest.advanceTimersByTime(2);
    });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  test('a change made while loading applies once loading finishes', () => {
    const onChange = jest.fn();
    const { rerender } = renderHook(
      ({ text, loading }: { text: string; loading: boolean }) => useDebouncedFilterText(text, loading, onChange),
      { initialProps: { text: '', loading: false } },
    );
    rerender({ text: 'x', loading: true });
    act(() => {
      jest.advanceTimersByTime(DEBOUNCE_MS * 2);
    });
    expect(onChange).not.toHaveBeenCalled();
    rerender({ text: 'x', loading: false });
    act(() => {
      jest.advanceTimersByTime(DEBOUNCE_MS + 1);
    });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  test('clearing back to the applied text does not fire, clearing an applied term does', () => {
    const onChange = jest.fn();
    const { rerender } = renderHook(
      ({ text }: { text: string }) => useDebouncedFilterText(text, false, onChange),
      { initialProps: { text: '' } },
    );
    rerender({ text: 'abc' });
    rerender({ text: '' }); // back to what the list already shows, before the pause elapsed
    act(() => {
      jest.advanceTimersByTime(DEBOUNCE_MS * 2);
    });
    expect(onChange).not.toHaveBeenCalled();

    rerender({ text: 'abc' });
    act(() => {
      jest.advanceTimersByTime(DEBOUNCE_MS + 1);
    });
    expect(onChange).toHaveBeenCalledTimes(1); // 'abc' applied
    rerender({ text: '' });
    act(() => {
      jest.advanceTimersByTime(DEBOUNCE_MS + 1);
    });
    expect(onChange).toHaveBeenCalledTimes(2); // clearing an applied term is a change
  });
});
