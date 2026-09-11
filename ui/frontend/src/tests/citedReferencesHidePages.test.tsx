import React from 'react';
import { render } from '@testing-library/react';
import { CitedReferences } from '../components/citations/CitedContent';
import { SourceReference } from '../types/api';

const SOURCES: SourceReference[] = [
  { chunkId: 'c1', docId: 'd1', title: 'Doc One', text: '', score: 0, page: 12, index: 1 },
  { chunkId: 'c2', docId: 'd2', title: 'Doc Two', text: '', score: 0, page: 3, index: 2 },
];

describe('CitedReferences hidePages', () => {
  test('shows each document with its page by default', () => {
    render(<CitedReferences content="A [1] and B [2]." sources={SOURCES} collapsible={false} />);
    const groups = document.querySelectorAll('.ai-summary-ref-group');
    expect(Array.from(groups).map((g) => g.textContent)).toEqual([
      'Doc One | 1 p.12',
      'Doc Two | 2 p.3',
    ]);
  });

  test('hidePages lists the documents and numbers without pages', () => {
    render(
      <CitedReferences content="A [1] and B [2]." sources={SOURCES} collapsible={false} hidePages />,
    );
    const groups = document.querySelectorAll('.ai-summary-ref-group');
    expect(Array.from(groups).map((g) => g.textContent)).toEqual(['Doc One | 1', 'Doc Two | 2']);
  });
});
