import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { SearchResultsList } from '../components/SearchResultsList';
import type { SearchResult } from '../types/api';

const result = (chunkId: string, docId: string, text: string): SearchResult => ({
  chunk_id: chunkId, doc_id: docId, text, page_num: 3, headings: [], score: 0.9,
  title: `Document ${docId}`, organization: 'WFP', year: '2021', metadata: {},
});

const DOC_A = 'Document A';
const DOC_B = 'Document B';

const RESULTS = [result('a1', 'A', 'alpha one'), result('b1', 'B', 'bravo one'), result('a2', 'A', 'alpha two')];

const renderList = (props: Partial<React.ComponentProps<typeof SearchResultsList>> = {}) =>
  render(
    <SearchResultsList
      results={RESULTS}
      minScore={0}
      loading={false}
      query="alpha"
      hasSearchRun
      selectedDoc={null}
      onResultClick={jest.fn()}
      onOpenMetadata={jest.fn()}
      onLanguageChange={jest.fn()}
      {...props}
    />,
  );

const cards = () => document.querySelectorAll('.result-card');
const headers = () => Array.from(document.querySelectorAll('.result-group-header'));
const row = (title: string) => screen.getByRole('button', { name: new RegExp(`^.?${title}.*excerpts?$`) });

describe('SearchResultsList grouped by document', () => {
  test('flat mode is unchanged: one card per excerpt and no group rows', () => {
    renderList();
    expect(cards()).toHaveLength(3);
    expect(document.querySelector('.result-group')).toBeNull();
  });

  test('grouped mode shows one collapsed row per document with its excerpt count', () => {
    renderList({ groupByDocument: true });
    expect(cards()).toHaveLength(0);
    expect(headers()).toHaveLength(2);
    expect(row(DOC_A)).toHaveAttribute('aria-expanded', 'false');
    expect(row(DOC_B)).toBeInTheDocument();
    expect(screen.getByText('3 excerpts in 2 documents')).toBeInTheDocument();
  });

  test('documents are ordered by their best match, and excerpts inside keep rank order', () => {
    renderList({ groupByDocument: true });
    const titles = Array.from(document.querySelectorAll('.result-group-title')).map((el) => el.textContent);
    expect(titles).toEqual([DOC_A, DOC_B]);
    fireEvent.click(row(DOC_A));
    const texts = Array.from(document.querySelectorAll('.result-group-body .result-card')).map((el) => el.textContent);
    expect(texts[0]).toContain('alpha one');
    expect(texts[1]).toContain('alpha two');
  });

  test('clicking a row expands it to the excerpt cards and clicking again collapses it', () => {
    renderList({ groupByDocument: true });
    const rowA = row(DOC_A);
    fireEvent.click(rowA);
    expect(rowA).toHaveAttribute('aria-expanded', 'true');
    expect(cards()).toHaveLength(2);
    fireEvent.click(rowA);
    expect(cards()).toHaveLength(0);
  });

  test('expand all and collapse all act on every row', () => {
    renderList({ groupByDocument: true });
    fireEvent.click(screen.getByRole('button', { name: 'Expand all' }));
    expect(cards()).toHaveLength(3);
    fireEvent.click(screen.getByRole('button', { name: 'Collapse all' }));
    expect(cards()).toHaveLength(0);
  });

  test('documents picked in the carousel start expanded but can still be collapsed', () => {
    renderList({ groupByDocument: true, defaultExpandedDocIds: ['B'] });
    expect(cards()).toHaveLength(1);
    fireEvent.click(row(DOC_B));
    expect(cards()).toHaveLength(0);
  });

  test('a new result set collapses everything again', () => {
    const view = renderList({ groupByDocument: true });
    fireEvent.click(row(DOC_A));
    expect(cards()).toHaveLength(2);
    view.rerender(
      <SearchResultsList
        results={[result('a9', 'A', 'alpha nine')]}
        minScore={0}
        loading={false}
        query="alpha"
        hasSearchRun
        selectedDoc={null}
        onResultClick={jest.fn()}
        onOpenMetadata={jest.fn()}
        onLanguageChange={jest.fn()}
        groupByDocument
      />,
    );
    expect(cards()).toHaveLength(0);
    expect(screen.getByText('1 excerpt in 1 document')).toBeInTheDocument();
  });

  test('each row shows the document thumbnail, source and year', () => {
    renderList({ groupByDocument: true, thumbnailDataSource: 'wfp' });
    const rowA = row(DOC_A);
    expect(rowA.querySelector('.result-group-source')?.textContent).toBe('WFP');
    expect(rowA.querySelector('.result-group-year')?.textContent).toBe('2021');
    const img = rowA.querySelector('img.result-group-thumb-img') as HTMLImageElement;
    expect(img.getAttribute('src')).toContain('/document/A/thumbnail?data_source=wfp');
  });

  test('a row without a data source shows the thumbnail placeholder instead of a broken image', () => {
    renderList({ groupByDocument: true });
    expect(document.querySelector('.result-group-thumb')).toBeInTheDocument();
    expect(document.querySelector('img.result-group-thumb-img')).toBeNull();
  });

  test('score threshold still applies before grouping', () => {
    renderList({ groupByDocument: true, minScore: 0.95 });
    expect(document.querySelector('.result-group')).toBeNull();
  });
});
