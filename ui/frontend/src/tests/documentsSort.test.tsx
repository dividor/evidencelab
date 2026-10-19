import React from 'react';
import { fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

import { Documents } from '../components/Documents';
import { useDocumentsReload } from '../components/documents/documentsUtils';

// jest.mock calls are hoisted above the imports by babel-jest.
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

const SORT_BY_YEAR = 'Sort by year';
const OLDER_REPORT = 'Older report';

const statsPayload = {
  total_documents: 2,
  indexed_documents: 2,
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

const docRow = (id: string, title: string, year: number) => ({
  id,
  title,
  organization: 'UN',
  status: 'indexed',
  document_type: 'type',
  published_year: year,
  language: 'en',
  file_format: 'pdf',
  page_count: 10,
  file_size_mb: 1.2,
});

const mockApi = () => {
  mockedAxios.get.mockImplementation((url: string) => {
    if (url.includes('/stats')) return Promise.resolve({ data: statsPayload });
    if (url.includes('/facets')) return Promise.resolve({ data: { facets: { title: [] } } });
    if (url.includes('/documents?')) {
      return Promise.resolve({
        data: {
          documents: [docRow('a', OLDER_REPORT, 2019), docRow('b', 'Newer report', 2024)],
          pagination: { total_pages: 1, total_count: 2 },
        },
      });
    }
    return Promise.resolve({ data: {} });
  });
};

const documentsCalls = () =>
  mockedAxios.get.mock.calls.map((call) => String(call[0])).filter((url) => url.includes('/documents?'));

describe('useDocumentsReload', () => {
  // A stable filters object: a fresh {} per render would change the dependency
  // list on its own and mask what these tests are isolating.
  const filters: Record<string, string> = {};

  test('refetches when the sort field or direction changes', () => {
    const load = jest.fn();
    const { rerender } = renderHook(
      ({ field, dir }: { field: string; dir: 'asc' | 'desc' }) =>
        useDocumentsReload(1, null, filters, load, 10, field, dir),
      { initialProps: { field: 'last_updated', dir: 'desc' } },
    );
    expect(load).toHaveBeenCalledTimes(1);
    rerender({ field: 'published_year', dir: 'asc' });
    expect(load).toHaveBeenCalledTimes(2);
    rerender({ field: 'published_year', dir: 'desc' });
    expect(load).toHaveBeenCalledTimes(3);
  });

  test('does not refetch when the loader identity changes but inputs do not', () => {
    const { rerender } = renderHook(
      ({ load }: { load: () => void }) => useDocumentsReload(1, null, filters, load, 10, 'title', 'asc'),
      { initialProps: { load: jest.fn() } },
    );
    const second = jest.fn();
    rerender({ load: second });
    expect(second).not.toHaveBeenCalled();
  });
});

describe('Documents table sorting', () => {
  beforeEach(() => {
    mockedAxios.get.mockReset();
    mockApi();
  });

  test('clicking the Year sort control fetches the first page sorted by year ascending', async () => {
    render(<Documents dataSource="uneg" />);
    expect(await screen.findByText(OLDER_REPORT)).toBeInTheDocument();
    const before = documentsCalls().length;

    fireEvent.click(screen.getByLabelText(SORT_BY_YEAR));

    await waitFor(() => expect(documentsCalls().length).toBeGreaterThan(before));
    const last = new URLSearchParams(documentsCalls().slice(-1)[0].split('?')[1]);
    expect(last.get('sort_by')).toBe('year');
    expect(last.get('order')).toBe('asc');
    expect(last.get('page')).toBe('1');
  });

  test('clicking the same column again flips the direction', async () => {
    render(<Documents dataSource="uneg" />);
    expect(await screen.findByText(OLDER_REPORT)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(SORT_BY_YEAR));
    await waitFor(() => expect(documentsCalls().slice(-1)[0]).toContain('order=asc'));
    fireEvent.click(screen.getByLabelText(SORT_BY_YEAR));
    await waitFor(() => expect(documentsCalls().slice(-1)[0]).toContain('sort_by=year&order=desc'));
  });
});
