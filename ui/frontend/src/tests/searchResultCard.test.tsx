import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import SearchResultCard from '../components/SearchResultCard';
import { SearchResult } from '../types/api';

const buildResult = (overrides: Partial<SearchResult> = {}): SearchResult => ({
  chunk_id: 'chunk-1',
  doc_id: 'doc-1',
  text: 'Sample text',
  page_num: 2,
  headings: [],
  score: 0.9,
  title: 'Report Title',
  metadata: {},
  ...overrides,
});

describe('SearchResultCard', () => {
  test('renders inline references as superscripts', () => {
    const text = 'This is a finding [12] with reference.';
    const result = buildResult({
      chunk_elements: [
        {
          element_type: 'text',
          text,
          label: 'text',
          inline_references: [
            {
              number: 12,
              position: text.indexOf('12'),
              pattern: 'square_bracket',
            },
          ],
          page: 2,
          position_hint: 0.1,
        },
      ],
    });

    render(
      <SearchResultCard
        result={result}
        query="finding"
        isSelected={false}
        onClick={jest.fn()}
        onOpenMetadata={jest.fn()}
        onLanguageChange={jest.fn()}
      />
    );

    const superscripts = document.querySelectorAll('sup.inline-reference-number');
    expect(superscripts).toHaveLength(1);
    expect(superscripts[0].textContent).toBe('12');
  });

  test('renders caption elements with caption styling', () => {
    const result = buildResult({
      chunk_elements: [
        {
          element_type: 'text',
          text: 'FIGURE 1. Example Caption',
          label: 'caption',
          page: 1,
          position_hint: 0.2,
        },
      ],
    });

    render(
      <SearchResultCard
        result={result}
        query=""
        isSelected={false}
        onClick={jest.fn()}
        onOpenMetadata={jest.fn()}
        onLanguageChange={jest.fn()}
      />
    );

    const captions = document.querySelectorAll('.result-snippet-caption');
    expect(captions).toHaveLength(1);
    expect(captions[0].textContent).toContain('FIGURE 1');
  });

  test('metadata button triggers metadata modal', () => {
    const onOpenMetadata = jest.fn();
    const result = buildResult({
      metadata: {
        toc_classified: '[H2] Contents | page 1',
      },
    });

    render(
      <SearchResultCard
        result={result}
        query=""
        isSelected={false}
        onClick={jest.fn()}
        onOpenMetadata={onOpenMetadata}
        onLanguageChange={jest.fn()}
      />
    );

    const metadataButton = screen.getByRole('button', { name: 'Metadata' });
    fireEvent.click(metadataButton);
    expect(onOpenMetadata).toHaveBeenCalledWith(result);
  });
});
