import React from 'react';
import axios from 'axios';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { DocumentsPagination } from '../components/documents/DocumentsPagination';
import {
  DEFAULT_PAGE_SIZE,
  PAGE_SIZE_OPTIONS,
  buildDocumentsParams,
  getInitialPageSize,
  useSyncDocumentsUrlParams,
} from '../components/documents/documentsUtils';
import { useDocumentsState } from '../components/documents/useDocumentsState';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined, USER_FEEDBACK: false }));
jest.mock('../hooks/useAuth', () => ({ useAuth: () => ({ user: null }) }));
jest.mock('axios', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));

const PER_PAGE = 'Documents per page';

const setUrl = (search: string) => window.history.replaceState({}, '', `/${search}`);

beforeEach(() => setUrl(''));

describe('page size options', () => {
  test('are 5, 10, 50 and 100, starting at 10', () => {
    expect(PAGE_SIZE_OPTIONS).toEqual([5, 10, 50, 100]);
    expect(DEFAULT_PAGE_SIZE).toBe(10);
  });

  test('the URL can choose one of them, and anything else gives the default', () => {
    setUrl('?page_size=50');
    expect(getInitialPageSize()).toBe(50);
    setUrl('?page_size=37');
    expect(getInitialPageSize()).toBe(DEFAULT_PAGE_SIZE);
    setUrl('?page_size=abc');
    expect(getInitialPageSize()).toBe(DEFAULT_PAGE_SIZE);
  });

  test('the page size is sent to the API', () => {
    const params = buildDocumentsParams({
      currentPage: 2,
      pageSize: 100,
      dataSource: 'wfp',
      filterText: '',
      selectedCategory: null,
      chartView: 'year',
      columnFilters: {},
      sortField: 'year',
      sortDirection: 'desc',
    } as any);
    expect(new URLSearchParams(params).get('page_size')).toBe('100');
  });

  test('a page size other than the default is kept in the URL', () => {
    const { rerender } = renderHook(({ size }) => useSyncDocumentsUrlParams(1, '', 'year', size), {
      initialProps: { size: 50 },
    });
    expect(new URLSearchParams(window.location.search).get('page_size')).toBe('50');
    rerender({ size: DEFAULT_PAGE_SIZE });
    expect(new URLSearchParams(window.location.search).has('page_size')).toBe(false);
  });
});

describe('the paging bar', () => {
  test('offers the page sizes and reports a choice', () => {
    const onPageSizeChange = jest.fn();
    render(
      <DocumentsPagination
        currentPage={1}
        totalPages={5}
        onPageChange={jest.fn()}
        pageSize={10}
        onPageSizeChange={onPageSizeChange}
      />,
    );
    const select = screen.getByLabelText(PER_PAGE) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(['5', '10', '50', '100']);
    expect(select.value).toBe('10');
    fireEvent.change(select, { target: { value: '50' } });
    expect(onPageSizeChange).toHaveBeenCalledWith(50);
    expect(screen.getByText('Next »')).toBeInTheDocument();
  });

  test('with one page there are no page buttons, but the page size can still change', () => {
    render(
      <DocumentsPagination
        currentPage={1}
        totalPages={1}
        onPageChange={jest.fn()}
        pageSize={100}
        onPageSizeChange={jest.fn()}
      />,
    );
    expect(screen.queryByText('Next »')).toBeNull();
    expect(screen.getByLabelText(PER_PAGE)).toHaveValue('100');
  });
});

describe('changing the page size in the Documents Library', () => {
  test('reloads with the new size from the first page', async () => {
    setUrl('?page=3');
    (axios.get as jest.Mock).mockResolvedValue({ data: { documents: [], total_pages: 1, total: 0 } });
    const { result } = renderHook(() => useDocumentsState('wfp'));
    await waitFor(() => expect(axios.get).toHaveBeenCalled());
    expect(result.current.currentPage).toBe(3);
    expect(result.current.pageSize).toBe(DEFAULT_PAGE_SIZE);

    (axios.get as jest.Mock).mockClear();
    act(() => result.current.handlePageSizeChange(100));

    expect(result.current.pageSize).toBe(100);
    expect(result.current.currentPage).toBe(1);
    await waitFor(() => {
      const urls = (axios.get as jest.Mock).mock.calls.map((c) => String(c[0]));
      const listing = urls.find((u) => u.includes('/documents?'));
      expect(listing).toBeDefined();
      const query = new URLSearchParams(listing!.split('?')[1]);
      expect(query.get('page_size')).toBe('100');
      expect(query.get('page')).toBe('1');
    });
  });

  test('reloads when already on the first page', async () => {
    (axios.get as jest.Mock).mockResolvedValue({ data: { documents: [], total_pages: 1, total: 0 } });
    const { result } = renderHook(() => useDocumentsState('wfp'));
    await waitFor(() => expect(axios.get).toHaveBeenCalled());
    // Let the load-time reloads (including the 500 ms debounced filter reload) finish first,
    // so the request below can only come from the page size change.
    await act(() => new Promise((resolve) => setTimeout(resolve, 800)));
    expect(result.current.currentPage).toBe(1);

    (axios.get as jest.Mock).mockClear();
    act(() => result.current.handlePageSizeChange(50));

    await waitFor(
      () => {
        const listing = (axios.get as jest.Mock).mock.calls
          .map((c) => String(c[0]))
          .find((u) => u.includes('/documents?'));
        expect(listing).toBeDefined();
        expect(new URLSearchParams(listing!.split('?')[1]).get('page_size')).toBe('50');
      },
      { timeout: 300 },
    );
  });
});
