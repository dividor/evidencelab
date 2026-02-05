import React from 'react';
import { render } from '@testing-library/react';

import { formatLinesWithIndentation, renderMarkdownText } from './utils/textHighlighting';

describe('text formatting helpers', () => {
  test('renderMarkdownText renders bold and italic', () => {
    const { container } = render(
      <div>{renderMarkdownText('**Bold** and *italic* text')}</div>
    );

    expect(container.querySelectorAll('strong')).toHaveLength(1);
    expect(container.querySelectorAll('em')).toHaveLength(1);
  });

  test('formatLinesWithIndentation preserves bullet markers', () => {
    const nodes = ['* First item\n* Second item'];
    const { container } = render(
      <div>{formatLinesWithIndentation(nodes)}</div>
    );

    expect(container.textContent).toContain('First item');
    expect(container.textContent).toContain('Second item');
  });
});
